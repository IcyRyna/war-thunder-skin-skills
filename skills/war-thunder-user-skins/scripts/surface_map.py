"""Surface maps for a vector_paint design: where each chart can safely carry lines.

For every chart of a design JSON, the selected triangles are drawn in the chart's
own metre coordinates and classed as flat (projection keeps >= 80% of the area),
curving (50-80%), steep (< 50%: widths and patterns streak there), protected
(mechanical texels from --protect) or lost (the original UV shares the texel
with an earlier chart, and the earlier chart wins it, as in vector_paint).  The
design's polygons, strokes and image/text placements are drawn on top and
scored by item type: colour fields are at risk on steep or lost ground (they
may bleed past the real edge on purpose); lines, type and portraits also when
they cross mechanical texels or run off the surface.  Use it before placing lines and type, and after moving
them; it does not replace looking at the model.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artifact_io import ArtifactError, ArtifactTransaction
from inspect_skins import load_font
from surface_preview import load_geometry
from vector_paint import parse_axis, select_charts, stroke_outline

Image.MAX_IMAGE_PIXELS = 8192 * 8192
OFF, FLAT, CURVING, STEEP, SHARED, PROTECTED = range(6)
NAMES = ['off-surface', 'flat', 'curving', 'steep', 'lost-to-earlier-chart', 'protected']
COLORS = [(250, 250, 250), (200, 205, 210), (236, 190, 110), (220, 80, 70), (165, 110, 210), (80, 140, 230)]
RISKY = {'polygon': (STEEP, SHARED), 'stroke': (OFF, STEEP, SHARED, PROTECTED),
         'text': (OFF, STEEP, SHARED, PROTECTED), 'image': (STEEP, SHARED, PROTECTED)}


def chart_coords(points, axes, index):
    """World points (..., 3) -> chart (u, v) using the chart's axis specs."""
    out = []
    for slot in (0, 2):
        axis, mode = axes[index, slot], axes[index, slot + 1]
        value = points[..., axis]
        out.append(np.abs(value) if mode == 2 else -value if mode == 1 else value)
    return np.stack(out, axis=-1)


def classify(geometry, assignment, axes, protect, atlas=2048):
    world, uvs = geometry['triangles'].astype(np.float64), geometry['uvs'].astype(np.float64)
    area = np.linalg.norm(np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0]), axis=1) * .5
    classes = np.full(len(world), OFF, np.int8)
    # First claimant per texel: charts are painted in order and an earlier chart wins shared texels.
    owners = np.full((atlas, atlas), 1 << 30, np.int32)
    for chart in np.unique(assignment[assignment >= 0]):
        mask = Image.new('L', (atlas, atlas), 0)
        draw = ImageDraw.Draw(mask)
        for tri in np.flatnonzero(assignment == chart):
            draw.polygon([(u * (atlas - 1), (1 - v) * (atlas - 1)) for u, v in uvs[tri]], fill=1)
        claimed = np.asarray(mask, bool)
        owners[claimed] = np.minimum(owners[claimed], int(chart))
    for tri in np.flatnonzero(assignment >= 0):
        chart = assignment[tri]
        p = chart_coords(world[tri], axes, chart)
        flat = .5 * abs((p[1, 0] - p[0, 0]) * (p[2, 1] - p[0, 1]) - (p[2, 0] - p[0, 0]) * (p[1, 1] - p[0, 1]))
        ratio = flat / max(area[tri], 1e-30)
        classes[tri] = FLAT if ratio >= .8 else CURVING if ratio >= .5 else STEEP
        c = uvs[tri].mean(axis=0)
        x, y = min(atlas - 1, max(0, int(c[0] * (atlas - 1)))), min(atlas - 1, max(0, int((1 - c[1]) * (atlas - 1))))
        if owners[y, x] < chart:
            classes[tri] = SHARED
        if protect is not None:
            px = min(protect.shape[1] - 1, int(c[0] * (protect.shape[1] - 1)))
            py = min(protect.shape[0] - 1, int((1 - c[1]) * (protect.shape[0] - 1)))
            if protect[py, px]:
                classes[tri] = PROTECTED
    return classes


