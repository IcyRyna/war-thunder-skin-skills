"""Clean panel hairlines and rivet dots for a full repaint, traced from the aircraft's original colour map.

The reference author draws the airframe's real panel layout into the colour map as crisp hairlines about
2 px wide at 8192, about 20-35 levels from the paint under them, plus faint rivet dots.  The normal stays
flat, so the lines read only as fine print, never as dark grooves.

  trace  --color ORIGINAL_C [--protect MASK] --out DIR
         Finds the thin dark panel lines and isolated rivet dots of the original colour map, thins them to
         centre lines and fits clean polylines.  Writes lines.json (normalised UV, top-left origin),
         trace-preview.png (red = kept lines, cyan = rivets over the original) and receipt.json.
  apply  --lines lines.json --color PAINTED_C --out DIR [--exclude LAYER ...] [--protect MASK]
         Draws the lines anti-aliased at the painted map's size and shifts the paint under them: lighter on
         a dark coat, darker on mid and light paint (or forced with --on-dark).  Texels covered by any
         --exclude layer (character art, type, white shapes) and protected texels are left untouched.
         Writes color.png, lines-mask.png, rivets-mask.png and receipt.json.
Dependencies: NumPy, Pillow, Numba.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np

os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'war-thunder-skins-numba'))
from numba import njit  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from artifact_io import ArtifactTransaction  # noqa: E402

Image.MAX_IMAGE_PIXELS = 8192 * 8192 * 2
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


# ----------------------------------------------------------------------------------------------- tracing
def box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 window with edge replication (integral image)."""
    p = np.pad(a, r + 1, mode='edge').astype(np.float64)
    s = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    out = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
    return (out[:a.shape[0], :a.shape[1]] / (k * k)).astype(np.float32)


@njit(cache=True)
def _label(mask):
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    parent = np.arange(h * w + 1, dtype=np.int32)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    nxt = 1
    for y in range(h):
        for x in range(w):
            if not mask[y, x]:
                continue
            best = 0
            for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy and 0 <= xx < w and lab[yy, xx] > 0:
                    r = find(lab[yy, xx])
                    if best == 0:
                        best = r
                    elif r != best:
                        a, b = min(r, best), max(r, best)
                        parent[b] = a
                        best = a
            if best == 0:
                best = nxt
                nxt += 1
            lab[y, x] = best
    for y in range(h):
        for x in range(w):
            if lab[y, x]:
                lab[y, x] = find(lab[y, x])
    return lab


@njit(cache=True)
def _thin(img):
    """Zhang-Suen thinning of a boolean image (in place copy)."""
    a = img.copy()
    h, w = a.shape
    changed = True
    while changed:
        changed = False
        for step in range(2):
            rm = []
            for y in range(1, h - 1):
                for x in range(1, w - 1):
                    if not a[y, x]:
                        continue
                    p2, p3, p4, p5 = a[y - 1, x], a[y - 1, x + 1], a[y, x + 1], a[y + 1, x + 1]
                    p6, p7, p8, p9 = a[y + 1, x], a[y + 1, x - 1], a[y, x - 1], a[y - 1, x - 1]
                    n = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if n < 2 or n > 6:
                        continue
                    seq = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
                    t = 0
                    for i in range(8):
                        if seq[i] == 0 and seq[i + 1] == 1:
                            t += 1
                    if t != 1:
                        continue
                    if step == 0 and (p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0):
                        continue
                    if step == 1 and (p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0):
                        continue
                    rm.append((y, x))
            for y, x in rm:
                a[y, x] = 0
            if rm:
                changed = True
    return a


