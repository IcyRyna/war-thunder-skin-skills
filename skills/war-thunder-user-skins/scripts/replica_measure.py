#!/usr/bin/env python3
"""Measure an author's livery graphics on the unwrapped map, one group at a time (原 UV 逐组复刻的测量工具).

Subcommands (all coordinates are atlas pixels, top-left origin, texel centres at integers):
  trace   outlines of one colour class as straight-run polygons (holes kept or filled)  -> polygons.json
  ramp    the colour ramp of one shape: clamped two-stop linear gradient along a direction or the plane fit
  mosaic  a triangular mosaic: lattice (angle, cell, origin), gap, shade levels, edge evidence -> fit.json
  zoom    high-pass enlarged crop with atlas ticks, to read line directions and spacing by eye on small fields
  icon    register a bitmap (e.g. a game icon) onto an icon drawn in the map; ramp and drop shadow -> placed.png
  region  one region end to end: trace every class, ramp each shape, fit mosaics, skip original mechanical
          parts, write a replica plan (replica_check.py plan turns it into a vector_paint design)

Every number is read from the reference map: the output is a measured reconstruction (源轮廓测量重建).  Shade order
inside a mosaic is not copied (vector_paint draws it from a seed).  Read references/uv-native-replica.md first.
Requires NumPy, Pillow, SciPy and OpenCV (cv2).
"""
import argparse, json, math, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from scipy import ndimage, optimize
except ImportError:          # pragma: no cover - reported at run time
    ndimage = optimize = None

Image.MAX_IMAGE_PIXELS = 16384 * 16384
R3 = math.sqrt(3)
_IMAGES = {}


def need(module, name):
    if module is None:
        raise SystemExit(f'{name} is required: pip install {name}')


def load_rgb(path):
    key = str(Path(path).resolve())
    if key not in _IMAGES:
        _IMAGES[key] = np.asarray(Image.open(path).convert('RGB'))
    return _IMAGES[key]


# ---------------------------------------------------------------- colour classes
def classify(px, cls):
    """Named colour classes of a red / pink / white livery; '+' joins classes (red+white)."""
    px = px.astype(int)
    if '+' in cls:
        out = None
        for part in cls.split('+'):
            m = classify(px, part)
            out = m if out is None else out | m
        return out
    if cls == 'red':          # signature red with its mosaic shades, not the pink tint
        return (px[..., 0] > 95) & (px[..., 0] - px[..., 1] > 45) & ~((px[..., 1] > 72) & (px[..., 2] > 85) & (px[..., 0] < 215))
    if cls == 'redall':       # any saturated red incl. pink and light mosaic steps
        return (px[..., 0] > 95) & (px[..., 0] - px[..., 1] > 45)
    if cls == 'pink':
        return (px[..., 0] > 140) & (px[..., 1] > 72) & (px[..., 2] > 85) & (px[..., 0] - px[..., 1] > 40) & (px.min(-1) <= 200)
    if cls == 'redpink':
        return (px[..., 0] > 95) & (px[..., 0] - px[..., 1] > 40)
    if cls == 'white':
        return px.min(-1) > 200
    raise ValueError(f'unknown class {cls}: red, redall, pink, redpink, white or a + union')


