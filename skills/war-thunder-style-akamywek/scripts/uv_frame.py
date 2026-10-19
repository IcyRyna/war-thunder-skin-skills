"""Fit a straight-edge design frame to one UV island and locate airframe points on it.

A painter working on the unwrapped colour map draws straight lines in the atlas.  Where an island is a
developed (unrolled) skin, atlas distance follows distance along the skin rather than the top-view
projection, so a line that is straight in world (x, z) bends in the atlas, and a line that is straight
in the atlas bends on the model.  Akamywek's F-2A is drawn the second way: its spine graphics use only
atlas-horizontal edges and two slant families.  This tool writes a "frame" for vector_paint.py so a
design can be written in metres and still come out straight in the atlas.

  --geometry geometry.npz --design design.json --chart dorsal [--region u0 v0 u1 v1]
  --origin c0=0,0 --toward c2=2,0 [--point name=a,b ...] [--samples 9] --out frame.json

Points are given in the chart's own world axes (for a top chart u = x, v = z) and are projected onto the
chart's triangles along the remaining axis, taking the face on the chart's "facing" side.  --origin
becomes design (0, 0); --toward sets design +x (normally a second point on the island centre line).
Design x is scaled so that the two points are their world u distance apart; design y is perpendicular
in the atlas and scaled by the island's skin density around the origin, so it measures distance along
the skin.

The receipt lists each point's atlas pixel and frame coordinates and checks straightness: points sampled
along the origin-toward line (and 0.25 m to each side) are located on the model and compared with the
straight frame.  Large deviations mean the island is not one development of the skin there; split the
chart or keep world axes.  Atlas pixels have a top-left origin with texel centres at integers, as in
vector_paint.py.  Dependencies: NumPy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from vector_paint import parse_axis, select_charts
from surface_preview import load_geometry


def chart_triangles(design, geometry, chart_id, size=(8192, 8192)):
    assignment, _, _, _, _ = select_charts(design, geometry, size)
    ids = [c['id'] for c in design['charts']]
    if chart_id not in ids:
        raise ValueError(f'Unknown chart {chart_id}')
    return design['charts'][ids.index(chart_id)], assignment == ids.index(chart_id)


def _axis(values, ax, s):
    return np.abs(values[..., ax]) if s == 2 else -values[..., ax] if s == 1 else values[..., ax]


def project(chart, tris, pix, a, b):
    """Atlas pixel where the chart's surface sits at chart coordinates (a, b), or None off the surface."""
    (ua, us), (va, vs) = parse_axis(chart['u']), parse_axis(chart['v'])
    view = ({0, 1, 2} - {ua, va}).pop()
    fa, fs = parse_axis(chart['facing']) if 'facing' in chart else (view, 0)
    U, V = _axis(tris, ua, us), _axis(tris, va, vs)
    d = (V[:, 1] - V[:, 2]) * (U[:, 0] - U[:, 2]) + (U[:, 2] - U[:, 1]) * (V[:, 0] - V[:, 2])
    with np.errstate(divide='ignore', invalid='ignore'):
        w0 = ((V[:, 1] - V[:, 2]) * (a - U[:, 2]) + (U[:, 2] - U[:, 1]) * (b - V[:, 2])) / d
        w1 = ((V[:, 2] - V[:, 0]) * (a - U[:, 2]) + (U[:, 0] - U[:, 2]) * (b - V[:, 2])) / d
    w2 = 1 - w0 - w1
    inside = (np.abs(d) > 1e-12) & (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
    if not inside.any():
        return None
    w = np.stack([w0, w1, w2], axis=1)
    height = _axis((w[:, :, None] * tris).sum(axis=1), fa, fs)
    k = np.flatnonzero(inside)[np.argmax(height[inside])]
    return (w[k][:, None] * pix[k]).sum(axis=0)


def parse_point(text):
    name, _, coords = text.partition('=')
    values = [float(v) for v in coords.split(',')]
    if not name or len(values) != 2:
        raise ValueError(f'Point must be name=a,b in chart coordinates: {text}')
    return name, values


def fit(args) -> dict:
    design = json.loads(Path(args.design).read_text(encoding='utf-8'))
    geometry = load_geometry(Path(args.geometry), allow_repeat_uv=True)
    chart, sel = chart_triangles(design, geometry, args.chart, (args.atlas, args.atlas))
    tris = np.asarray(geometry['triangles'], np.float64)[sel]
    uvs = np.asarray(geometry['uvs'], np.float64)[sel]
    pix = np.stack([uvs[..., 0] * (args.atlas - 1), (1 - uvs[..., 1]) * (args.atlas - 1)], axis=-1)
    if args.region:
        # The island to draw on: other parts of the chart can lie above it (a fairing, a blister) or share
        # its atlas box, so restrict to the triangles whose atlas centre lies in the island's box.
        u0, v0, u1, v1 = args.region
        c = pix.mean(axis=1)
        inside = (c[:, 0] >= u0) & (c[:, 0] <= u1) & (c[:, 1] >= v0) & (c[:, 1] <= v1)
        tris, pix = tris[inside], pix[inside]
    (oname, ov), (tname, tv) = parse_point(args.origin), parse_point(args.toward)
    o, t = project(chart, tris, pix, *ov), project(chart, tris, pix, *tv)
    if o is None or t is None:
        raise ValueError('--origin and --toward must lie on the chart surface')
    distance = float(np.hypot(tv[0] - ov[0], tv[1] - ov[1]))
    ex = (t - o) / distance
    # Skin density around the origin from areas (atlas px^2 per m^2), so design y measures skin distance.
    area_w = .5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
    e1, e2 = pix[:, 1] - pix[:, 0], pix[:, 2] - pix[:, 0]
    area_a = .5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    near = np.linalg.norm(pix.mean(axis=1) - o, axis=1) <= args.radius
    # keep only triangles whose atlas density agrees with the origin-toward scale (other islands in the box differ)
    ratio = np.sqrt(area_a / np.maximum(area_w, 1e-12)) / np.linalg.norm(ex)
    near &= (ratio > .5) & (ratio < 2)
    if near.sum() < 3:
        raise ValueError('No island triangles near the origin; check --origin')
    density = float(np.sqrt(area_a[near].sum() / area_w[near].sum()))
    across = np.array([-ex[1], ex[0]]) / np.linalg.norm(ex)
    ey = across * density ** 2 / np.linalg.norm(ex)
    side = project(chart, tris, pix, ov[0], ov[1] + .2)
    if side is not None and (side - o) @ ey < 0:
        ey = -ey
    inv = np.linalg.inv(np.c_[ex, ey])

    def frame_of(px):
        return inv @ (px - o)
    points = {oname: dict(chart=ov, atlas=o.tolist()), tname: dict(chart=tv, atlas=t.tolist())}
    for spec in args.point or []:
        name, value = parse_point(spec)
        found = project(chart, tris, pix, *value)
        points[name] = dict(chart=value, atlas=None if found is None else found.tolist())
    for record in points.values():
        if record['atlas'] is not None:
            record['frame_m'] = [round(float(v), 4) for v in frame_of(np.array(record['atlas']))]
            record['atlas'] = [round(float(v), 2) for v in record['atlas']]
    checks = []
    for k in np.linspace(-.5, 1.5, args.samples):
        a, b = ov[0] + k * (tv[0] - ov[0]), ov[1] + k * (tv[1] - ov[1])
        for off in (0.0, .25, -.25):
            found = project(chart, tris, pix, a, b + off)
            if found is None:
                continue
            fx, fy = frame_of(found)
            checks.append(dict(chart=[round(a, 3), round(b + off, 3)], frame_m=[round(float(fx), 4), round(float(fy), 4)],
                               along_error_m=round(float(fx - k * distance), 4)))
    worst = max((abs(c['along_error_m']) for c in checks), default=None)
    frame = dict(origin=[round(float(v), 3) for v in o], x=[round(float(v), 4) for v in ex], y=[round(float(v), 4) for v in ey],
                 note=f'chart {args.chart}: design x from {oname} toward {tname} (metres), design y = skin distance across')
    return dict(schema_version=1, tool='uv_frame.py', chart=args.chart, triangles=int(sel.sum()), atlas=args.atlas, frame=frame,
                px_per_m=dict(along=round(float(np.linalg.norm(ex)), 2), across=round(float(np.linalg.norm(ey)), 2), skin=round(density, 2)),
                points=points, straightness=dict(samples=checks, worst_along_error_m=worst),
                scope='Exact only where the island is one development of the skin; check worst_along_error_m and the points on the model.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--geometry', required=True)
    parser.add_argument('--design', required=True, help='Design JSON whose charts select the triangles')
    parser.add_argument('--chart', required=True)
    parser.add_argument('--origin', required=True, help='name=a,b chart coordinates that become design (0, 0)')
    parser.add_argument('--toward', required=True, help='name=a,b chart coordinates that set design +x')
    parser.add_argument('--point', action='append', help='name=a,b extra chart coordinates to locate (repeatable)')
    parser.add_argument('--region', type=float, nargs=4, metavar=('U0', 'V0', 'U1', 'V1'), help='Atlas pixel box of the island to draw on')
    parser.add_argument('--radius', type=float, default=600, help='Atlas pixels around the origin used for the skin density')
    parser.add_argument('--samples', type=int, default=9, help='Straightness samples along the origin-toward line')
    parser.add_argument('--atlas', type=int, default=8192)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    result = fit(args)
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f'{out} exists; write a new file')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('chart', 'frame', 'px_per_m')} | {'worst_along_error_m': result['straightness']['worst_along_error_m']}))


if __name__ == '__main__':
    main()
