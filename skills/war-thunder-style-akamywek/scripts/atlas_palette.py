"""Compare colour families inside matching UV regions of several color atlases.

Each region is given in normalised UV-image coordinates (0-1, origin top-left),
so a 4K and an 8K atlas of the same airframe line up.  Pixels are grouped into
families: dark / mid / light neutrals and chromatic hues in 30-degree bins;
vivid share counts strong signature-like colour (saturation > .5, value > .45).
The board shows every crop with its family bar; the JSON lists shares, the
largest family and the quiet-base share (pixels close to the largest dark or
mid neutral).  Use it to read an atlas the way the editor shows it, beside a
liked reference; the numbers are not an art score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artifact_io import ArtifactError, ArtifactTransaction
from inspect_skins import load_font

Image.MAX_IMAGE_PIXELS = 8192 * 8192
HUES = ['red', 'orange', 'yellow', 'lime', 'green', 'teal', 'cyan', 'azure', 'blue', 'violet', 'magenta', 'rose']
SHOW = dict(dark=(40, 40, 44), mid=(120, 120, 124), light=(232, 232, 228))


def parse_named(text, kind):
    name, sep, value = text.partition('=')
    if not sep or not name or not value:
        raise ValueError(f'{kind} must be NAME=VALUE: {text}')
    return name, value


def parse_box(text):
    values = [float(v) for v in text.split(',')]
    if len(values) != 4 or not (0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
        raise ValueError('Region must be x0,y0,x1,y1 with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1')
    return values


def parse_hex(text):
    text = text.strip().lstrip('#')
    if len(text) != 6:
        raise ValueError(f'Colors are #rrggbb: {text}')
    return np.array([int(text[i:i + 2], 16) for i in (0, 2, 4)])


def families(pixels):
    """Family label per pixel: 'dark', 'mid', 'light' or a hue name."""
    rgb = pixels.astype(np.float32) / 255.
    high, low = rgb.max(axis=1), rgb.min(axis=1)
    chroma = high - low
    saturation = np.where(high > 0, chroma / np.maximum(high, 1e-6), 0)
    luminance = rgb @ np.array([.2126, .7152, .0722], np.float32)
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    hue = np.zeros(len(rgb), np.float32)
    safe = np.maximum(chroma, 1e-6)
    hue = np.where(high == r, ((g - b) / safe) % 6, hue)
    hue = np.where(high == g, (b - r) / safe + 2, hue)
    hue = np.where(high == b, (r - g) / safe + 4, hue)
    hue = (hue * 60 + 15) % 360
    label = np.empty(len(rgb), object)
    neutral = (saturation < .28) | (high < .18)
    label[neutral & (luminance < .25)] = 'dark'
    label[neutral & (luminance >= .25) & (luminance <= .7)] = 'mid'
    label[neutral & (luminance > .7)] = 'light'
    bins = (hue // 30).astype(int) % 12
    for index, name in enumerate(HUES):
        label[~neutral & (bins == index)] = name
    return label


def analyse(crop, ignore, tolerance):
    pixels = np.asarray(crop.convert('RGB')).reshape(-1, 3).astype(np.int16)
    keep = np.ones(len(pixels), bool)
    for color in ignore:
        keep &= np.abs(pixels - color).max(axis=1) > tolerance
    pixels = pixels[keep]
    if len(pixels) < 100:
        raise ValueError('Region has too few pixels after ignored colors')
    label = families(pixels)
    names, counts = np.unique(label, return_counts=True)
    share = {str(n): round(float(c / len(label)), 4) for n, c in sorted(zip(names, counts), key=lambda x: -x[1])}
    neutrals = [n for n in ('dark', 'mid') if n in share]
    base = max(neutrals, key=lambda n: share[n]) if neutrals else None
    quiet = 0.
    if base:
        chosen = pixels[label == base]
        mode = np.median(chosen, axis=0)
        quiet = float((np.abs(pixels - mode).max(axis=1) <= 18).mean())
    hues = {n: s for n, s in share.items() if n in HUES}
    rgb = pixels.astype(np.float32) / 255.
    high = rgb.max(axis=1)
    vivid = float((((high - rgb.min(axis=1)) / np.maximum(high, 1e-6) > .5) & (high > .45)).mean())
    swatch = {n: '#%02x%02x%02x' % tuple(int(v) for v in np.median(pixels[label == n], axis=0)) for n in share}
    return dict(pixels=int(len(pixels)), family_share=share, family_color=swatch, largest_family=next(iter(share)),
                quiet_base_share=round(quiet, 4), saturated_share=round(float(sum(hues.values())), 4), vivid_share=round(vivid, 4),
                hue_families_over_2pct=sorted(n for n, s in hues.items() if s >= .02),
                light_share=share.get('light', 0.))


def board(rows, regions, font, width=900):
    pad, title, bar = 16, 24, 26
    blocks = []
    for region_name, _ in regions:
        crops = [(atlas, data[region_name]) for atlas, data in rows]
        h = max(int(width * c['crop'].height / c['crop'].width) for _, c in crops)
        blocks.append((region_name, crops, h))
    height = pad + sum(title + len(c) * (h + bar + pad + title) for _, c, h in blocks)
    canvas = Image.new('RGB', (width + 2 * pad + 420, height), (240, 240, 240))
    draw = ImageDraw.Draw(canvas)
    y = pad
    for region_name, crops, h in blocks:
        draw.text((pad, y), f'region {region_name}', fill=(20, 20, 20), font=font); y += title
        for atlas, info in crops:
            stats = info['stats']
            draw.text((pad, y), atlas, fill=(40, 40, 40), font=font)
            view = info['crop'].convert('RGB').resize((width, int(width * info['crop'].height / info['crop'].width)), Image.Resampling.LANCZOS)
            canvas.paste(view, (pad, y + title))
            x = pad
            for name, share in stats['family_share'].items():
                w = int(round(width * share))
                if w:
                    draw.rectangle([x, y + title + h + 4, x + w, y + title + h + bar], fill=stats['family_color'][name])
                x += w
            text = [f'quiet base {stats["quiet_base_share"]:.0%}', f'vivid {stats["vivid_share"]:.0%}  hues {",".join(stats["hue_families_over_2pct"]) or "-"}',
                    f'light neutral {stats["light_share"]:.0%}', 'largest: ' + stats['largest_family']]
            text += [f'{n} {s:.1%}' for n, s in list(stats['family_share'].items())[:6]]
            for i, line in enumerate(text):
                draw.text((width + 2 * pad, y + title + i * 20), line, fill=(30, 30, 30), font=font)
            y += title + h + bar + pad
    return canvas


def run(args):
    atlases = [parse_named(a, '--atlas') for a in args.atlas]
    regions = [(n, parse_box(b)) for n, b in (parse_named(r, '--region') for r in args.region)]
    if not atlases or not regions:
        raise ValueError('Give at least one --atlas NAME=PATH (two or more to compare) and one --region NAME=x0,y0,x1,y1')
    if len({n for n, _ in atlases}) != len(atlases) or len({n for n, _ in regions}) != len(regions):
        raise ValueError('Atlas and region names must be unique')
    ignore = [parse_hex(c) for c in args.ignore_color]
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    rows, records = [], {}
    inputs = []
    for name, path in atlases:
        path = Path(path).resolve(); inputs.append(path)
        with Image.open(path) as image:
            image = image.convert('RGB'); w, h = image.size
            data = {}
            for region_name, (x0, y0, x1, y1) in regions:
                crop = image.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
                if max(crop.size) > 1600:
                    crop.thumbnail((1600, 1600), Image.Resampling.BOX)
                data[region_name] = dict(crop=crop, stats=analyse(crop, ignore, args.tolerance))
        rows.append((name, data))
        records[name] = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=[w, h],
                             regions={r: d['stats'] for r, d in data.items()})
    outputs = [out / 'atlas-palette.png', out / 'atlas-palette.json']
    with ArtifactTransaction(outputs, inputs=inputs, label='atlas-palette') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        board(rows, regions, load_font(15)).save(staged[outputs[0]])
        staged[outputs[1]].write_text(json.dumps(dict(schema_version=1, tool='atlas_palette.py', regions=dict(regions),
                                                      ignored_colors=args.ignore_color, atlases=records,
                                                      scope='Colour-family areas inside matching normalised atlas regions; read beside the editor view and references.'),
                                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--atlas', action='append', default=[], help='NAME=PATH of a color atlas (repeatable; one profiles a reference, several compare)')
    parser.add_argument('--region', action='append', default=[], help='NAME=x0,y0,x1,y1 in normalised image coordinates (repeatable)')
    parser.add_argument('--ignore-color', action='append', default=[], help='#rrggbb padding/background to drop, e.g. an author fill color')
    parser.add_argument('--tolerance', type=int, default=40, help='Max channel distance for --ignore-color (default 40)')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    for name, record in run(parser.parse_args(argv)).items():
        for region, stats in record['regions'].items():
            print(f'{name:16} {region:8} quiet base {stats["quiet_base_share"]:.0%}, vivid {stats["vivid_share"]:.0%} '
                  f'{stats["hue_families_over_2pct"]}, light {stats["light_share"]:.0%}, largest {stats["largest_family"]}')


if __name__ == '__main__':
    main()
