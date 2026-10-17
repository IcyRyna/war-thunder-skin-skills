"""Extract panel lines and rivets as a clean overlay layer for a fresh coat.

A full repaint usually erases the airframe's own panel lines, which makes the
livery read as plastic.  The packed normal map keeps those grooves and rivets
without grime, old stencils or lighting, so this tool band-passes the confirmed
normal channels (G/A by default), optionally mixes in thin dark detail from the
original color map, and writes one RGBA layer: a single line color whose alpha
is the structure strength.  Put it above the paint as a multiply/normal layer
and mask it off faces and main names in the editor.
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
CHANNELS = {'r': 0, 'g': 1, 'b': 2, 'a': 3}


def gaussian(plane, sigma):
    """Separable Gaussian blur with edge clamping (float32)."""
    if sigma <= 0:
        return plane
    radius = max(1, int(round(sigma * 3)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-.5 * (x / sigma) ** 2); kernel /= kernel.sum()
    out = plane
    for axis in (0, 1):
        padded = np.pad(out, [(radius, radius) if a == axis else (0, 0) for a in (0, 1)], mode='edge')
        acc = np.zeros_like(out)
        for i, weight in enumerate(kernel):
            acc += weight * (padded[i:i + out.shape[0]] if axis == 0 else padded[:, i:i + out.shape[1]])
        out = acc
    return out


def band(plane, fine, coarse):
    return gaussian(plane, fine) - gaussian(plane, coarse)


def strength_from_normal(rgba, channels, fine, coarse):
    planes = [rgba[:, :, CHANNELS[c]].astype(np.float32) for c in channels]
    energy = np.sqrt(sum(band(p, fine, coarse) ** 2 for p in planes))
    # Grooves show as paired light/dark edges; merge them into one line.
    return gaussian(energy, max(fine, .6))


def strength_from_color(rgb, fine, coarse):
    lum = rgb[:, :, :3].astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32)
    return np.maximum(-band(lum, fine, coarse), 0)


def normalise(strength, floor, percentile):
    top = float(np.percentile(strength, percentile))
    if top <= 0:
        return np.zeros_like(strength)
    value = np.clip(strength / top, 0, 1)
    return np.clip((value - floor) / max(1 - floor, 1e-6), 0, 1)


def run(args):
    normal_path = args.normal.resolve()
    inputs = [normal_path] + [p.resolve() for p in (args.color, args.exclude) if p is not None]
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    channels = args.channels.lower()
    if not channels or any(c not in CHANNELS for c in channels) or len(set(channels)) != len(channels):
        raise ValueError('--channels lists distinct normal channels such as ga')
    if not 0 < args.fine < args.coarse <= 32:
        raise ValueError('Need 0 < --fine < --coarse <= 32 source pixels')
    if not 0 < args.opacity <= 1 or not 0 <= args.floor < 1 or not 0 <= args.color_weight <= 1:
        raise ValueError('--opacity in (0,1], --floor in [0,1), --color-weight in [0,1]')
    normal = np.asarray(Image.open(normal_path).convert('RGBA'))
    strength = normalise(strength_from_normal(normal, channels, args.fine, args.coarse), args.floor, args.percentile)
    size = normal.shape[1], normal.shape[0]
    if args.color is not None:
        color = Image.open(args.color).convert('RGB')
        if color.size != size:
            color = color.resize(size, Image.Resampling.LANCZOS)
        detail = normalise(strength_from_color(np.asarray(color), args.fine, args.coarse), args.floor, args.percentile)
        strength = np.maximum(strength, detail * args.color_weight)
    target = args.size or size[0]
    if not 256 <= target <= 8192:
        raise ValueError('--size must be 256-8192')
    alpha = Image.fromarray(np.rint(strength * args.opacity * 255).astype(np.uint8), 'L')
    if target != size[0]:
        alpha = alpha.resize((target, round(target * size[1] / size[0])), Image.Resampling.LANCZOS)
    if args.exclude is not None:
        mask = Image.open(args.exclude).convert('L')
        if mask.size != alpha.size:
            raise ValueError('--exclude must match the output size')
        alpha = Image.fromarray((np.asarray(alpha).astype(np.float32) * (1 - np.asarray(mask, np.float32) / 255)).astype(np.uint8), 'L')
    rgb = tuple(int(args.line_color.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
    layer = Image.new('RGBA', alpha.size, rgb + (0,)); layer.putalpha(alpha)
    preview = Image.alpha_composite(Image.new('RGBA', alpha.size, (66, 67, 71, 255)), layer)
    preview.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    outputs = [out / 'structure.png', out / 'structure-preview.png', out / 'receipt.json']
    with ArtifactTransaction(outputs, inputs=inputs, label='structure-layer') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        layer.save(staged[outputs[0]]); preview.convert('RGB').save(staged[outputs[1]])
        receipt = dict(schema_version=1, tool='structure_layer.py', inputs={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
                       normal_channels=channels, band_pass_px=[args.fine, args.coarse], floor=args.floor, percentile=args.percentile,
                       color_weight=args.color_weight if args.color else 0, opacity=args.opacity, line_color=args.line_color,
                       size=list(alpha.size), covered_share=round(float((np.asarray(alpha) > 8).mean()), 4),
                       scope='Clean structure overlay derived from the normal map; it does not change the packed material. Mask faces and main type in the editor.')
        staged[outputs[2]].write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--normal', type=Path, required=True, help='Original packed normal/material map (PNG/TGA)')
    parser.add_argument('--channels', default='ga', help='Normal channels to read (default ga; confirm per resource)')
    parser.add_argument('--color', type=Path, help='Optional original color map for thin dark detail missing from the normal map')
    parser.add_argument('--color-weight', type=float, default=.0, help='0-1 weight of color-map detail (default 0: grime and stencils stay out)')
    parser.add_argument('--fine', type=float, default=.7, help='Fine blur in source pixels (default 0.7)')
    parser.add_argument('--coarse', type=float, default=3., help='Coarse blur in source pixels; wider features are dropped (default 3)')
    parser.add_argument('--floor', type=float, default=.18, help='Noise floor after normalising (default 0.18)')
    parser.add_argument('--percentile', type=float, default=99.5, help='Strength percentile mapped to full line (default 99.5)')
    parser.add_argument('--opacity', type=float, default=.55, help='Maximum line opacity (default 0.55)')
    parser.add_argument('--line-color', default='#1b1b1d', help='Line color (default #1b1b1d)')
    parser.add_argument('--size', type=int, help='Output width; defaults to the normal map width')
    parser.add_argument('--exclude', type=Path, help='Mask at output size; white removes structure (faces, main names)')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    receipt = run(parser.parse_args(argv))
    print(json.dumps(dict(size=receipt['size'], covered_share=receipt['covered_share']), ensure_ascii=False))


if __name__ == '__main__':
    main()
