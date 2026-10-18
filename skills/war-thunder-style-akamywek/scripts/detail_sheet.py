"""Full-size detail sheet: crops of the final colour map at 1:1 next to a reference at the same metric scale.

An 8192 colour map shown at 1600 px hides everything that decides how the skin reads up close in game:
2 px lines, broken or stair-stepped edges, haze around art, stray pixels of the original texture.  This
tool cuts named or automatically chosen regions out of the full-size map, enlarges them with nearest
neighbour (so pixels stay pixels), and places a reference crop beside each one, rescaled so both show
the same number of millimetres per screen pixel.

  --color MAP --px-per-m 510 --region spine=3900,3300,480 [--region ...] [--auto 4]
  --ref f2a=REF_MAP --ref-px-per-m 550 --ref-region spine=2700,3550,480 [...]
  --zoom 2 --out DIR [--composa-copy]

Regions are x,y,width in pixels of their own map (height is two thirds of the width).  Reference regions
pair with our regions by name.  --auto N adds the N windows of our map with the most edge detail, spread
apart, which is where line and edge faults show first.  Writes sheet.png, crops/*.png, regions.json and
composa-calls.json (open the map and render each region at full size in Composa); --composa-copy also
writes color.png, because Composa does not open TGA or DDS.
Dependencies: NumPy, Pillow.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from artifact_io import ArtifactTransaction

Image.MAX_IMAGE_PIXELS = 8192 * 8192 * 2
MAX_CELL = 1000     # crops larger than this are cut on the sheet; the crops/ files stay whole
LABEL = 34


def parse_region(text: str) -> tuple[str, tuple[int, int, int]]:
    name, _, spec = text.partition('=')
    try:
        x, y, w = (int(float(v)) for v in spec.split(','))
    except ValueError:
        raise ValueError(f'Region must be name=x,y,width: {text}') from None
    if not name or w < 16:
        raise ValueError(f'Region needs a name and a width of at least 16 px: {text}')
    return name, (x, y, w)


def auto_regions(image: Image.Image, count: int, width: int) -> list[tuple[str, tuple[int, int, int]]]:
    """Windows with the most edge energy on a quarter-size copy, at least one window apart."""
    if count <= 0:
        return []
    small = np.asarray(image.convert('L').resize((image.width // 4, image.height // 4), Image.Resampling.BOX), np.float32)
    gx, gy = np.abs(np.diff(small, axis=1))[:-1], np.abs(np.diff(small, axis=0))[:, :-1]
    energy = np.minimum(gx + gy, 60)
    w, h = max(width // 4, 4), max(width * 2 // 3 // 4, 4)
    s = np.pad(energy, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    win = s[h:, w:] - s[:-h, w:] - s[h:, :-w] + s[:-h, :-w]
    picks: list[tuple[int, int]] = []
    order = np.argsort(win, axis=None)[::-1]
    for flat in order[:200000]:
        y, x = divmod(int(flat), win.shape[1])
        if all(abs(x - a) >= w or abs(y - b) >= h for a, b in picks):
            picks.append((x, y))
            if len(picks) == count:
                break
    return [(f'auto-{i + 1}', (x * 4, y * 4, width)) for i, (x, y) in enumerate(picks)]


def cut(image: Image.Image, box: tuple[int, int, int], scale: float, zoom: int) -> Image.Image:
    """Crop box (x, y, w), resample by scale to the common metric scale, then enlarge by zoom with nearest neighbour."""
    x, y, w = box
    h = w * 2 // 3
    crop = image.crop((x, y, x + w, y + h))
    if abs(scale - 1) > 1e-3:
        crop = crop.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
    crop = crop.resize((crop.width * zoom, crop.height * zoom), Image.Resampling.NEAREST)
    return crop


def font(size: int):
    for name in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/bahnschrift.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def run(args) -> dict:
    color_path = Path(args.color).resolve()
    ours = Image.open(color_path).convert('RGB')
    regions = [parse_region(r) for r in args.region or []]
    regions += auto_regions(ours, args.auto, args.auto_width)
    if not regions:
        raise ValueError('Give at least one --region or --auto N')
    names = [n for n, _ in regions]
    if len(set(names)) != len(names):
        raise ValueError('Region names must be unique')
    ref = ref_path = None
    ref_regions = dict(parse_region(r) for r in args.ref_region or [])
    if args.ref:
        ref_name, _, path = args.ref.partition('=')
        ref_path = Path(path or ref_name).resolve()
        ref_label = ref_name if path else ref_path.stem
        ref = Image.open(ref_path).convert('RGB')
        unknown = set(ref_regions) - set(names)
        if unknown:
            raise ValueError(f'Reference regions without a matching --region: {sorted(unknown)}')
    elif ref_regions:
        raise ValueError('--ref-region needs --ref')
    # Both columns show the same millimetres per screen pixel: the denser map is shrunk to the coarser one.
    ref_scale = 1.0
    if ref is not None and args.px_per_m and args.ref_px_per_m:
        ref_scale = args.px_per_m / args.ref_px_per_m
    crops, records, rows = {}, [], []
    for name, box in regions:
        mine = cut(ours, box, 1.0, args.zoom)
        crops[f'{name}.png'] = mine
        record = dict(name=name, box=dict(x=box[0], y=box[1], width=box[2], height=box[2] * 2 // 3))
        if args.px_per_m:
            record['width_m'] = round(box[2] / args.px_per_m, 3)
        theirs = None
        if ref is not None and name in ref_regions:
            rbox = ref_regions[name]
            theirs = cut(ref, rbox, ref_scale, args.zoom)
            crops[f'{name}-ref.png'] = theirs
            record['reference_box'] = dict(x=rbox[0], y=rbox[1], width=rbox[2], height=rbox[2] * 2 // 3, scale=round(ref_scale, 4))
        records.append(record)
        rows.append((name, box, mine, theirs, ref_regions.get(name)))
    cell_w = min(MAX_CELL, max(max(r[2].width, r[3].width if r[3] else 0) for r in rows))
    heights = [min(MAX_CELL, max(r[2].height, r[3].height if r[3] else 0)) for r in rows]
    columns = 2 if ref is not None else 1
    sheet = Image.new('RGB', (columns * (cell_w + 16) + 16, 60 + sum(h + LABEL + 16 for h in heights)), (24, 24, 26))
    draw = ImageDraw.Draw(sheet)
    title = f'1:1 x{args.zoom}  {color_path.name}' + (f'  |  {ref_label}' if ref is not None else '')
    if args.px_per_m:
        title += f'  |  {1000 / args.px_per_m:.1f} mm per map pixel'
    draw.text((16, 14), title, font=font(24), fill=(235, 235, 235))
    y0 = 60
    for (name, box, mine, theirs, rbox), h in zip(rows, heights):
        draw.text((16, y0), f'{name}  x{box[0]} y{box[1]} w{box[2]}', font=font(20), fill=(255, 255, 255))
        sheet.paste(mine.crop((0, 0, min(mine.width, cell_w), min(mine.height, h))), (16, y0 + LABEL))
        if theirs is not None:
            draw.text((32 + cell_w, y0), f'{ref_label}  x{rbox[0]} y{rbox[1]} w{rbox[2]}', font=font(20), fill=(255, 255, 255))
            sheet.paste(theirs.crop((0, 0, min(theirs.width, cell_w), min(theirs.height, h))), (32 + cell_w, y0 + LABEL))
        y0 += h + LABEL + 16
    out = Path(args.out).resolve()
    composa_source = out / 'color.png' if args.composa_copy else color_path
    calls = [dict(name='open_document', arguments=dict(path=str(composa_source)))]
    for record in records:
        b = record['box']
        calls.append(dict(name='render', arguments=dict(x=b['x'], y=b['y'], width=b['width'], height=b['height'],
                                                         maxSide=max(b['width'], b['height']))))
    receipt = dict(schema_version=1, tool='detail_sheet.py', color=str(color_path), size=list(ours.size), px_per_m=args.px_per_m,
                   reference=str(ref_path) if ref_path else None, reference_px_per_m=args.ref_px_per_m, zoom=args.zoom,
                   regions=records,
                   composa=('open composa-calls.json with composa_mcp.py --calls; renders are full size' if composa_source.suffix.lower()
                            in ('.png', '.jpg', '.jpeg', '.webp') else 'Composa cannot open this format; rerun with --composa-copy'),
                   scope='Visual evidence for a person or agent to judge edges, line weight and haze at full size. It does not judge them itself.')
    outputs = [out / 'sheet.png', out / 'regions.json', out / 'composa-calls.json'] + [out / 'crops' / n for n in crops]
    if args.composa_copy:
        outputs.append(out / 'color.png')
    inputs = [color_path] + ([ref_path] if ref_path else [])
    with ArtifactTransaction(outputs, inputs=inputs, label='detail-sheet') as tx:
        staged = {o: tx.stage(o) for o in outputs}
        sheet.save(staged[out / 'sheet.png'])
        for n, im in crops.items():
            im.save(staged[out / 'crops' / n])
        staged[out / 'regions.json'].write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        staged[out / 'composa-calls.json'].write_text(json.dumps(calls, indent=1) + '\n', encoding='utf-8')
        if args.composa_copy:
            ours.save(staged[out / 'color.png'], compress_level=1)
        tx.commit()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--color', required=True, help='Our colour map at full size (TGA/PNG/DDS readable by Pillow)')
    parser.add_argument('--px-per-m', type=float, help='Texel density of our map on the inspected surfaces (pixels per metre)')
    parser.add_argument('--region', action='append', help='name=x,y,width in our map (repeatable)')
    parser.add_argument('--auto', type=int, default=0, help='Also add the N windows with the most edge detail')
    parser.add_argument('--auto-width', type=int, default=480, help='Width of automatic windows in pixels (default 480)')
    parser.add_argument('--ref', help='Reference colour map, as label=path or path')
    parser.add_argument('--ref-px-per-m', type=float, help='Texel density of the reference map (F-2A by Akamywek: about 550 on wings, 510 on the fuselage)')
    parser.add_argument('--ref-region', action='append', help='name=x,y,width in the reference map; pairs with --region of the same name')
    parser.add_argument('--zoom', type=int, default=2, help='Nearest-neighbour enlargement after the 1:1 crop (default 2)')
    parser.add_argument('--composa-copy', action='store_true', help='Also write color.png for Composa (it does not open TGA or DDS)')
    parser.add_argument('--out', required=True, help='New or empty output directory')
    args = parser.parse_args(argv)
    if not 1 <= args.zoom <= 8:
        parser.error('--zoom is 1-8')
    receipt = run(args)
    print(json.dumps({k: receipt[k] for k in ('color', 'size', 'zoom', 'composa')} | {'regions': [r['name'] for r in receipt['regions']]}))


if __name__ == '__main__':
    main()