def view_depth(triangles, chart):
    """Distance toward the viewer for each triangle: larger means closer to the outside."""
    used = {parse_axis(chart['u'])[0], parse_axis(chart['v'])[0]}
    depth_axis = ({0, 1, 2} - used).pop()
    centroid = triangles.mean(axis=1)[:, depth_axis]
    spec = chart.get('facing')
    if spec:
        axis, mode = parse_axis(spec)
        if axis == depth_axis:
            return np.abs(centroid) if mode == 2 else -centroid if mode == 1 else centroid
    return np.abs(centroid)


def item_shapes(design, chart_ids):
    """(label, chart, kind, polygon points in chart metres) for every design item."""
    shapes = []
    for layer in design.get('layers', []):
        for item in layer.get('items', []):
            label = item.get('id', layer['name'])
            if item['chart'] not in chart_ids:
                continue
            if item['type'] == 'polygon':
                shapes.append((label, item['chart'], 'polygon', [tuple(p) for p in item['points']]))
            else:
                taper = item.get('taper', 'none')
                length = sum(math.dist(a, b) for a, b in zip(item['points'], item['points'][1:]))
                span = item.get('taper_length', length)
                outline = stroke_outline(item['points'], item['width'], span if taper in ('start', 'both') else 0,
                                         span if taper in ('end', 'both') else 0)
                shapes.append((label, item['chart'], 'stroke', [tuple(p) for p in outline]))
        for spec in layer.get('images', []):
            if spec['chart'] not in chart_ids:
                continue
            if 'text' in spec:
                h = float(spec['height']) * 1.3
                w = float(spec['height']) * .62 * len(spec['text']) * (1 + float(spec.get('tracking', 0)))
            else:
                w = float(spec['width'])
                h = w * .75 if 'crop' not in spec else w * (spec['crop'][3] - spec['crop'][1]) / (spec['crop'][2] - spec['crop'][0])
            a = math.radians(float(spec.get('rotation', 0)))
            cx, cy = spec['center']
            corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
            pts = [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in corners]
            shapes.append((spec.get('id', layer['name']), spec['chart'], 'text' if 'text' in spec else 'image', pts))
    return shapes


def render_chart(chart, index, geometry, assignment, axes, classes, shapes, scale, font):
    world = geometry['triangles'].astype(np.float64)
    tris = np.flatnonzero(assignment == index)
    pts = chart_coords(world[tris], axes, index)
    item_pts = [np.asarray(s[3]) for s in shapes]
    every = np.concatenate([pts.reshape(-1, 2), *item_pts]) if item_pts else pts.reshape(-1, 2)
    lo, hi = every.min(axis=0) - .3, every.max(axis=0) + .3
    header = 44  # legend strip above the chart
    width, height = int((hi[0] - lo[0]) * scale) + 1, int((hi[1] - lo[1]) * scale) + 1 + header
    to_px = lambda u, v: ((u - lo[0]) * scale, header + (hi[1] - v) * scale)
    cls = Image.new('L', (width, height), OFF)
    draw = ImageDraw.Draw(cls)
    # Painter's order along the viewing axis: hidden inner surfaces that share the chart
    # coordinates (e.g. nacelle interiors under a top chart) are covered by the outer skin.
    for tri in tris[np.argsort(view_depth(world[tris], chart))]:
        draw.polygon([to_px(*q) for q in pts[np.searchsorted(tris, tri)]], fill=int(classes[tri]))
    grid = np.asarray(cls)
    rgb = Image.fromarray(np.asarray(COLORS, np.uint8)[grid], 'RGB')
    pen = ImageDraw.Draw(rgb)
    for u in range(math.ceil(lo[0]), math.floor(hi[0]) + 1):
        pen.line([to_px(u, lo[1]), to_px(u, hi[1])], fill=(150, 170, 190) if u % 5 else (60, 110, 200))
        pen.text((to_px(u, lo[1])[0] + 2, height - 16), str(u), fill=(0, 0, 0), font=font)
    for v in np.arange(math.ceil(lo[1] * 2) / 2, hi[1], .5):
        pen.line([to_px(lo[0], v), to_px(hi[0], v)], fill=(190, 200, 215))
        pen.text((2, to_px(lo[0], v)[1] - 8), f'{v:g}', fill=(0, 0, 0), font=font)
    scores = []
    for (label, _, kind, poly), arr in zip(shapes, item_pts):
        pen.line([to_px(*q) for q in poly] + [to_px(*poly[0])], fill=(20, 20, 20), width=2 if kind in ('polygon', 'stroke') else 1)
        mask = Image.new('L', (width, height), 0)
        ImageDraw.Draw(mask).polygon([to_px(*q) for q in poly], fill=1)
        inside = grid[np.asarray(mask, bool)]
        if not inside.size:
            continue
        counts = {NAMES[c]: round(float((inside == c).mean()), 3) for c in range(6) if (inside == c).any()}
        risk = float(np.isin(inside, RISKY[kind]).mean())
        scores.append(dict(id=label, kind=kind, risky_share=round(risk, 3), ground=counts))
    pen.text((6, 4), f'chart {chart["id"]}  u={chart["u"]} v={chart["v"]}  (metres)', fill=(0, 0, 0), font=font)
    for i, (name, color) in enumerate(zip(NAMES, COLORS)):
        pen.rectangle([6 + i * 165, 22, 20 + i * 165, 36], fill=color, outline=(0, 0, 0))
        pen.text((24 + i * 165, 22), name, fill=(0, 0, 0), font=font)
    totals = {NAMES[c]: round(float((grid == c).sum() / max(1, (grid != OFF).sum())), 3) for c in range(1, 6)}
    return rgb, scores, totals


