"""Side-by-side style board: candidate renders against liked references.

Every image is fitted to the same display size and shown three ways: color,
luminance only (value structure) and blurred (the squint test for big shapes).
Airframe pixels are separated from a flat background estimated at the corners,
then simple diagnostics are measured: dark/mid/light share, saturated-color
share, distinct color families and edge density.  The numbers only help name
what the board shows; they are not an art score or a pass/fail gate.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from artifact_io import ArtifactError, ArtifactTransaction
from inspect_skins import load_font

Image.MAX_IMAGE_PIXELS = 8192 * 8192


def fit(image, side):
    image = image.convert('RGB')
    scale = side / max(image.size)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)


def airframe_mask(rgb, tolerance=14):
    """Pixels that differ from the median corner color; a flat backdrop is assumed."""
    h, w = rgb.shape[:2]
    k = max(2, min(h, w) // 40)
    corners = np.concatenate([rgb[:k, :k].reshape(-1, 3), rgb[:k, -k:].reshape(-1, 3), rgb[-k:, :k].reshape(-1, 3), rgb[-k:, -k:].reshape(-1, 3)])
    background = np.median(corners, axis=0)
    spread = np.abs(corners - background).max(axis=1)
    mask = np.abs(rgb.astype(np.int16) - background.astype(np.int16)).max(axis=2) > tolerance
    # A backdrop that leaves most of the frame 'airframe' is a scene, not a flat studio.
    return mask, bool(np.percentile(spread, 98) <= tolerance and mask.mean() < .7)


def metrics(image):
    rgb = np.asarray(image, np.uint8)
    mask, flat = airframe_mask(rgb)
    if mask.sum() < 50:
        mask = np.ones(rgb.shape[:2], bool); flat = False
    pixels = rgb[mask].astype(np.float32) / 255.
    luminance = pixels @ np.array([.2126, .7152, .0722], np.float32)
    hsv = np.array([colorsys.rgb_to_hsv(*p) for p in pixels[::max(1, len(pixels) // 40000)]], np.float32)
    saturated = (hsv[:, 1] > .45) & (hsv[:, 2] > .3)
    families = 0
    if saturated.any():
        hist, _ = np.histogram(hsv[saturated, 0], bins=12, range=(0, 1))
        families = int((hist / len(hsv) > .02).sum())
    gray = np.asarray(image.convert('L'), np.float32)
    gx, gy = np.zeros_like(gray), np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]; gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    edges = np.hypot(gx, gy) > 48
    inner = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(5))) > 0
    return dict(airframe_pixels=int(mask.sum()), flat_background_detected=flat,
                dark_share=round(float((luminance < .25).mean()), 3), mid_share=round(float(((luminance >= .25) & (luminance <= .7)).mean()), 3),
                light_share=round(float((luminance > .7).mean()), 3), saturated_share=round(float(saturated.mean()), 3),
                saturated_hue_families=families, edge_density=round(float(edges[inner].mean()) if inner.any() else 0., 4))


def board(entries, side, font):
    pad, label = 16, 26
    columns = len(entries)
    cell_h = max(entry[2].height for entry in entries)
    width = pad + columns * (side + pad)
    rows = ['color', 'value (luminance)', 'squint (blur)']
    table_h = 8 * 18 + pad
    height = pad + len(rows) * (cell_h + label + pad) + table_h + label
    canvas = Image.new('RGB', (width, height), (238, 238, 238))
    draw = ImageDraw.Draw(canvas)
    for c, (kind, name, image, stats) in enumerate(entries):
        x = pad + c * (side + pad)
        views = [image, image.convert('L').convert('RGB'), image.filter(ImageFilter.GaussianBlur(radius=max(2, side / 90)))]
        for r, view in enumerate(views):
            y = pad + r * (cell_h + label + pad)
            draw.text((x, y), f'{kind.upper()} · {name}' if r == 0 else rows[r], fill=(30, 30, 30), font=font)
            canvas.paste(view, (x + (side - view.width) // 2, y + label + (cell_h - view.height) // 2))
        y = pad + len(rows) * (cell_h + label + pad)
        lines = [f'dark / mid / light: {stats["dark_share"]:.0%} / {stats["mid_share"]:.0%} / {stats["light_share"]:.0%}',
                 f'saturated area: {stats["saturated_share"]:.0%}', f'saturated hue families: {stats["saturated_hue_families"]}',
                 f'edge density: {stats["edge_density"]:.3f}', '' if stats['flat_background_detected'] else 'background not flat: stats use whole image']
        for i, line in enumerate(lines):
            draw.text((x, y + i * 18), line, fill=(30, 30, 30), font=font)
    draw.text((pad, height - label), 'Diagnostics only: compare what differs, then judge on the model at display size. Not an art score.', fill=(90, 90, 90), font=font)
    return canvas


def run(args):
    sources = [('candidate', p.resolve()) for p in args.candidate] + [('reference', p.resolve()) for p in args.reference]
    if not args.candidate or not args.reference:
        raise ValueError('Give at least one --candidate and one --reference image')
    if not 160 <= args.size <= 2048:
        raise ValueError('--size must be 160-2048 pixels')
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    entries, records = [], []
    for kind, path in sources:
        with Image.open(path) as image:
            fitted = fit(image, args.size)
        stats = metrics(fitted)
        entries.append((kind, path.stem[:28], fitted, stats))
        records.append(dict(role=kind, path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), display_long_edge=args.size, **stats))
    font = load_font(15)
    outputs = [out / 'style-board.png', out / 'style-board.json']
    with ArtifactTransaction(outputs, inputs=[p for _, p in sources], label='style-board') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        board(entries, args.size, font).save(staged[outputs[0]])
        staged[outputs[1]].write_text(json.dumps(dict(schema_version=1, tool='style_board.py', images=records,
                                                      scope='Display-size diagnostics. Character art, background and camera all move these numbers; read them only beside the board and the user feedback.'),
                                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--candidate', type=Path, action='append', default=[], help='Our render at a comparable camera (repeatable)')
    parser.add_argument('--reference', type=Path, action='append', default=[], help='Liked reference image (repeatable)')
    parser.add_argument('--size', type=int, default=560, help='Common display long edge in pixels (default 560)')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    for record in run(parser.parse_args(argv)):
        name = '/'.join(Path(record['path']).parts[-2:])
        print(f"{record['role']:9} {name}: dark/mid/light {record['dark_share']:.0%}/{record['mid_share']:.0%}/{record['light_share']:.0%}, "
              f"saturated {record['saturated_share']:.0%} in {record['saturated_hue_families']} hue families, edges {record['edge_density']:.3f}"
              + ('' if record['flat_background_detected'] else ' (background not flat: whole-image numbers)'))


if __name__ == '__main__':
    main()
