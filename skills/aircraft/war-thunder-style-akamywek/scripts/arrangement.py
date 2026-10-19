"""Construction-line graphics: cut a chart by a few straight lines and fill chosen cells.

Akamywek's F-2A spine group is built this way on the unwrapped map: a handful of lines in two slant
families (about 12 and 18 degrees to the fuselage axis) plus cuts parallel to the axis, and every white or
dark shape is a cell (or an outline of a cell) of that line arrangement.  Writing a design as lines and
cells keeps edges exactly straight, keeps parallel edges exactly parallel and lets a change of one line
move every shape that shares it.

  python -B arrangement.py --spec spec.json --out items.json [--design design.json --layer NAME]

spec.json (metres in the chart's design frame; a UV-frame chart keeps the lines straight in the atlas):
  {"chart": "dorsal", "mirror": "y",
   "lines": [{"id": "outer", "deg": 11.85, "apex": -1.862},          # through (apex, 0) at deg to +x
             {"id": "cut1", "deg": 0, "at": 0.254},                  # parallel to x at y = at
             {"id": "e1", "deg": 20.8, "through": [-0.285, -0.676]}],
   "clip": [x0, x1, y0, y1],
   "fills": [{"id": "arm", "seed": [0.6, -0.5], "fill": "white"},    # the cell containing seed
             {"id": "echo", "seed": [0.1, -0.63], "fill": "white", "outline": 0.0095,
              "using": ["e1", "e1r", "e1top", "e1bottom"]}]}

With "mirror": "y" every line and seed is repeated mirrored across y = 0 (lines given by apex mirror
their slope).  A cell is the intersection of the half-planes of all lines on the seed's side, so it is
convex, and neighbouring cells share edges exactly: filling both leaves no seam.  "outline" keeps only a
band of that width inside the cell's edges (the same lines moved inward), with straight mitred corners.
"using" limits a fill to the named lines (mirrors included), so other lines of the group do not cut it.
"halves": "separate" (with "mirror": "y") cuts each half only by its own lines: a mirrored line that crosses into
the other half (any line not through y = 0, e.g. "through" a point on a spine edge) would otherwise cut the cells
there too and the two halves come out different.

Region and cuts (the F-2A dorsal logic: one white area cut by equal dark bands, so every arm and step shares the
same lines):
  "region": [{"line": {...}, "keep": [x, y]}, ...]       # lines bounding the white area, a point on the kept side
  "cuts":   [{"deg": 12, "through": [x, y], "toward": [x2, y2], "width": 0.09}, ...]
            # a dark band of that width from the line toward the given point; "limit": [{"line", "keep"}] bounds it
  "cut_fill": "white"                                     # fill of the cells that remain
Given for the half y > 0, every cell of the region that lies outside all cuts becomes a fill; with "mirror": "y"
the other half is built from mirrored lines only ("halves" is set to "separate").  Keep each remaining piece at
least 8 cm wide and each cut at least 7 cm: thinner reads as scratches at the in-game viewing distance.
Writes vector_paint.py polygon items (outlines use "holes"); --design/--layer append them to a design.
Dependencies: none beyond the standard library.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def line_of(spec):
    """(nx, ny, c): points p with n.p <= c lie on the 'left' side; n is the unit normal of the line."""
    th = math.radians(float(spec['deg']))
    d = (math.cos(th), math.sin(th))
    if 'apex' in spec:
        p = (float(spec['apex']), 0.0)
    elif 'at' in spec:
        if abs(math.sin(th)) > 1e-9:
            raise ValueError(f'line {spec.get("id")}: "at" is for lines parallel to x (deg 0)')
        p = (0.0, float(spec['at']))
    elif 'through' in spec:
        p = tuple(map(float, spec['through']))
    else:
        raise ValueError(f'line {spec.get("id")} needs apex, at or through')
    n = (-d[1], d[0])
    return n[0], n[1], n[0] * p[0] + n[1] * p[1]


def on_axis(spec):
    """True for the line y = 0 itself (its mirror is itself).  A horizontal line given by "through" is on the axis
    only when its point has y = 0; checking only "at" (missing "at" read as 0) left such lines unmirrored."""
    if abs(float(spec['deg'])) > 1e-12:
        return False
    if 'at' in spec:
        return abs(float(spec['at'])) < 1e-12
    if 'through' in spec:
        return abs(float(spec['through'][1])) < 1e-12
    return False


def mirrored(spec):
    out = dict(spec)
    out['deg'] = -float(spec['deg'])
    if 'at' in spec:
        out['at'] = -float(spec['at'])
    if 'through' in spec:
        out['through'] = [float(spec['through'][0]), -float(spec['through'][1])]
    out['id'] = f'{spec.get("id", "line")}~'
    return out


def clip_halfplane(poly, n, c):
    """Sutherland-Hodgman: keep the part of convex poly with n.p <= c."""
    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        da, db = n[0] * a[0] + n[1] * a[1] - c, n[0] * b[0] + n[1] * b[1] - c
        if da <= 0:
            out.append(a)
        if (da < 0 < db) or (db < 0 < da):
            t = da / (da - db)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return out


def cell(lines, seed, clip, inset=0.0):
    x0, x1, y0, y1 = clip
    poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if inset:
        poly = [(x0 + inset, y0 + inset), (x1 - inset, y0 + inset), (x1 - inset, y1 - inset), (x0 + inset, y1 - inset)]
    for nx, ny, c in lines:
        side = nx * seed[0] + ny * seed[1] - c
        if abs(side) < 1e-12:
            raise ValueError(f'seed {seed} lies on a construction line; move it into the cell')
        if side < 0:
            poly = clip_halfplane(poly, (nx, ny), c - inset)
        else:
            poly = clip_halfplane(poly, (-nx, -ny), -c - inset)
        if len(poly) < 3:
            return []
    # drop repeated vertices
    clean = []
    for p in poly:
        if not clean or math.dist(p, clean[-1]) > 1e-9:
            clean.append(p)
    if len(clean) > 1 and math.dist(clean[0], clean[-1]) <= 1e-9:
        clean.pop()
    return clean if len(clean) >= 3 else []


def area(poly):
    return .5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])))


def offset_line(line, dist, toward):
    """The same line moved `dist` metres toward the point `toward`, written with "through"."""
    n0, n1, c = line_of(line)
    s = -1 if n0 * toward[0] + n1 * toward[1] - c < 0 else 1
    if 'apex' in line:
        p = (float(line['apex']), 0.)
    elif 'at' in line:
        p = (0., float(line['at']))
    else:
        p = tuple(map(float, line['through']))
    return dict(deg=line['deg'], through=[round(p[0] + s * n0 * dist, 6), round(p[1] + s * n1 * dist, 6)])


def _side(line, p):
    n0, n1, c = line_of(line)
    return n0 * p[0] + n1 * p[1] - c


def expand_cuts(spec, step=.01):
    """Turn "region" + "cuts" into lines and fills: the cells of the region (half y > 0) outside every cut band."""
    spec = dict(spec)
    lines, region, bands = list(spec.get('lines', [])), [], []
    for k, r in enumerate(spec['region']):
        l = dict(r['line'], id=r['line'].get('id', f'region{k}'))
        lines.append(l); region.append((l, r['keep']))
    for k, cut in enumerate(spec.get('cuts', [])):
        if float(cut.get('width', 0)) <= 0:
            raise ValueError(f'cut {k}: width must be positive')
        a = {kk: cut[kk] for kk in ('deg', 'apex', 'at', 'through') if kk in cut}
        a['id'] = cut.get('id', f'cut{k}') + '-a'
        b = dict(offset_line(a, float(cut['width']), cut['toward']), id=cut.get('id', f'cut{k}') + '-b')
        lim = []
        for j, m in enumerate(cut.get('limit', [])):
            ml = dict(m['line'], id=m['line'].get('id', f'cut{k}-limit{j}'))
            lines.append(ml); lim.append((ml, m['keep']))
        lines += [a, b]; bands.append((a, b, lim))

    def inside(p):
        return all(_side(l, p) * _side(l, k) > 0 for l, k in region)

    def in_band(p, band):
        a, b, lim = band
        return _side(a, p) * _side(b, p) < 0 and all(_side(l, p) * _side(l, k) > 0 for l, k in lim)
    x0, x1, y0, y1 = (float(v) for v in spec['clip'])
    cells = {}
    y = max(y0, 0.) + step / 2
    while y < y1:
        x = x0 + step / 2
        while x < x1:
            p = (x, y)
            if inside(p) and not any(in_band(p, band) for band in bands):
                cells.setdefault(tuple(_side(l, p) > 0 for l in lines), []).append(p)
            x += step
        y += step
    names = [l['id'] for l in lines]
    fills = list(spec.get('fills', []))
    for n, pts in enumerate(sorted(cells.values(), key=len, reverse=True)):
        if len(pts) < 3:
            continue
        cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
        seed = min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        fills.append(dict(id=f'cut-cell-{n}', seed=[round(seed[0], 5), round(seed[1], 5)], fill=spec.get('cut_fill', 'white'), using=names))
    spec['lines'], spec['fills'] = lines, fills
    if spec.get('mirror') == 'y':
        spec['halves'] = 'separate'
    for k in ('region', 'cuts'):
        spec.pop(k, None)
    return spec


def build(spec) -> list:
    if 'region' in spec:
        spec = expand_cuts(spec)
    raw = list(spec['lines'])
    seeds = list(spec['fills'])
    if spec.get('mirror') == 'y':
        raw += [mirrored(l) for l in raw if not on_axis(l)]
        seeds += [dict(f, id=f'{f["id"]}~', seed=[f['seed'][0], -f['seed'][1]]) for f in seeds if abs(f['seed'][1]) > 1e-12]
    elif spec.get('mirror') not in (None, 'none'):
        raise ValueError('mirror is "y" or absent')
    ids = [l.get('id') for l in raw]
    if len(set(i for i in ids if i)) != len([i for i in ids if i]):
        raise ValueError('line ids must be unique')
    lines = [line_of(l) for l in raw]
    clip = [float(v) for v in spec['clip']]
    separate = spec.get('halves') == 'separate'
    if separate and spec.get('mirror') != 'y':
        raise ValueError('halves "separate" needs mirror "y"')
    shared = {l.get('id') for l in spec['lines'] if on_axis(l)}
    items = []
    for f in seeds:
        use = lines
        if 'using' in f:
            # Only these lines (and their mirrors) bound the cell: an outline or a separate small shape that
            # the group's other construction lines must not cut.
            names = set(f['using']) | {n + '~' for n in f['using']}
            unknown = set(f['using']) - set(ids)
            if unknown:
                raise ValueError(f'fill {f["id"]}: unknown lines {sorted(unknown)}')
            use = [ln for ln, i in zip(lines, ids) if i in names]
        if separate:
            # each half only by its own lines (an unmirrored line through y = 0 belongs to both)
            mirrored_seed = str(f['id']).endswith('~')
            mine = {i for i in ids if str(i).endswith('~') == mirrored_seed} | shared
            pick = [ln for ln, i in zip(lines, ids) if i in mine and ('using' not in f or i in names)]
            use = pick
        outer = cell(use, f['seed'], clip)
        if not outer:
            raise ValueError(f'fill {f["id"]}: empty cell')
        item = dict(id=f['id'], type='polygon', chart=spec['chart'], points=[[round(x, 6), round(y, 6)] for x, y in outer], fill=f['fill'])
        if f.get('outline'):
            inner = cell(use, f['seed'], clip, inset=float(f['outline']))
            if inner and area(inner) > 0:
                item['holes'] = [[[round(x, 6), round(y, 6)] for x, y in inner]]
        items.append(item)
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True, help='New JSON file with the polygon items (and the design, with --design)')
    parser.add_argument('--design', help='Design JSON to append the items to (as a new layer)')
    parser.add_argument('--layer', default='arrangement', help='Layer name when appending to --design')
    args = parser.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    items = build(spec)
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f'{out} exists; write a new file')
    if args.design:
        design = json.loads(Path(args.design).read_text(encoding='utf-8'))
        design['layers'].append(dict(name=args.layer, items=items))
        result = design
    else:
        result = dict(items=items)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(dict(items=len(items), outlines=sum('holes' in i for i in items))))


if __name__ == '__main__':
    main()