NEIGH = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _chains(skel: np.ndarray) -> list[list[tuple[int, int]]]:
    """Split a one-pixel skeleton into pixel chains between endpoints and junctions."""
    ys, xs = np.nonzero(skel)
    pts = set(zip(ys.tolist(), xs.tolist()))

    def nbrs(p):
        y, x = p
        return [(y + dy, x + dx) for dy, dx in NEIGH if (y + dy, x + dx) in pts]
    degree = {p: len(nbrs(p)) for p in pts}
    nodes = {p for p, d in degree.items() if d != 2}
    seen_edges, chains = set(), []
    for start in sorted(nodes):
        for n in nbrs(start):
            if (start, n) in seen_edges:
                continue
            chain, prev, cur = [start], start, n
            while True:
                seen_edges.add((prev, cur))
                seen_edges.add((cur, prev))
                chain.append(cur)
                if cur in nodes:
                    break
                nxt = [q for q in nbrs(cur) if q != prev and (cur, q) not in seen_edges]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
            chains.append(chain)
    # closed loops without nodes
    rest = pts - {p for c in chains for p in c}
    while rest:
        start = rest.pop()
        chain, prev, cur = [start], None, start
        while True:
            nxt = [q for q in nbrs(cur) if q != prev and q in rest]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            rest.discard(cur)
            chain.append(cur)
        chain.append(start)
        chains.append(chain)
    return chains


def _rdp(points: np.ndarray, eps: float) -> np.ndarray:
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    d = b - a
    n = math.hypot(*d)
    if n == 0:
        dist = np.hypot(*(points - a).T)
    else:
        dist = np.abs(d[0] * (points[:, 1] - a[1]) - d[1] * (points[:, 0] - a[0])) / n
    i = int(dist.argmax())
    if dist[i] > eps:
        return np.vstack([_rdp(points[:i + 1], eps)[:-1], _rdp(points[i:], eps)])
    return np.vstack([a, b])