def run(args):
    design_path, geometry_path = args.design.resolve(), args.geometry.resolve()
    inputs = [design_path, geometry_path] + ([args.protect.resolve()] if args.protect else [])
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    design = json.loads(design_path.read_text(encoding='utf-8'))
    if not isinstance(design.get('charts'), list) or not design['charts']:
        raise ValueError('Design needs a nonempty charts list')
    geometry = load_geometry(geometry_path, allow_repeat_uv=True)
    assignment, axes, _, quality, warnings = select_charts(design, geometry)
    protect = np.asarray(Image.open(args.protect).convert('L')) > 0 if args.protect else None
    classes = classify(geometry, assignment, axes, protect)
    font = load_font(13)
    charts = [c for c in design['charts'] if not args.chart or c['id'] in args.chart]
    outputs = [out / f'{c["id"]}.png' for c in charts] + [out / 'surface-map.json']
    report = dict(schema_version=1, tool='surface_map.py', design=str(design_path), charts={}, risky_items=[], warnings=warnings,
                  classes=dict(flat='projection keeps >= 80% of area', curving='50-80%', steep='< 50%, lines and patterns streak',
                               **{'lost-to-earlier-chart': 'texel shared with an earlier chart, which wins it; reorder charts or move the item'},
                               protected='mechanical texels from --protect', **{'off-surface': 'no triangle of this chart'}),
                  risk_rule={k: [NAMES[c] for c in v] for k, v in RISKY.items()})
    with ArtifactTransaction(outputs, inputs=inputs, label='surface-map') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        for chart in charts:
            index = [c['id'] for c in design['charts']].index(chart['id'])
            shapes = item_shapes(design, {chart['id']})
            image, scores, totals = render_chart(chart, index, geometry, assignment, axes, classes, shapes, args.scale, font)
            image.save(staged[out / f'{chart["id"]}.png'])
            report['charts'][chart['id']] = dict(area_share=totals, items=scores, **quality[chart['id']])
            report['risky_items'] += [dict(chart=chart['id'], **s) for s in scores if s['risky_share'] > args.threshold]
        report['risky_items'].sort(key=lambda s: -s['risky_share'])
        staged[out / 'surface-map.json'].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--design', type=Path, required=True, help='vector_paint design JSON (charts required; layers optional)')
    parser.add_argument('--protect', type=Path, help='Atlas mask of mechanical texels (nonzero = protected)')
    parser.add_argument('--chart', action='append', default=[], help='Only these chart ids (repeatable)')
    parser.add_argument('--scale', type=float, default=60, help='Pixels per metre (default 60)')
    parser.add_argument('--threshold', type=float, default=.15, help='Report items with more risky ground than this share (default 0.15)')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    report = run(parser.parse_args(argv))
    for item in report['risky_items']:
        print(f"RISK {item['chart']:12} {item['id']:28} {item['risky_share']:.0%} on {item['ground']}")
    if not report['risky_items']:
        print('No item over the risk threshold.')


if __name__ == '__main__':
    main()
