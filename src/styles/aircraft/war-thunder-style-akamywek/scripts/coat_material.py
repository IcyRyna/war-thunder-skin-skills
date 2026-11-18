"""Write a one-coat packed material map: the whole airframe as a single clean lacquer.

A full anime repaint reads clean when the paint is one smooth, even coat: one
smoothness value, no metal, and a flat normal so panel grooves do not shade the
paint in every light.  The reference author ships exactly that (one constant
packed map for the whole aircraft), and his structure only glints in highlights.
This tool takes the original packed map for its size and flat normal code and
writes that coat; --structure keeps a fraction of the original G/A grooves so they
show faintly in reflections, and --protect keeps chosen texels (e.g. exhaust
nozzles) exactly original.  Feed the channel PNGs to build_skin.py --channel.

Contract assumed: R inverted roughness (higher = smoother), B metallic, G/A normal.
Confirm it per resource before use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from artifact_io import ArtifactError, ArtifactTransaction

Image.MAX_IMAGE_PIXELS = 8192 * 8192
FLAT_DETAIL_RGBA = (198, 128, 255, 128)
PRESETS = {
    'dark': dict(r=173, b=0, structure=0.0, flat_g=None, flat_a=None),
    'pale': dict(r=228, b=56, structure=0.0, flat_g=None, flat_a=None),
    # Calibrated from [Bronya][Cy30][D-9A][SFW] (su_30sm_n.dds / n_n.dds): silky metallic reflection without mirror/glass blow-out.
    'metallic-satin': dict(r=163, b=188, structure=0.0, flat_g=128, flat_a=128),
}
# Verified 3-stage titanium/carbon-ceramic exhaust upgrade (keeps native G/A normal rivets/louvers, removes raw silver/tan stock shroud)
EXHAUST_ZONES = {
    'shroud': dict(gain=(0.35, 0.37, 0.42), lift=(4, 5, 8), rb=(150, 224)),      # Dark gunmetal titanium heat-shield barrels
    'noz_outer': dict(gain=(0.62, 0.66, 0.74), lift=(6, 8, 13), rb=(138, 240)),  # Anodized dark titanium turkey-feather petals
    'noz_inner': dict(gain=(0.38, 0.40, 0.45), lift=(4, 5, 8), rb=(86, 36)),     # Matte carbon-ceramic afterburner liner
}


def grade_metallic_zone(rgb_slice: np.ndarray, gain: tuple[float, float, float], lift: tuple[float, float, float]) -> np.ndarray:
    """Convert raw warm silver/tan metal RGB pixels to cool smoked titanium/gunmetal preserving panel detail."""
    f = rgb_slice.astype(np.float32)
    luma = 0.299 * f[:, 0] + 0.587 * f[:, 1] + 0.114 * f[:, 2]
    neutral = np.stack([luma * gain[0] + lift[0], luma * gain[1] + lift[1], luma * gain[2] + lift[2]], axis=1)
    return np.clip(np.rint(neutral), 0, 255).astype(np.uint8)


def apply_exhaust_finish(color_rgba: np.ndarray, packed_rgba: np.ndarray, shroud_color_mask: np.ndarray,
                         noz_outer_color_mask: np.ndarray, noz_inner_color_mask: np.ndarray,
                         shroud_n_mask: np.ndarray, noz_outer_n_mask: np.ndarray, noz_inner_n_mask: np.ndarray) -> None:
    """Apply 3-stage titanium/ceramic albedo grading and R/B PBR values in-place while preserving stock G/A normals."""
    for spec, cmask, nmask in (
        (EXHAUST_ZONES['shroud'], shroud_color_mask, shroud_n_mask),
        (EXHAUST_ZONES['noz_outer'], noz_outer_color_mask, noz_outer_n_mask),
        (EXHAUST_ZONES['noz_inner'], noz_inner_color_mask, noz_inner_n_mask),
    ):
        color_rgba[cmask, :3] = grade_metallic_zone(color_rgba[cmask, :3], spec['gain'], spec['lift'])
        packed_rgba[nmask, 0], packed_rgba[nmask, 2] = spec['rb']


def flat_code(plane):
    """Most common value of a normal channel: the code the map uses for a flat surface."""
    return int(np.bincount(plane.ravel(), minlength=256).argmax())


def protection_mask(path, size):
    """Convert an aligned, nonzero-means-protected colour-atlas mask to material texels."""
    with Image.open(path) as bitmap:
        sw, sh = bitmap.size
        w, h = size
        if sw * h != sh * w:
            raise ValueError('Protection mask aspect differs from material UV; supply a registered mask')
        if w >= sw and w % sw == 0:
            selected = np.asarray(bitmap.convert('L').resize(size, Image.Resampling.NEAREST)) != 0
            return selected, 'native' if w == sw else 'nearest-up'
        if sw >= w and sw % w == 0:
            factor = sw // w
            selected = np.asarray(bitmap.convert('L')).reshape(h, factor, w, factor).any(axis=(1, 3))
            return selected, 'any-covered-down'
        raise ValueError('Noninteger mask-to-material scale: supply a registered native material mask')


def run(args):
    preset = PRESETS[args.preset] if getattr(args, 'preset', None) else PRESETS['dark']
    r_val = preset['r'] if getattr(args, 'r', None) is None else args.r
    b_val = preset['b'] if getattr(args, 'b', None) is None else args.b
    structure = preset['structure'] if getattr(args, 'structure', None) is None else args.structure
    flat_g_opt = preset['flat_g'] if getattr(args, 'flat_g', None) is None else args.flat_g
    flat_a_opt = preset['flat_a'] if getattr(args, 'flat_a', None) is None else args.flat_a
    flat_detail_out = getattr(args, 'flat_detail_out', None)

    normal_path = args.normal.resolve()
    inputs = [normal_path] + ([args.protect.resolve()] if args.protect else [])
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    if not (0 <= r_val <= 255 and 0 <= b_val <= 255):
        raise ValueError('--r and --b are 0-255')
    if not 0 <= structure <= 1:
        raise ValueError('--structure is 0-1 (share of the original groove depth kept)')
    if any(v is not None and not 0 <= v <= 255 for v in (flat_g_opt, flat_a_opt)):
        raise ValueError('--flat-g and --flat-a must be byte values')
    with Image.open(normal_path) as bitmap:
        original = np.asarray(bitmap.convert('RGBA'))
    h, w = original.shape[:2]
    g0 = flat_g_opt if flat_g_opt is not None else flat_code(original[:, :, 1])
    a0 = flat_a_opt if flat_a_opt is not None else flat_code(original[:, :, 3])
    coat = np.empty_like(original)
    coat[:, :, 0], coat[:, :, 2] = r_val, b_val
    for ch, flat in ((1, g0), (3, a0)):
        keep = flat + structure * (original[:, :, ch].astype(np.float32) - flat)
        coat[:, :, ch] = np.clip(np.rint(keep), 0, 255).astype(np.uint8)
    protected = np.zeros((h, w), bool)
    mask_sampling = None
    if args.protect:
        protected, mask_sampling = protection_mask(args.protect, (w, h))
        coat[protected] = original[protected]
    names = {'R': 0, 'G': 1, 'B': 2, 'A': 3}
    outputs = [out / 'material.png'] + [out / f'material_{c}.png' for c in names] + [out / 'receipt.json']
    detail_path = flat_detail_out.resolve() if flat_detail_out else None
    if detail_path:
        if detail_path.exists():
            raise ArtifactError('--flat-detail-out target already exists')
        outputs.append(detail_path)
    with ArtifactTransaction(outputs, inputs=inputs, label='coat-material') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        Image.fromarray(coat, 'RGBA').save(staged[outputs[0]])
        for c, i in names.items():
            Image.fromarray(coat[:, :, i], 'L').save(staged[out / f'material_{c}.png'])
        if detail_path:
            detail_img = np.empty((512, 512, 4), dtype=np.uint8)
            detail_img[:, :] = FLAT_DETAIL_RGBA
            Image.fromarray(detail_img, 'RGBA').save(staged[detail_path])
        receipt = dict(schema_version=1, tool='coat_material.py', contract='R inverted roughness, B metallic, G/A normal (assumed; confirm per resource)',
                       inputs={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}, size=[w, h],
                       preset=getattr(args, 'preset', None),
                       coat=dict(R=r_val, B=b_val, flat_G=g0, flat_A=a0, structure_kept=structure),
                       protected_share=round(float(protected.mean()), 4),
                       protected_texels=int(protected.sum()), mask_sampling=mask_sampling,
                       flat_detail_normal=str(detail_path) if detail_path else None,
                       scope='Material only; the color map is untouched. Check in game or with finish_preview.py in two environments.')
        staged[outputs[5]].write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--normal', type=Path, required=True, help='Original packed material map (PNG/TGA): size and flat normal code')
    parser.add_argument('--preset', choices=sorted(PRESETS), help='Named finish preset: dark (R173/B0), pale (R228/B56), or metallic-satin (R163/B188 flat 128)')
    parser.add_argument('--r', type=int, help='Coat smoothness R (default 173, the reference dark-coat value; 228 for pale; 163 for metallic-satin)')
    parser.add_argument('--b', type=int, help='Coat metallic B (default 0; ~56 for pale; 188 for metallic-satin)')
    parser.add_argument('--structure', type=float, help='Share of the original G/A groove depth kept, 0-1 (default 0: flat)')
    parser.add_argument('--flat-g', type=int, help='Flat code for G (default: most common G value of the original, or preset flat_g)')
    parser.add_argument('--flat-a', type=int, help='Flat code for A (default: most common A value of the original, or preset flat_a)')
    parser.add_argument('--protect', type=Path, help='Registered grayscale UV mask: nonzero preserves original RGBA. Integer downscale protects any covered source texel.')
    parser.add_argument('--flat-detail-out', type=Path, help='Optional output PNG path for a 512x512 neutral flat detail normal (RGBA 198,128,255,128)')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    receipt = run(parser.parse_args(argv))
    print(json.dumps(dict(size=receipt['size'], coat=receipt['coat'], protected_share=receipt['protected_share'])))


if __name__ == '__main__':
    main()