def _rows(dots: np.ndarray, spacing: float) -> np.ndarray:
    """Keep dots that sit in a row: at least two other dots within `spacing` px, roughly on one line."""
    if len(dots) == 0:
        return dots
    cell = {}
    for i, (x, y) in enumerate(dots):
        cell.setdefault((int(x // spacing), int(y // spacing)), []).append(i)
    keep = []
    for i, (x, y) in enumerate(dots):
        cx, cy = int(x // spacing), int(y // spacing)
        near = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in cell.get((cx + dx, cy + dy), ())
                if j != i and 1.5 <= math.hypot(*(dots[j] - dots[i])) <= spacing]
        if len(near) < 2:
            continue
        v = dots[near] - dots[i]
        v = v / np.hypot(*v.T)[:, None]
        if np.min(v @ v.T) < -0.8:          # two neighbours on opposite sides: a row passes through this dot
            keep.append(i)
    return dots[keep]


def _join(chains: list[np.ndarray], gap: float) -> list[np.ndarray]:
    """Join chain ends that nearly meet and continue in the same direction."""
    chains = [c for c in chains if len(c) >= 2]
    ends, grid = [], {}
    for i, c in enumerate(chains):
        k = min(4, len(c) - 1)
        for side, p, d in ((0, c[0], c[0] - c[k]), (1, c[-1], c[-1] - c[-1 - k])):
            n = math.hypot(*d) or 1.0
            ends.append((i, side, p, d / n))
            grid.setdefault((int(p[0] // gap), int(p[1] // gap)), []).append(len(ends) - 1)
    pairs = []
    for a, (i, si, pi, ni) in enumerate(ends):
        gx, gy = int(pi[0] // gap), int(pi[1] // gap)
        for b in (b for dx in (-1, 0, 1) for dy in (-1, 0, 1) for b in grid.get((gx + dx, gy + dy), ())):
            j, sj, pj, nj = ends[b]
            if b <= a or j == i:
                continue
            d = math.hypot(*(pj - pi))
            if d == 0 or d > gap:
                continue
            link = (pj - pi) / d
            if ni @ link > .9 and nj @ -link > .9:   # each end heads towards the other
                pairs.append((d, a, b))
    link_of = {}
    for d, a, b in sorted(pairs):
        if a not in link_of and b not in link_of:
            link_of[a], link_of[b] = b, a
    used, out = set(), []
    for start in range(len(chains)):
        if start in used:
            continue
        # walk back to one free end of this joined path, then forward collecting chains
        i, side = start, 0
        seen = {start}
        while (2 * i + side) in link_of:
            nb = link_of[2 * i + side]
            j, sj = ends[nb][0], ends[nb][1]
            if j in seen:
                break
            seen.add(j)
            i, side = j, 1 - sj
        path, cur, entry = [], i, side       # entry side of the first chain in the path
        while cur not in used:
            used.add(cur)
            c = chains[cur] if entry == 0 else chains[cur][::-1]
            path.append(c)
            exit_end = 2 * cur + (1 - entry)
            if exit_end not in link_of:
                break
            nb = link_of[exit_end]
            cur, entry = ends[nb][0], ends[nb][1]
        out.append(np.vstack(path))
    return out


def trace(args) -> dict:
    src = Image.open(args.color).convert('RGB')
    w, h = src.size
    L = np.asarray(src, np.float32) @ LUMA
    protect = np.zeros((h, w), bool)
    if args.protect:
        protect = np.asarray(Image.open(args.protect).convert('L').resize((w, h), Image.Resampling.NEAREST)) > 0
    # A hairline is darker than the paint on BOTH sides of it; the edge of a light marking is darker on one side only.
    p = np.pad(L, 2, mode='edge')
    ridge = np.zeros_like(L)
    for dy, dx in ((0, 2), (2, 0), (2, 2), (2, -2)):
        a = p[2 + dy:2 + dy + h, 2 + dx:2 + dx + w]
        b = p[2 - dy:2 - dy + h, 2 - dx:2 - dx + w]
        ridge = np.maximum(ridge, np.minimum(a, b) - L)
    dark = (ridge > args.threshold) & ~protect
    thick = box_mean(dark.astype(np.float32), 2) > args.max_fill   # filled dark areas are not hairlines
    cand = dark & ~thick
    lab = _label(cand)
    ids, counts = np.unique(lab[lab > 0], return_counts=True)
    size = np.zeros(int(lab.max()) + 1, np.int64)
    size[ids] = counts
    small = (size[lab] <= args.max_rivet) & (lab > 0)
    rivets = []
    lab_small = np.where(small, lab, 0)
    if lab_small.any():
        flat = lab_small.ravel()
        sel = flat > 0
        idx = flat[sel]
        yy, xx = np.divmod(np.nonzero(sel)[0], w)
        cnt = np.bincount(idx)
        sy, sx = np.bincount(idx, yy), np.bincount(idx, xx)
        keep = np.nonzero(cnt >= 1)[0]          # single-pixel dots count; _rows drops strays
        dots = np.array([[sx[k] / cnt[k] + .5, sy[k] / cnt[k] + .5] for k in keep])
        rivets = [[float(x / w), float(y / h)] for x, y in _rows(dots, args.rivet_spacing)]
    lines_mask = cand & ~small
    # close one-pixel breaks (faint corners, compression) before thinning
    grown = box_mean(lines_mask.astype(np.float32), 1) > 0
    closed = (box_mean(grown.astype(np.float32), 1) > .999) | lines_mask
    skel = _thin(closed.astype(np.uint8)).astype(bool)
    chains = [np.array([(x + .5, y + .5) for y, x in c], np.float64) for c in _chains(skel)]
    chains = _join(chains, args.join_gap)
    polylines = []
    for pts in chains:
        length = float(np.hypot(*np.diff(pts, axis=0).T).sum()) if len(pts) > 1 else 0.0
        if length < args.min_length:
            continue
        simple = _rdp(pts, args.tolerance)
        if length / max(len(simple) - 1, 1) < args.min_segment:   # wiggly stains, not panel edges
            continue
        polylines.append((simple / [w, h]).round(6).tolist())
    out = Path(args.out)
    preview = src.copy()
    draw = ImageDraw.Draw(preview)
    for pl in polylines:
        draw.line([(x * w, y * h) for x, y in pl], fill=(255, 0, 0), width=1)
    for x, y in rivets:
        draw.point((x * w, y * h), fill=(0, 255, 255))
    data = dict(schema_version=1, tool='panel_lines.py', source_size=[w, h], coordinates='normalised UV, origin top-left',
                lines=polylines, rivets=[[round(x, 6), round(y, 6)] for x, y in rivets])
    receipt = dict(schema_version=1, tool='panel_lines.py', mode='trace', source=str(Path(args.color).resolve()),
                   protect=str(Path(args.protect).resolve()) if args.protect else None,
                   settings=dict(threshold=args.threshold, max_fill=args.max_fill, max_rivet=args.max_rivet,
                                 min_length=args.min_length, tolerance=args.tolerance, min_segment=args.min_segment,
                                 join_gap=args.join_gap, rivet_spacing=args.rivet_spacing),
                   lines=len(polylines), rivets=len(rivets),
                   line_length_px=round(sum(float(np.hypot(*np.diff(np.array(p) * [w, h], axis=0).T).sum()) for p in polylines), 1))
    outputs = [out / 'lines.json', out / 'trace-preview.png', out / 'receipt.json']
    inputs = [Path(args.color)] + ([Path(args.protect)] if args.protect else [])
    with ArtifactTransaction(outputs, inputs=inputs, label='panel-lines-trace') as tx:
        staged = {o: tx.stage(o) for o in outputs}
        staged[outputs[0]].write_text(json.dumps(data) + '\n', encoding='utf-8')
        preview.save(staged[outputs[1]])
        staged[outputs[2]].write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        tx.commit()
    return receipt


# ----------------------------------------------------------------------------------------------- applying
def _render(data, size, width_px, rivet_px, ss=2):
    W, H = size
    lines = Image.new('L', (W * ss, H * ss), 0)
    d = ImageDraw.Draw(lines)
    lw = max(1, round(width_px * ss))
    for pl in data['lines']:
        d.line([(x * W * ss, y * H * ss) for x, y in pl], fill=255, width=lw, joint='curve')
    rivets = Image.new('L', (W * ss, H * ss), 0)
    d = ImageDraw.Draw(rivets)
    r = rivet_px * ss / 2
    for x, y in data['rivets']:
        cx, cy = x * W * ss, y * H * ss
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    return lines.resize((W, H), Image.Resampling.BOX), rivets.resize((W, H), Image.Resampling.BOX)


def apply(args) -> dict:
    data = json.loads(Path(args.lines).read_text(encoding='utf-8'))
    color = Image.open(args.color).convert('RGBA')
    W, H = color.size
    scale = W / 8192
    lines, rivets = _render(data, (W, H), args.width * scale, args.rivet_size * scale)
    la = np.asarray(lines, np.float32) / 255
    ra = np.asarray(rivets, np.float32) / 255 * args.rivet_strength
    keep = np.ones((H, W), np.float32)
    for layer in args.exclude or []:
        a = np.asarray(Image.open(layer).getchannel('A').resize((W, H), Image.Resampling.BILINEAR), np.float32) / 255
        keep *= 1 - np.clip(a * 2, 0, 1)
    if args.protect:
        keep *= np.asarray(Image.open(args.protect).convert('L').resize((W, H), Image.Resampling.NEAREST)) == 0
    c = np.asarray(color, np.float32)
    lum = c[..., :3] @ LUMA
    if args.on_dark == 'light':
        lighten = lum < args.dark_below
    elif args.on_dark == 'dark':
        lighten = np.zeros_like(lum, bool)
    else:
        raise ValueError('--on-dark must be light or dark')
    shift = np.where(lighten, args.light_shift, -args.dark_shift).astype(np.float32)
    alpha = np.maximum(la, ra) * keep
    out = c.copy()
    out[..., :3] = np.clip(c[..., :3] + shift[..., None] * alpha[..., None], 0, 255)
    result = Image.fromarray(np.rint(out).astype(np.uint8), 'RGBA')
    receipt = dict(schema_version=1, tool='panel_lines.py', mode='apply', lines=str(Path(args.lines).resolve()),
                   color=str(Path(args.color).resolve()), size=[W, H], exclude=[str(Path(p).resolve()) for p in args.exclude or []],
                   settings=dict(width_px_at_8192=args.width, rivet_px_at_8192=args.rivet_size, rivet_strength=args.rivet_strength,
                                 on_dark=args.on_dark, dark_below=args.dark_below, light_shift=args.light_shift, dark_shift=args.dark_shift),
                   drawn_share=round(float((alpha > .05).mean()), 5),
                   lightened_share_of_drawn=round(float((lighten & (alpha > .05)).sum() / max((alpha > .05).sum(), 1)), 3))
    out = Path(args.out)
    outputs = [out / 'color.png', out / 'lines-mask.png', out / 'rivets-mask.png', out / 'receipt.json']
    inputs = [Path(args.lines), Path(args.color)] + [Path(p) for p in args.exclude or []] + ([Path(args.protect)] if args.protect else [])
    with ArtifactTransaction(outputs, inputs=inputs, label='panel-lines-apply') as tx:
        staged = {o: tx.stage(o) for o in outputs}
        result.save(staged[outputs[0]])
        lines.save(staged[outputs[1]])
        rivets.save(staged[outputs[2]])
        staged[outputs[3]].write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        tx.commit()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='mode', required=True)
    t = sub.add_parser('trace', help='trace panel lines and rivets from the original colour map')
    t.add_argument('--color', required=True, help='Original colour map (TGA/PNG/DDS readable by Pillow)')
    t.add_argument('--protect', help='Mechanical mask; nonzero texels are ignored')
    t.add_argument('--threshold', type=float, default=6, help='Levels darker than the paint on both sides (default 6)')
    t.add_argument('--max-fill', type=float, default=.55, help='Dark share of a 5x5 window above which an area is a filled shape, not a line')
    t.add_argument('--max-rivet', type=int, default=6, help='Largest isolated dark blob kept as a rivet dot, in source pixels')
    t.add_argument('--min-length', type=float, default=18, help='Shortest kept line, in source pixels; shorter pieces read as breaks')
    t.add_argument('--tolerance', type=float, default=1.0, help='Polyline fit tolerance, in source pixels')
    t.add_argument('--min-segment', type=float, default=3.0, help='Mean fitted segment length; wigglier chains are stains and are dropped')
    t.add_argument('--join-gap', type=float, default=8, help='Join line ends this close (source px) that continue in the same direction')
    t.add_argument('--rivet-spacing', type=float, default=7, help='Rivets are kept only in rows with neighbours this close (source px)')
    t.add_argument('--out', required=True, help='New or empty output directory')
    a = sub.add_parser('apply', help='draw traced lines into a painted colour map')
    a.add_argument('--lines', required=True)
    a.add_argument('--color', required=True, help='Painted colour map; its size sets the drawing size')
    a.add_argument('--exclude', action='append', help='RGBA layer whose covered texels get no lines (repeatable)')
    a.add_argument('--protect', help='Mechanical mask; protected texels are left untouched')
    a.add_argument('--width', type=float, default=2.0, help='Line width in pixels at 8192 (scaled to the map size; default 2)')
    a.add_argument('--rivet-size', type=float, default=2.5, help='Rivet dot diameter in pixels at 8192 (default 2.5)')
    a.add_argument('--rivet-strength', type=float, default=.6, help='Rivet contrast relative to the lines (default 0.6)')
    a.add_argument('--on-dark', default='light', help="'light': lines lighter on dark paint (Rafale), 'dark': darker everywhere (Su-30, Mirage)")
    a.add_argument('--dark-below', type=float, default=60, help='Paint luminance below which --on-dark light lightens (default 60)')
    a.add_argument('--light-shift', type=float, default=30, help='Levels added on dark paint (default 30)')
    a.add_argument('--dark-shift', type=float, default=24, help='Levels removed on other paint (default 24)')
    a.add_argument('--out', required=True, help='New or empty output directory')
    args = parser.parse_args(argv)
    receipt = trace(args) if args.mode == 'trace' else apply(args)
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('settings',)}))


if __name__ == '__main__':
    main()