def polygon_mask(shape, origin, refs):
    """Union of polygons (polygons.json:index refs or vertex lists) rasterised into a box of shape at origin."""
    pm = Image.new('L', (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(pm)
    for ref in refs:
        verts = shape_of(ref)['vertices'] if isinstance(ref, str) else ref
        d.polygon([(x - origin[0], y - origin[1]) for x, y in verts], fill=1)
    return np.asarray(pm).astype(bool)


def shape_of(ref):
    path, _, index = str(ref).rpartition(':')
    return json.loads(Path(path).read_text(encoding='utf-8'))['shapes'][int(index)]


# ---------------------------------------------------------------- trace
def _tls(points):
    c = points.mean(0)
    _, _, vt = np.linalg.svd(points - c)
    return c, vt[0]


def _intersect(c1, d1, c2, d2):
    m = np.array([d1, -d2]).T
    if abs(np.linalg.det(m)) < 1e-6:
        return None
    t = np.linalg.solve(m, c2 - c1)
    return c1 + t[0] * d1


def _push_out(p, prev_pt, next_pt, comp, dist=.5):
    """Move a vertex of an unfitted run half a texel away from the shape (along the outward bisector): the traced
    contour runs through boundary-texel centres, the 50 % edge lies half a texel further out."""
    e0, e1 = np.asarray(p) - np.asarray(prev_pt), np.asarray(next_pt) - np.asarray(p)
    n = np.zeros(2)
    for e in (e0, e1):
        ln = np.hypot(*e)
        if ln > 1e-9:
            n += np.array([e[1], -e[0]]) / ln
    ln = np.hypot(*n)
    if ln < 1e-9:
        return np.asarray(p, float)
    n /= ln
    probe = np.asarray(p) - n * 1.5
    ix, iy = int(round(probe[0])), int(round(probe[1]))
    if not (0 <= iy < comp.shape[0] and 0 <= ix < comp.shape[1] and comp[iy, ix]):
        n = -n
    return np.asarray(p, float) + n * dist


def _fit_ring(cv2, cont, comp, eps, min_edge):
    """Straight-run fit of one closed contour: runs of at least min_edge px refitted by total least squares through
    the boundary-texel centres, moved half a texel away from the shape (the 50 % crossing of a hard edge); vertices
    are intersections of consecutive runs."""
    approx = cv2.approxPolyDP(cont.astype(np.float32), eps, True)[:, 0, :].astype(float)
    idx = [int(np.argmin(((cont - p) ** 2).sum(1))) for p in approx]
    nv = len(idx)
    runs = []
    for q in range(nv):
        i0, i1 = idx[q], idx[(q + 1) % nv]
        seg = cont[i0:i1 + 1] if i1 >= i0 else np.vstack([cont[i0:], cont[:i1 + 1]])
        length = math.dist(approx[q], approx[(q + 1) % nv])
        if length >= min_edge and len(seg) >= 6:
            trim = max(1, int(len(seg) * .12))
            core = seg[trim:-trim] if len(seg) > 2 * trim + 3 else seg
            c, d = _tls(core)
            if np.dot(d, approx[(q + 1) % nv] - approx[q]) < 0:
                d = -d
            nrm = np.array([d[1], -d[0]])
            probe = core.mean(0) - nrm * 1.5
            ix, iy = int(round(probe[0])), int(round(probe[1]))
            if not (0 <= iy < comp.shape[0] and 0 <= ix < comp.shape[1] and comp[iy, ix]):
                nrm = -nrm
            runs.append(dict(c=c + nrm * .5, d=d, length=length, fitted=True,
                             rms=float(np.sqrt((((core - c) @ np.array([-d[1], d[0]])) ** 2).mean()))))
        else:
            runs.append(dict(c=approx[q], d=(approx[(q + 1) % nv] - approx[q]) / max(length, 1e-9), length=length, fitted=False, rms=None))
    verts = []
    for q in range(nv):
        r0, r1 = runs[q - 1], runs[q]
        p = None
        if r0['fitted'] and r1['fitted']:
            p = _intersect(r0['c'], r0['d'], r1['c'], r1['d'])
            if p is not None and math.dist(p, approx[q]) > 6:
                p = None
        if p is None:
            p = _push_out(approx[q], approx[q - 1], approx[(q + 1) % nv], comp)
        verts.append(p)
    return verts, runs


def trace(author, box, cls, min_area=400, eps=2.0, min_edge=18, fill_holes=False, rings=False, close=0, min_hole=30, keep_largest=0,
          coat=(51, 51, 52)):
    try:
        import cv2
    except ImportError:
        raise SystemExit('trace needs OpenCV: pip install opencv-python')
    need(ndimage, 'scipy')
    u0, v0, u1, v1 = box
    img = load_rgb(author)[v0:v1, u0:u1]
    m = classify(img, cls)
    if close:
        m = ndimage.binary_closing(m, iterations=close)      # bridges lettering cut into a field
    if fill_holes:
        # fill holes cut by marks of other colours (lettering), but a hole that is coat stays open: the author left a
        # dark slot inside the field (F-2A side strip: two rounded slots behind the type)
        # decided per texel: lettering touching the slot shares one hole with it (F-2A: the type runs over both slots)
        coat_px = np.abs(img.astype(int) - np.array(coat)).max(-1) <= 10
        hole = ndimage.binary_fill_holes(m) & ~m
        m = m | (hole & ~ndimage.binary_dilation(coat_px & hole, iterations=1))
    lab, n = ndimage.label(m)
    sizes = ndimage.sum(m, lab, range(1, n + 1)) if n else []
    order = [i + 1 for i in np.argsort(-np.asarray(sizes)) if sizes[i] >= min_area]
    if keep_largest:
        order = order[:keep_largest]
    shapes = []
    for k in order:
        comp = (lab == k).astype(np.uint8)
        cs, hier = cv2.findContours(comp, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        outer = max((i for i in range(len(cs)) if hier[0][i][3] < 0), key=lambda i: cv2.contourArea(cs[i]))
        verts, runs = _fit_ring(cv2, cs[outer][:, 0, :].astype(float), comp, eps, min_edge)
        if len(verts) < 3:
            continue
        holes = []
        if rings or fill_holes:          # with fill_holes only the coat slots are still holes here
            for i in range(len(cs)):
                if hier[0][i][3] == outer and cv2.contourArea(cs[i]) >= min_hole:
                    hv, _ = _fit_ring(cv2, cs[i][:, 0, :].astype(float), comp, eps, min_edge)
                    if len(hv) >= 3:
                        holes.append([[round(float(x) + u0, 3), round(float(y) + v0, 3)] for x, y in hv])
        verts = [(float(x) + u0, float(y) + v0) for x, y in verts]
        nv = len(verts)
        edges = [dict(deg=round(math.degrees(math.atan2(verts[(q + 1) % nv][1] - verts[q][1], verts[(q + 1) % nv][0] - verts[q][0])), 3),
                      length=round(math.dist(verts[q], verts[(q + 1) % nv]), 2), fitted=runs[q]['fitted'],
                      rms_px=None if runs[q]['rms'] is None else round(runs[q]['rms'], 3)) for q in range(nv)]
        area = .5 * abs(sum(verts[i][0] * verts[(i + 1) % nv][1] - verts[(i + 1) % nv][0] * verts[i][1] for i in range(nv)))
        shapes.append(dict(index=len(shapes), vertices=[[round(x, 3), round(y, 3)] for x, y in verts], holes=holes, edges=edges,
                           area_px=round(area, 1), mask_px=int(sizes[k - 1]), median_rgb=[int(v) for v in np.median(img[lab == k], 0)]))
    return dict(box=list(box), cls=cls, eps=eps, fill_holes=fill_holes, rings=rings, close=close, shapes=shapes,
                provenance='measured reconstruction: outlines fitted to the reference map (straight runs refitted, half-texel 50 % edge)')


def write_trace(rep, author, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    (out / 'polygons.json').write_text(json.dumps(rep, indent=1), encoding='utf-8')
    u0, v0, u1, v1 = rep['box']
    ov = Image.fromarray(load_rgb(author)[v0:v1, u0:u1].copy()); d = ImageDraw.Draw(ov)
    for s in rep['shapes']:
        d.polygon([(x - u0, y - v0) for x, y in s['vertices']], outline=(0, 255, 255))
        for h in s['holes']:
            d.polygon([(x - u0, y - v0) for x, y in h], outline=(255, 0, 255))
    ov.save(out / 'polygons.png')
    return out / 'polygons.json'


# ---------------------------------------------------------------- ramp
def ramp(author, box, cls, angle='plane', polygon=None, erode=2, min_count=8):
    """Two-stop clamped linear ramp of a shape's colour along a direction (degrees, 0 = +u, 90 = +v) or 'plane'."""
    need(ndimage, 'scipy')
    u0, v0, u1, v1 = box
    px = load_rgb(author)[v0:v1, u0:u1].astype(float)
    raw = classify(px, cls)
    m = ndimage.binary_erosion(raw, iterations=erode) if erode else raw.copy()
    if polygon is not None:
        inside = polygon_mask(raw.shape, (u0, v0), [polygon])
        m &= ndimage.binary_erosion(inside, iterations=3)
        if m.sum() < 50:
            m = raw & inside       # thin outlines: erosion leaves nothing
    if m.sum() < 3:
        raise ValueError('ramp: no texels of the class inside the shape')
    V, U = np.mgrid[v0:v1, u0:u1]
    if angle == 'plane':
        ys, xs = np.nonzero(m)
        X = np.c_[np.ones(len(xs)), U[ys, xs], V[ys, xs]]
        coef, *_ = np.linalg.lstsq(X, px[ys, xs] @ np.array([.299, .587, .114]), rcond=None)
        angle = float(np.degrees(np.arctan2(coef[2], coef[1])))
    angle = float(angle)
    th = np.radians(angle)
    proj = U * np.cos(th) + V * np.sin(th)
    bins = np.floor(proj[m]).astype(int); vals = px[m]
    order = np.argsort(bins); bins, vals = bins[order], vals[order]
    cuts = np.flatnonzero(np.diff(bins)) + 1
    us, cols = [], []
    for b, chunk in zip(np.split(bins, cuts), np.split(vals, cuts)):
        if len(chunk) >= min(min_count, max(1, int(m.sum()) // 400)):
            us.append(b[0]); cols.append(np.median(chunk, 0))
    us, cols = np.array(us, float), np.array(cols)
    best = None
    grid = np.arange(us.min(), us.max() + 1, max(4, int((us.max() - us.min()) / 150)))
    for ua in grid:
        for ub in grid[grid > ua + 8]:
            t = np.clip((us - ua) / (ub - ua), 0, 1)
            A = np.c_[1 - t, t]
            c, *_ = np.linalg.lstsq(A, cols, rcond=None)
            err = A @ c - cols
            score = float((err ** 2).sum())
            if best is None or score < best[0]:
                best = (score, ua, ub, c, err)
    if best is None:            # span under 8 px along this direction: a flat colour
        c = np.median(cols, 0)
        best = (0., us.min(), us.max(), np.vstack([c, c]), cols - c)
    _, ua, ub, coef, err = best
    hexes = ['#%02x%02x%02x' % tuple(int(round(min(255, max(0, v)))) for v in c) for c in coef]
    return dict(box=list(box), cls=cls, angle=angle, stops=[float(ua), float(ub)], colors=hexes,
                change=max(abs(int(hexes[0][i:i + 2], 16) - int(hexes[1][i:i + 2], 16)) for i in (1, 3, 5)),
                rms_error=[round(float(v), 2) for v in np.sqrt((err ** 2).mean(0))], bins=len(us))


# ---------------------------------------------------------------- mosaic
def lattice_coords(U, V, origin, cell, angle):
    """Lattice cell indices and the barycentric margin of atlas points (vector_paint tri-mosaic convention)."""
    th = math.radians(angle)
    qx, qy = U - origin[0], V - origin[1]
    ca, sa = math.cos(-th), math.sin(-th)
    px, py = (qx * ca - qy * sa) / cell, (qx * sa + qy * ca) / cell
    a, b = px - py / R3, 2 * py / R3
    i, j = np.floor(a), np.floor(b)
    fa, fb = a - i, b - j
    upper = (fa + fb) > 1
    l0 = np.where(upper, fa + fb - 1, 1 - fa - fb)
    l1 = np.where(upper, 1 - fb, fa)
    l2 = np.where(upper, 1 - fa, fb)
    return i.astype(np.int64), j.astype(np.int64), upper, np.minimum(np.minimum(l0, l1), l2)


def mosaic(author, box, cls='redall', polygons=(), erode=3, cell_range=(60, 260), init_angle=None, init_cell=None,
           fix_cell=False, levels=6, blur=1.5, edge_pct=95):
    """Fit a triangular mosaic inside a field.  On small fields fix the cell (zoom first): a finer lattice always
    lowers the in-triangle variance there.  edge_ratio (gradient on the fitted lines / inside the triangles) below
    about 2 means the lattice is not really there (a flat or smoothly ramped field, or a mirrored mosaic)."""
    need(ndimage, 'scipy')
    u0, v0, u1, v1 = box
    img = load_rgb(author)[v0:v1, u0:u1].astype(float)
    mask = classify(img, cls)
    if polygons:
        mask &= polygon_mask(mask.shape, (u0, v0), polygons)
    mask = ndimage.binary_erosion(mask, iterations=erode)
    if mask.sum() < 200:
        raise ValueError('mosaic: field too small after erosion')
    V, U = np.mgrid[v0:v1, u0:u1].astype(float)
    L = img @ np.array([.299, .587, .114])
    Lb = ndimage.gaussian_filter(L, blur)      # brushed grain must not out-vote the triangle edges
    gx, gy = ndimage.sobel(Lb, 1), ndimage.sobel(Lb, 0)
    mag = np.hypot(gx, gy)
    strong = mask & (mag > np.percentile(mag[mask], edge_pct))
    ang = np.degrees(np.arctan2(gy[strong], gx[strong])) % 60
    hist, edges = np.histogram(ang, bins=240, range=(0, 60), weights=mag[strong])
    normal0 = edges[np.argmax(ndimage.gaussian_filter1d(hist, 2, mode='wrap'))] + .125
    periods = []
    for k in range(3):
        al = math.radians(normal0 + 60 * k)
        s = U[strong] * math.cos(al) + V[strong] * math.sin(al)
        h, _ = np.histogram(s, bins=np.arange(s.min(), s.max() + .5, .5))
        f = np.abs(np.fft.rfft(h - h.mean())); freqs = np.fft.rfftfreq(len(h), d=.5)
        sel = (freqs >= 1 / (cell_range[1] * R3 / 2)) & (freqs <= 1 / (cell_range[0] * R3 / 2))
        if sel.any():
            periods.append(1 / freqs[sel][np.argmax(f[sel])])
    if not periods and not init_cell:
        raise ValueError('mosaic: field too short to measure the spacing; zoom and give init_cell')
    cell0 = float(init_cell or np.median(periods) * 2 / R3)
    angle0 = float(init_angle) if init_angle is not None else (normal0 + 90) % 60
    ys, xs = np.nonzero(mask)
    if len(ys) > 120000:
        pick = np.random.default_rng(1).choice(len(ys), 120000, replace=False)
        ys, xs = ys[pick], xs[pick]
    Us, Vs, Cs = U[ys, xs], V[ys, xs], img[ys, xs]

    def score(p, margin=.12):
        ang_, cell_, ou_, ov_ = p
        i, j, up, mm = lattice_coords(Us, Vs, (ou_, ov_), cell_, ang_)
        keep = mm > margin
        if keep.sum() < 10:
            return 1e9
        _, inv = np.unique((i[keep] * 100003 + j[keep]) * 2 + up[keep], return_inverse=True)
        tot = 0.
        for c in range(3):
            x = Cs[keep, c]
            cnt = np.bincount(inv); s1 = np.bincount(inv, x); s2 = np.bincount(inv, x * x)
            tot += float((s2 - s1 * s1 / np.maximum(cnt, 1)).sum())
        return tot / keep.sum()
    best = None
    for ou_ in np.linspace(0, cell0, 12, endpoint=False):
        for ov_ in np.linspace(0, cell0 * R3, 20, endpoint=False):
            for ang_ in (angle0, angle0 + 60, angle0 - 60):
                sc = score((ang_, cell0, u0 + ou_, v0 + ov_))
                if best is None or sc < best[0]:
                    best = (sc, (ang_, cell0, u0 + ou_, v0 + ov_))
    b = best[1]
    # explicit simplex steps: an angle of exactly 0 would otherwise get a near-zero first step and never move
    if fix_cell:
        x0 = np.array([b[0], b[2], b[3]])
        simplex = [x0, x0 + [1.5, 0, 0], x0 + [0, cell0 / 6, 0], x0 + [0, 0, cell0 / 6]]
        res = optimize.minimize(lambda q: score((q[0], cell0, q[1], q[2])), x0, method='Nelder-Mead',
                                options=dict(xatol=1e-3, fatol=1e-4, maxiter=1500, initial_simplex=simplex))
        ang_, ou_, ov_ = res.x; cell_ = cell0
    else:
        x0 = np.array(b)
        simplex = [x0, x0 + [1.5, 0, 0, 0], x0 + [0, cell0 * .03, 0, 0], x0 + [0, 0, cell0 / 6, 0], x0 + [0, 0, 0, cell0 / 6]]
        res = optimize.minimize(score, x0, method='Nelder-Mead', options=dict(xatol=1e-3, fatol=1e-4, maxiter=1500, initial_simplex=simplex))
        ang_, cell_, ou_, ov_ = res.x
        cell_ = float(min(max(cell_, cell_range[0]), cell_range[1]))
    while ang_ > 30:
        ang_ -= 60
    while ang_ <= -30:
        ang_ += 60
    Ua, Va = U[mask], V[mask]
    i, j, up, mm = lattice_coords(Ua, Va, (ou_, ov_), cell_, ang_)
    dist = mm * cell_ * R3 / 2                     # distance to the nearest lattice line, px
    _, inv = np.unique((i * 100003 + j) * 2 + up, return_inverse=True)
    Cm = img[mask]
    inner = dist > 8
    cnt = np.bincount(inv[inner], minlength=inv.max() + 1)
    tri = np.stack([np.bincount(inv[inner], Cm[inner, c], minlength=inv.max() + 1) for c in range(3)], -1) / np.maximum(cnt, 1)[:, None]
    dev = np.abs(Cm - tri[inv]).sum(1)
    gapw = 0.
    for b0 in np.arange(0, 12, .25):
        sel = (dist >= b0) & (dist < b0 + .25) & (cnt[inv] > 30)
        if sel.any() and np.median(dev[sel]) < 6:
            gapw = float(b0); break
    near = dist < 1.0
    gap_col = np.median(Cm[near], 0) if near.any() else np.median(Cm, 0)
    edge_band, interior = dist <= gapw + 2, dist >= gapw + 6
    magm = mag[mask]
    edge_ratio = float(magm[edge_band].mean() / max(magm[interior].mean(), 1e-6)) if edge_band.any() and interior.any() else 0.
    # base ramp of the gap (between-triangle) colour, then each triangle against the base at its centre
    gu, gv, gc = Ua[near], Va[near], Cm[near]
    bestr = None
    for th in np.radians(np.arange(0, 180, 3)):
        s = gu * math.cos(th) + gv * math.sin(th)
        A = np.c_[np.ones_like(s), s]
        coef, *_ = np.linalg.lstsq(A, gc, rcond=None)
        err = float(((A @ coef - gc) ** 2).sum())
        if bestr is None or err < bestr[0]:
            bestr = (err, th, coef)
    _, th, coef = bestr
    good = cnt > 30
    cu = np.bincount(inv[inner], Ua[inner], minlength=len(cnt)) / np.maximum(cnt, 1)
    cv = np.bincount(inv[inner], Va[inner], minlength=len(cnt)) / np.maximum(cnt, 1)
    base_tri = coef[0] + np.outer(cu * math.cos(th) + cv * math.sin(th), coef[1])
    lum = np.array([.299, .587, .114])
    lb, lt = base_tri @ lum, tri @ lum
    factor = np.where(lt <= lb, lt / np.maximum(lb, 1), 1 + (lt - lb) / np.maximum(255 - lb, 1))
    fs = factor[good] if good.any() else np.array([1.])
    k = min(levels, max(1, len(np.unique(np.round(fs, 3)))))
    cent = np.quantile(fs, np.linspace(.05, .95, k))
    for _ in range(50):
        lab = np.argmin(np.abs(fs[:, None] - cent[None]), 1)
        cent = np.array([fs[lab == q].mean() if (lab == q).any() else cent[q] for q in range(k)])
    weights = np.bincount(np.argmin(np.abs(fs[:, None] - cent[None]), 1), minlength=k) / len(fs)
    # which shapes the fit belongs to (by reference and extent): shape indices change when a region is traced again
    shapes = []
    for ref in polygons:
        verts = shape_of(ref)['vertices'] if isinstance(ref, str) else ref
        xs = [q[0] for q in verts]; ys = [q[1] for q in verts]
        shapes.append(dict(ref=ref if isinstance(ref, str) else None, extent=[round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]))
    return dict(box=list(box), cls=cls, shapes=shapes, triangles_scored=int(good.sum()), edge_ratio=round(edge_ratio, 2),
                lattice=dict(origin=[round(float(ou_), 3), round(float(ov_), 3)], cell_px=round(float(cell_), 3), angle_deg=round(float(ang_), 3),
                             score=round(float(res.fun), 3), cell_fixed=bool(fix_cell)),
                gap=dict(half_width_px=gapw, inset=round(gapw / (cell_ * R3 / 2), 4), colour=[round(float(x), 1) for x in gap_col]),
                base_ramp=dict(direction_deg=round(math.degrees(th), 1), at_origin=[round(float(x), 2) for x in coef[0]],
                               per_px=[round(float(x), 5) for x in coef[1]]),
                levels=[[round(float(c), 4), round(float(w), 3)] for c, w in sorted(zip(cent, weights))],
                provenance='measured: lattice geometry, gap and level distribution; the shade of each triangle is not copied')


def mosaic_overlay(author, fit, path):
    u0, v0, u1, v1 = fit['box']
    ov = Image.fromarray(load_rgb(author)[v0:v1, u0:u1].copy()); d = ImageDraw.Draw(ov)
    L = fit['lattice']; ou_, ov_ = L['origin']; cell, th = L['cell_px'], math.radians(L['angle_deg'])
    hgt, span = cell * R3 / 2, (u1 - u0) + (v1 - v0)
    for k in range(3):
        dx, dy = math.cos(th + k * math.pi / 3), math.sin(th + k * math.pi / 3)
        nx, ny = -dy, dx
        base = ((u0 + u1) / 2 - ou_) * nx + ((v0 + v1) / 2 - ov_) * ny
        for kk in range(int(base / hgt) - int(span / hgt) - 2, int(base / hgt) + int(span / hgt) + 3):
            px, py = ou_ + nx * kk * hgt, ov_ + ny * kk * hgt
            t = ((u0 + u1) / 2 - px) * dx + ((v0 + v1) / 2 - py) * dy
            d.line([(px + dx * (t - span) - u0, py + dy * (t - span) - v0), (px + dx * (t + span) - u0, py + dy * (t + span) - v0)], fill=(0, 255, 255))
    ov.save(path)


# ---------------------------------------------------------------- zoom
def zoom(author, box, scale=4, sigma=10, gain=8, tick=20, out=None):
    """High-pass crop enlarged with atlas ticks: triangle edges and their spacing become readable on small fields."""
    need(ndimage, 'scipy')
    u0, v0, u1, v1 = box
    c = load_rgb(author)[v0:v1, u0:u1].astype(float)
    L = c @ np.array([.299, .587, .114])
    e = np.clip((L - ndimage.gaussian_filter(L, sigma)) * gain + 128, 0, 255).astype(np.uint8)
    im = Image.fromarray(e).convert('RGB').resize(((u1 - u0) * scale, (v1 - v0) * scale), Image.NEAREST)
    d = ImageDraw.Draw(im)
    for u in range((u0 // tick + 1) * tick, u1, tick):
        x = (u - u0) * scale; d.line([(x, 0), (x, 8)], fill=(0, 255, 255)); d.text((x + 2, 10), str(u), fill=(0, 255, 255))
    for v in range((v0 // tick + 1) * tick, v1, tick):
        y = (v - v0) * scale; d.line([(0, y), (8, y)], fill=(0, 255, 255)); d.text((10, y - 5), str(v), fill=(0, 255, 255))
    if out:
        im.save(out)
    return im


# ---------------------------------------------------------------- icon
def _warp(icon, shape, scale, angle, cx, cy):
    h, w = icon.shape
    th = math.radians(angle); c, s = math.cos(th), math.sin(th)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(float)
    dx, dy = (xx - cx) / scale, (yy - cy) / scale
    return ndimage.map_coordinates(icon, [-s * dx + c * dy + h / 2, c * dx + s * dy + w / 2], order=1, cval=0.)


def icon(author, box, icon_path, rotate=0., min_r=120, body_rg=90, ramp_angle=0., shadow_min=.3):
    """Register an icon bitmap (alpha) onto the icon drawn in the map; measure its ramp and drop shadow.
    The silhouette stays the bitmap's (位图复用), only placement and colour are measured."""
    need(ndimage, 'scipy')
    u0, v0, u1, v1 = box
    img = load_rgb(author)[v0:v1, u0:u1].astype(float)
    red = (img[..., 0] > 95) & (img[..., 0] - img[..., 1] > 45)
    body = ndimage.binary_opening(red & (img[..., 0] > min_r) & (img[..., 0] - img[..., 1] > body_rg), iterations=1)
    lab, n = ndimage.label(body)
    if not n:
        raise ValueError('icon: no saturated red icon in the box')
    body = lab == (np.argmax(ndimage.sum(body, lab, range(1, n + 1))) + 1)
    ic = np.asarray(Image.open(icon_path).convert('RGBA').rotate(rotate, expand=True, resample=Image.BICUBIC))[..., 3].astype(float) / 255
    ys, xs = np.nonzero(ic > .5)
    ic = ic[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    by, bx = np.nonzero(body)
    p0 = [(bx.max() - bx.min() + 1) / ic.shape[1], 0., (bx.min() + bx.max()) / 2, (by.min() + by.max()) / 2]
    target = body.astype(float)

    def loss(p):
        m = _warp(ic, body.shape, *p)
        inter = (m * target).sum()
        return -inter / (m.sum() + target.sum() - inter)
    simplex = [p0, [p0[0] * 1.02] + p0[1:], [p0[0], 1.] + p0[2:], [p0[0], 0, p0[2] + 3, p0[3]], [p0[0], 0, p0[2], p0[3] + 3]]
    res = optimize.minimize(loss, p0, method='Nelder-Mead', options=dict(xatol=1e-3, fatol=1e-6, maxiter=800, initial_simplex=simplex))
    scale, angle, cx, cy = res.x
    m = _warp(ic, body.shape, scale, angle, cx, cy)
    hard = m > .5
    iou = float((hard & body).sum() / max((hard | body).sum(), 1))
    th = math.radians(ramp_angle)
    VV, UU = np.mgrid[0:body.shape[0], 0:body.shape[1]]
    proj = UU * math.cos(th) + VV * math.sin(th)
    core = ndimage.binary_erosion(body, iterations=2)
    bins = np.floor(proj[core]).astype(int); order = np.argsort(bins)
    bins, vals = bins[order], img[core][order]
    cuts = np.flatnonzero(np.diff(bins)) + 1
    us, cols = [], []
    for b, chunk in zip(np.split(bins, cuts), np.split(vals, cuts)):
        if len(chunk) >= 3:
            us.append(b[0]); cols.append(np.median(chunk, 0))
    us, cols = np.array(us, float), np.array(cols)
    best = None
    for ua in np.arange(us.min(), us.max(), 2):
        for ub in np.arange(ua + 8, us.max() + 1, 2):
            t = np.clip((us - ua) / (ub - ua), 0, 1)
            A = np.c_[1 - t, t]
            c, *_ = np.linalg.lstsq(A, cols, rcond=None)
            err = float(((A @ c - cols) ** 2).sum())
            if best is None or err < best[0]:
                best = (err, ua, ub, c)
    _, ua, ub, coef = best
    lo, hi = float(proj[hard].min()), float(proj[hard].max())
    # shadow: a dull dark red copy (R may be under the red class): texels neither coat nor icon
    coat0 = np.median(img[~ndimage.binary_dilation(red, iterations=12)], 0)
    shadow = (np.abs(img - coat0).max(-1) > 10) & ~ndimage.binary_dilation(hard, iterations=1) & (img[..., 0] > img[..., 1] + 8)
    best_off = (0., 0, 0)
    for dx in range(-16, 17):
        for dy in range(-16, 17):
            sh = np.roll(np.roll(hard, dy, 0), dx, 1) & ~hard
            if sh.any():
                sc = (sh & shadow).sum() / max((sh | shadow).sum(), 1)
                if sc > best_off[0]:
                    best_off = (sc, dx, dy)
    sscore, sdx, sdy = best_off
    sh_mask = np.roll(np.roll(hard, sdy, 0), sdx, 1) & ~hard & shadow
    sh_col = np.median(img[sh_mask], 0) if sh_mask.any() else coat0
    has_shadow = sscore >= shadow_min
    t = np.clip((proj - ua) / (ub - ua), 0, 1)[..., None]
    col = (1 - t) * coef[0] + t * coef[1]
    sm = np.roll(np.roll(m, sdy, 0), sdx, 1) if has_shadow else np.zeros_like(m)
    rgb = col * m[..., None] + sh_col * (1 - m[..., None])
    alpha = m + sm * (1 - m)
    placed = Image.fromarray(np.clip(np.round(np.dstack([rgb, alpha[..., None] * 255])), 0, 255).astype(np.uint8), 'RGBA')
    rep = dict(box=list(box), icon=Path(icon_path).name, rotate=rotate, scale=round(float(scale), 5), angle_deg=round(float(angle), 3),
               centre_atlas=[round(float(cx) + u0, 2), round(float(cy) + v0, 2)], iou=round(iou, 4),
               ramp=dict(angle=ramp_angle, colors=['#%02x%02x%02x' % tuple(int(round(v)) for v in c) for c in coef],
                         stops_fraction_of_length=[round((ua - lo) / (hi - lo), 3), round((ub - lo) / (hi - lo), 3)]),
               shadow=dict(used=bool(has_shadow), offset_px=[sdx, sdy], overlap=round(float(sscore), 3),
                           colour='#%02x%02x%02x' % tuple(int(round(v)) for v in sh_col)),
               category='位图复用: the bitmap silhouette; placement, ramp and shadow measured from the reference map')
    return rep, placed, (body, hard)


# ---------------------------------------------------------------- region
def ring_context(img, verts, coat, tol, ring=4):
    """Share of the ring just outside a shape that is coat or a design colour: painted marks sit on the coat."""
    xs = [p[0] for p in verts]; ys = [p[1] for p in verts]
    u0, v0 = max(0, int(min(xs)) - ring - 3), max(0, int(min(ys)) - ring - 3)
    u1, v1 = min(img.shape[1], int(max(xs)) + ring + 4), min(img.shape[0], int(max(ys)) + ring + 4)
    inside = polygon_mask((v1 - v0, u1 - u0), (u0, v0), [verts])
    band = ndimage.binary_dilation(inside, iterations=ring + 2) & ~ndimage.binary_dilation(inside, iterations=2)
    px = img[v0:v1, u0:u1].astype(int)[band]
    if not len(px):
        return 1.
    return float(((np.abs(px - np.array(coat)).max(-1) <= tol) | classify(px[None], 'redall+white')[0]).mean())


def flat_colour(img, verts, rgb, tol=6, max_std=6.):
    """True when a shape is one flat colour near rgb (the game's own mechanical paint)."""
    xs = [p[0] for p in verts]; ys = [p[1] for p in verts]
    u0, v0 = max(0, int(min(xs))), max(0, int(min(ys)))
    u1, v1 = min(img.shape[1], int(max(xs)) + 1), min(img.shape[0], int(max(ys)) + 1)
    inside = ndimage.binary_erosion(polygon_mask((v1 - v0, u1 - u0), (u0, v0), [verts]), iterations=2)
    px = img[v0:v1, u0:u1].astype(float)[inside]
    return len(px) >= 10 and bool(np.abs(np.median(px, 0) - np.array(rgb)).max() <= tol and px.std(0).max() <= max_std)


def mechanical(img, sh, cls, a):
    """Original mechanical part (kept from the base, not rebuilt)?  White: a small shape off the coat (light metal).
    Red / pink: only the game's flat red off the coat; a large field of it only when it lies wholly over detail,
    because the darkest step of an author ramp can equal the game red."""
    if cls == 'white':
        if sh['mask_px'] >= a.context_area:
            return None
        ctx = ring_context(img, sh['vertices'], a.coat, a.coat_tol)
        return ctx if ctx < a.context_min else None
    if not a.mechanical_rgb or not flat_colour(img, sh['vertices'], a.mechanical_rgb):
        return None
    ctx = ring_context(img, sh['vertices'], a.coat, a.coat_tol)
    limit = a.context_min if sh['mask_px'] < a.context_area else a.context_min_large
    return ctx if ctx < limit else None


def region(a):
    img = load_rgb(a.author)
    wb = Path(a.out)
    root = wb / a.name
    root.mkdir(parents=True, exist_ok=True)
    elements, notes, skipped = [], [], []
    seed = a.seed_start
    for cls in a.classes:
        rep = trace(a.author, a.box, cls, min_area=a.min_area, eps=a.eps, fill_holes=cls not in a.rings, rings=cls in a.rings, close=a.close)
        ppath = write_trace(rep, a.author, root / f'poly-{cls}')
        for sh in rep['shapes']:
            xs = [p[0] for p in sh['vertices']]; ys = [p[1] for p in sh['vertices']]
            box = [int(min(xs)) - 3, int(min(ys)) - 3, int(max(xs)) + 4, int(max(ys)) + 4]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            if getattr(a, 'include', None) and not any(e[0] <= cx <= e[2] and e[1] <= cy <= e[3] for e in a.include):
                continue
            if any(e[0] <= cx <= e[2] and e[1] <= cy <= e[3] for e in a.exclude):
                notes.append(f'{cls} shape {sh["index"]} skipped (exclude box)'); skipped.append(box)
                continue
            ctx = mechanical(img, sh, cls, a)
            if ctx is not None:
                notes.append(f'{cls} shape {sh["index"]} skipped (mechanical: {ctx:.2f} of its outside ring is coat)'); skipped.append(box)
                continue
            ref = f'{ppath.resolve()}:{sh["index"]}'
            bb = [max(0, box[0] + 1), max(0, box[1] + 1), box[2], box[3]]
            if sh['mask_px'] >= a.ramp_area:
                g = ramp(a.author, bb, cls, 'plane', ref)
            else:
                g = dict(colors=['#%02x%02x%02x' % tuple(sh['median_rgb'])] * 2, change=0, rms_error=None)
            if g['change'] < a.solid_below:
                fill = {'color': '#%02x%02x%02x' % tuple(sh['median_rgb'])}
            else:
                fill = {'ramp': {'angle': round(g['angle'], 3), 'stops': g['stops'], 'colors': g['colors']}}
            el = dict(id=f'{a.name}-{cls}-{sh["index"]}', polygon=ref, fill=fill,
                      measured=dict(area_px=sh['area_px'], ramp_rms=g['rms_error'], ramp_change=g['change']))
            if cls != 'white' and sh['mask_px'] >= a.mosaic_area:
                try:
                    fit = mosaic(a.author, bb, 'redall', [ref], erode=5, cell_range=(80, 300))
                    mdir = root / f'mosaic-{cls}-{sh["index"]}'; mdir.mkdir(exist_ok=True)
                    (mdir / 'fit.json').write_text(json.dumps(fit, indent=1), encoding='utf-8')
                    el['measured'].update(mosaic_score=fit['lattice']['score'], mosaic_edge_ratio=fit['edge_ratio'])
                    lev = sum(abs(k - 1) * w for k, w in fit['levels']) / max(sum(w for _, w in fit['levels']), 1e-9)
                    el['measured']['mosaic_level_dev'] = round(lev, 4)
                    # step edges on the lines AND shade steps worth seeing: on a flat field the edge ratio is noise over noise
                    if fit['lattice']['score'] < a.mosaic_score and fit['edge_ratio'] >= a.edge_ratio and lev >= getattr(a, 'level_dev', .01):
                        fill['mosaic'] = str((mdir / 'fit.json').resolve()); fill['mosaic_seed'] = seed; seed += 1
                    else:
                        notes.append(f'{el["id"]}: mosaic not used (score {fit["lattice"]["score"]}, edge ratio {fit["edge_ratio"]}, level dev {lev:.4f}; '
                                     'flat field, or a mirrored / per-piece / half-cell mosaic that needs a manual fit)')
                except ValueError as e:
                    notes.append(f'{el["id"]}: mosaic fit failed: {e}')
            elements.append(el)
    (wb / 'plans').mkdir(parents=True, exist_ok=True)
    plan = dict(layer=a.name, note=f'auto-measured region {a.box}, classes {a.classes}', notes=notes, elements=elements, skipped_boxes=skipped)
    path = wb / 'plans' / f'{a.name}.json'
    path.write_text(json.dumps(plan, indent=1), encoding='utf-8')
    return path, plan


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--author', required=True, help='reference colour map (the author\'s unwrapped texture)')
    common.add_argument('--box', type=int, nargs=4, required=True, metavar=('U0', 'V0', 'U1', 'V1'))
    p = sub.add_parser('trace', parents=[common]); p.add_argument('--cls', required=True)
    p.add_argument('--min-area', type=int, default=400); p.add_argument('--eps', type=float, default=2.)
    p.add_argument('--min-edge', type=float, default=18); p.add_argument('--fill-holes', action='store_true')
    p.add_argument('--rings', action='store_true'); p.add_argument('--close', type=int, default=0)
    p.add_argument('--keep-largest', type=int, default=0); p.add_argument('--out', required=True)
    p = sub.add_parser('ramp', parents=[common]); p.add_argument('--cls', default='red'); p.add_argument('--angle', default='plane')
    p.add_argument('--polygon'); p.add_argument('--erode', type=int, default=2)
    p = sub.add_parser('mosaic', parents=[common]); p.add_argument('--cls', default='redall')
    p.add_argument('--polygon', action='append', default=[]); p.add_argument('--erode', type=int, default=3)
    p.add_argument('--cell-range', type=float, nargs=2, default=[60, 260]); p.add_argument('--init-angle', type=float)
    p.add_argument('--init-cell', type=float); p.add_argument('--fix-cell', action='store_true'); p.add_argument('--out', required=True)
    p = sub.add_parser('zoom', parents=[common]); p.add_argument('--scale', type=int, default=4); p.add_argument('--out', required=True)
    p = sub.add_parser('icon', parents=[common]); p.add_argument('--icon', required=True); p.add_argument('--rotate', type=float, default=0)
    p.add_argument('--ramp-angle', type=float, default=0); p.add_argument('--out', required=True)
    p = sub.add_parser('region', parents=[common]); p.add_argument('--name', required=True)
    p.add_argument('--classes', nargs='+', default=['red', 'pink', 'white']); p.add_argument('--rings', nargs='*', default=['white'])
    p.add_argument('--min-area', type=int, default=40); p.add_argument('--eps', type=float, default=.8); p.add_argument('--close', type=int, default=0)
    p.add_argument('--exclude', type=float, nargs=4, action='append', default=[])
    p.add_argument('--include', type=float, nargs=4, action='append', default=[],
                   help='only shapes whose centre lies in one of these boxes (e.g. lettering between finished fields)')
    p.add_argument('--ramp-area', type=int, default=1200); p.add_argument('--solid-below', type=float, default=6)
    p.add_argument('--mosaic-area', type=int, default=60000); p.add_argument('--mosaic-score', type=float, default=6)
    p.add_argument('--edge-ratio', type=float, default=2.); p.add_argument('--level-dev', type=float, default=.01)
    p.add_argument('--coat', type=int, nargs=3, default=[51, 51, 52])
    p.add_argument('--coat-tol', type=int, default=8); p.add_argument('--context-min', type=float, default=.6)
    p.add_argument('--context-min-large', type=float, default=.15); p.add_argument('--context-area', type=int, default=30000)
    p.add_argument('--mechanical-rgb', type=int, nargs=3, default=None,
                   help='flat colour of the original red mechanical parts (measure it first); without it no red shape is skipped')
    p.add_argument('--seed-start', type=int, default=100); p.add_argument('--out', required=True, help='work directory (plans/ is written in it)')
    a = ap.parse_args(argv)
    if a.cmd == 'trace':
        rep = trace(a.author, a.box, a.cls, a.min_area, a.eps, a.min_edge, a.fill_holes, a.rings, a.close, keep_largest=a.keep_largest)
        write_trace(rep, a.author, a.out)
        print(json.dumps([dict(index=s['index'], n=len(s['vertices']), mask=s['mask_px'], rgb=s['median_rgb']) for s in rep['shapes']]))
    elif a.cmd == 'ramp':
        print(json.dumps(ramp(a.author, a.box, a.cls, a.angle, a.polygon, a.erode), indent=1))
    elif a.cmd == 'mosaic':
        fit = mosaic(a.author, a.box, a.cls, a.polygon, a.erode, a.cell_range, a.init_angle, a.init_cell, a.fix_cell)
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        (out / 'fit.json').write_text(json.dumps(fit, indent=1), encoding='utf-8')
        mosaic_overlay(a.author, fit, out / 'overlay.png')
        print(json.dumps({k: fit[k] for k in ('lattice', 'edge_ratio', 'gap', 'levels')}))
    elif a.cmd == 'zoom':
        zoom(a.author, a.box, a.scale, out=a.out)
    elif a.cmd == 'icon':
        rep, placed, (body, hard) = icon(a.author, a.box, a.icon, a.rotate, ramp_angle=a.ramp_angle)
        out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
        placed.save(out / 'placed.png')
        ov = np.zeros(body.shape + (3,), np.uint8); ov[body & hard] = 200; ov[body & ~hard] = (0, 220, 0); ov[hard & ~body] = (230, 0, 230)
        Image.fromarray(ov).save(out / 'overlay.png')
        (out / 'fit.json').write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(rep, ensure_ascii=True))
    elif a.cmd == 'region':
        path, plan = region(a)
        print(json.dumps(dict(plan=str(path), elements=len(plan['elements']), mosaic=sum('mosaic' in e['fill'] for e in plan['elements']),
                              notes=plan['notes']), ensure_ascii=True))


if __name__ == '__main__':
    sys.exit(main())
