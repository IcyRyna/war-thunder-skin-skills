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


def flat_code(plane):
    """Most common value of a normal channel: the code the map uses for a flat surface."""
    return int(np.bincount(plane.ravel(), minlength=256).argmax())


def run(args):
    normal_path = args.normal.resolve()
    inputs = [normal_path] + ([args.protect.resolve()] if args.protect else [])
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    if not (0 <= args.r <= 255 and 0 <= args.b <= 255):
        raise ValueError('--r and --b are 0-255')
    if not 0 <= args.structure <= 1:
        raise ValueError('--structure is 0-1 (share of the original groove depth kept)')
    original = np.asarray(Image.open(normal_path).convert('RGBA'))
    h, w = original.shape[:2]
    g0 = args.flat_g if args.flat_g is not None else flat_code(original[:, :, 1])
    a0 = args.flat_a if args.flat_a is not None else flat_code(original[:, :, 3])
    coat = np.empty_like(original)
    coat[:, :, 0], coat[:, :, 2] = args.r, args.b
    for ch, flat in ((1, g0), (3, a0)):
        keep = flat + args.structure * (original[:, :, ch].astype(np.float32) - flat)
        coat[:, :, ch] = np.clip(np.rint(keep), 0, 255).astype(np.uint8)
    protected = np.zeros((h, w), bool)
    if args.protect:
        mask = Image.open(args.protect).convert('L')
        if mask.size != (w, h):
            mask = mask.resize((w, h), Image.Resampling.NEAREST)
        protected = np.asarray(mask) > 127
        coat[protected] = original[protected]
    names = {'R': 0, 'G': 1, 'B': 2, 'A': 3}
    outputs = [out / 'material.png'] + [out / f'material_{c}.png' for c in names] + [out / 'receipt.json']
    with ArtifactTransaction(outputs, inputs=inputs, label='coat-material') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        Image.fromarray(coat, 'RGBA').save(staged[outputs[0]])
        for c, i in names.items():
            Image.fromarray(coat[:, :, i], 'L').save(staged[out / f'material_{c}.png'])
        receipt = dict(schema_version=1, tool='coat_material.py', contract='R inverted roughness, B metallic, G/A normal (assumed; confirm per resource)',
                       inputs={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}, size=[w, h],
                       coat=dict(R=args.r, B=args.b, flat_G=g0, flat_A=a0, structure_kept=args.structure),
                       protected_share=round(float(protected.mean()), 4),
                       scope='Material only; the color map is untouched. Check in game or with finish_preview.py in two environments.')
        staged[outputs[-1]].write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--normal', type=Path, required=True, help='Original packed material map (PNG/TGA): size and flat normal code')
    parser.add_argument('--r', type=int, default=173, help='Coat smoothness R (default 173, the reference dark-coat value; 228 for a white/pale coat)')
    parser.add_argument('--b', type=int, default=0, help='Coat metallic B (default 0; up to ~56 for a pale pearl coat)')
    parser.add_argument('--structure', type=float, default=0., help='Share of the original G/A groove depth kept, 0-1 (default 0: flat)')
    parser.add_argument('--flat-g', type=int, help='Flat code for G (default: most common G value of the original)')
    parser.add_argument('--flat-a', type=int, help='Flat code for A (default: most common A value of the original)')
    parser.add_argument('--protect', type=Path, help='Mask, white keeps the original RGBA (e.g. exhaust nozzles); resized nearest')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    receipt = run(parser.parse_args(argv))
    print(json.dumps(dict(size=receipt['size'], coat=receipt['coat'], protected_share=receipt['protected_share'])))


if __name__ == '__main__':
    main()
