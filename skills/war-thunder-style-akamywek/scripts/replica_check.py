#!/usr/bin/env python3
"""Turn measured replica plans into vector_paint designs and verify them against the reference map, one group at a
time, then the whole aircraft (原 UV 逐组复刻的设计与核对工具).

Subcommands:
  used      texels the model actually samples through the skin colour map (score only there)
  edit      edit a plan: drop elements, attach mosaic fits, set a kaleidoscope mirror axis, take the base from a fit
  plan      plan JSON(s) -> one vector_paint design on an atlas-frame chart (shapes land where the author drew them)
  check     one group: reference map minus this group -> vector_paint -> same cameras, native 1:1 pair, numbers
  assemble  every verified group over a base with all design marks removed -> final map, 1:1 tiles, views, numbers

Plans come from replica_measure.py region (or are written by hand).  IoU and colour differences are diagnostics,
never an art verdict: look at the native pairs and the rendered views.  Read references/uv-native-replica.md.
Requires NumPy, Pillow, SciPy; vector_paint.py and scene_preview.py from this folder.
"""
import argparse, hashlib, json, math, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from scipy import ndimage
except ImportError:          # pragma: no cover
    ndimage = None

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replica_measure as rm  # noqa: E402

Image.MAX_IMAGE_PIXELS = 16384 * 16384


def run(args):
    r = subprocess.run([sys.executable, '-B', *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout[-2000:] + r.stderr[-4000:])
    return r.stdout


def font(size):
    for f in ('C:/Windows/Fonts/msyh.ttc', '/System/Library/Fonts/PingFang.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def skin_materials(scene_path):
    """Every material of the scene that samples a colour map: the author painted the atlas, so marks drawn over any
    island of them (retained mechanics included) land on the model."""
    scene = json.loads(Path(scene_path).read_text(encoding='utf-8'))
    names = [m.get('name') or m.get('id') for m in scene['materials'] if m.get('color')]
    if not names:
        raise SystemExit('scene has no material with a colour map')
    return names


# ---------------------------------------------------------------- used texels
def used_mask(geometry_path, materials, size):
    import vector_paint
    from surface_preview import load_geometry
    geometry = load_geometry(geometry_path, allow_repeat_uv=True)
    tris = vector_paint.same_texture_triangles({'charts': [{'materials': list(materials)}]}, geometry)
    used = np.zeros((size[1], size[0]), np.bool_)
    vector_paint._used(np.asarray(geometry['uvs'], np.float64)[tris], size[0], size[1], used)
    return used


# ---------------------------------------------------------------- plan editing
def straighten(verts, a_pt, b_pt):
    """Drop the vertices between the two vertices nearest a_pt and b_pt (on the side lying along their chord), so they are joined by
    one straight edge.  Use it only where the reference edge is measured straight (traced points on one line within a
    pixel) and a touching hairline or mark bent the traced outline."""
    v = [list(map(float, p)) for p in verts]
    dist = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1])
    i = min(range(len(v)), key=lambda k: dist(v[k], a_pt)); j = min(range(len(v)), key=lambda k: dist(v[k], b_pt))
    n = len(v); fwd = (j - i) % n
    sides = [{(i + k) % n for k in range(1, fwd)}, {(j + k) % n for k in range(1, n - fwd)}]
    a, b = v[i], v[j]; L = max(dist(a, b), 1e-9)
    off = lambda k: abs((b[0] - a[0]) * (v[k][1] - a[1]) - (b[1] - a[1]) * (v[k][0] - a[0])) / L
    # the side to drop is the one that lies along the chord (the bump), not the rest of the shape
    drop = min(sides, key=lambda side: max((off(k) for k in side), default=0.))
    return [p for k, p in enumerate(v) if k not in drop]


def edit(plan_path, out, drop=(), mosaics=(), mirrors=(), base_from_fit=False, seed_start=200, note='', straights=()):
    src = Path(plan_path)
    plan = json.loads(src.read_text(encoding='utf-8'))
    ids = [e['id'] for e in plan['elements']]
    absent = [d for d in drop if d not in ids]       # already skipped upstream (e.g. as a mechanical part): noted
    plan['elements'] = [e for e in plan['elements'] if e['id'] not in drop]
    by_id = {e['id']: e for e in plan['elements']}
    seed = seed_start
    for el_id, fit_path in mosaics:
        if el_id not in by_id:
            raise SystemExit(f'mosaic: no element {el_id}')
        el = by_id[el_id]
        fit_path = Path(fit_path).resolve()
        fit = json.loads(fit_path.read_text(encoding='utf-8'))
        if fit.get('shapes') and 'polygon' in el:
            # the fit records the extent of the shape it was measured on: refuse a fit that belongs to another piece
            v = _polygon(el['polygon'], src.parent)[0]
            ext = [min(q[0] for q in v), min(q[1] for q in v), max(q[0] for q in v), max(q[1] for q in v)]
            if not any(all(abs(a - b) <= 25 for a, b in zip(ext, sh['extent'])) for sh in fit['shapes']):
                raise SystemExit(f'mosaic: {fit_path} was fitted on another shape than {el_id} (extents differ)')
        fill = {k: v for k, v in el['fill'].items() if k in ('color', 'ramp', 'ramp_px', 'shade_px')}
        if base_from_fit:
            # a mosaic multiplies its base: the base is the gap colour between the triangles, not the field median
            br = fit['base_ramp']; th = math.radians(br['direction_deg'])
            pts = el.get('points_px') or _polygon(el['polygon'], src.parent)[0]
            s = [u * math.cos(th) + v * math.sin(th) for u, v in pts]
            col = lambda t: '#%02x%02x%02x' % tuple(int(round(min(255, max(0, c0 + c1 * t)))) for c0, c1 in zip(br['at_origin'], br['per_px']))
            lo, hi = min(s), max(s)
            fill = {'ramp_px': {'from': [lo * math.cos(th), lo * math.sin(th)], 'to': [hi * math.cos(th), hi * math.sin(th)], 'colors': [col(lo), col(hi)]}}
        fill.update(mosaic=str(fit_path), mosaic_seed=seed); seed += 1
        el['fill'] = fill
        el.setdefault('measured', {}).update(mosaic_score=fit['lattice']['score'], mosaic_edge_ratio=fit.get('edge_ratio'))
    for el_id, *pts in straights:
        if el_id not in by_id:
            raise SystemExit(f'straighten: no element {el_id}')
        el = by_id[el_id]
        verts, holes = (el['points_px'], el.get('holes_px', [])) if 'points_px' in el else _polygon(el.pop('polygon'), src.parent)
        u0, v0, u1, v1 = map(float, pts)
        el['points_px'] = straighten(verts, (u0, v0), (u1, v1))
        if holes:
            el['holes_px'] = holes
        el.setdefault('measured', {}).setdefault('straightened', []).append([u0, v0, u1, v1])
    for el_id, *axis in mirrors:
        if el_id not in by_id or 'mosaic' not in by_id[el_id]['fill']:
            raise SystemExit(f'mirror: {el_id} has no mosaic')
        u0, v0, u1, v1 = map(float, axis)
        by_id[el_id]['fill']['mirror_px'] = {'from': [u0, v0], 'to': [u1, v1]}
    plan.setdefault('notes', []).append(f'edited from {src.name}: dropped {[d for d in drop if d not in absent]}'
                                        + (f' (not present: {absent})' if absent else '') + f'; mosaics on {[m[0] for m in mosaics]}'
                                        + ('; base = fit gap ramp' if base_from_fit else '') + (f'; {note}' if note else ''))
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1), encoding='utf-8')
    return plan


# ---------------------------------------------------------------- plan -> design
def _polygon(ref, base):
    path, _, index = ref.rpartition(':')
    p = Path(path)
    sh = json.loads((p if p.is_absolute() else base / p).read_text(encoding='utf-8'))['shapes'][int(index)]
    return sh['vertices'], sh.get('holes', [])


def _fill(spec, base, S):
    d = lambda p: [round(p[0] / S, 6), round(p[1] / S, 6)]
    out = {}
    if 'color' in spec:
        out['color'] = spec['color']
    elif 'ramp' in spec:
        r = spec['ramp']; th = math.radians(r['angle']); a, b = r['stops']
        out['gradient'] = {'from': d((a * math.cos(th), a * math.sin(th))), 'to': d((b * math.cos(th), b * math.sin(th))), 'colors': r['colors']}
    elif 'ramp_px' in spec:
        out['gradient'] = {'from': d(spec['ramp_px']['from']), 'to': d(spec['ramp_px']['to']), 'colors': spec['ramp_px']['colors']}
    else:
        raise ValueError(f'fill needs color, ramp or ramp_px: {spec}')
    if 'mosaic' in spec:
        p = Path(spec['mosaic'])
        fit = json.loads((p if p.is_absolute() else base / p).read_text(encoding='utf-8'))
        lat = fit['lattice']
        out.update(pattern='tri-mosaic', cell=round(lat['cell_px'] / S, 6), angle=lat['angle_deg'], offset=d(lat['origin']),
                   inset=round(min(fit['gap']['inset'], .3), 4), seed=int(spec.get('mosaic_seed', 1)),
                   levels=[[max(.5, min(1.5, f)), max(w, 1e-4)] for f, w in fit['levels']])
        if 'mirror_px' in spec:
            out['mirror'] = {'from': d(spec['mirror_px']['from']), 'to': d(spec['mirror_px']['to'])}
        if 'contrast_px' in spec:
            c = spec['contrast_px']; out['contrast'] = {'from': d(c['from']), 'to': d(c['to']), 'values': c['values']}
    if 'shade_px' in spec:
        c = spec['shade_px']; out['shade'] = {'from': d(c['from']), 'to': d(c['to']), 'stops': c['stops']}
    return out


def _inside_points(shape, n=40):
    from matplotlib.path import Path as MPath
    poly, holes = shape
    pts = np.asarray(poly, float)
    lo, hi = pts.min(0), pts.max(0)
    n = n if not holes else 200
    xs, ys = np.meshgrid(np.linspace(lo[0], hi[0], n), np.linspace(lo[1], hi[1], n))
    cand = np.c_[xs.ravel(), ys.ravel()]
    cand = cand[MPath(pts).contains_points(cand)]
    for h in holes:
        cand = cand[~MPath(np.asarray(h, float)).contains_points(cand)]
    return cand[np.argsort(((cand - pts.mean(0)) ** 2).sum(1))]


def _seeds(polys, geometry_path, materials, size, per_shape=30):
    """Island seeds on real triangles, spread over each shape: a shape crossing UV seams is painted on every
    island it covers (a single centre seed paints only one of them)."""
    g = np.load(geometry_path, allow_pickle=True)
    if materials and 'material_names' in g and 'material_ids' in g:
        names = [str(n) for n in g['material_names']]
        keep = np.isin(g['material_ids'], [i for i, n in enumerate(names) if n in materials])
    else:
        keep = np.ones(len(g['uvs']), bool)     # single-material geometry
    uv = g['uvs'][keep].astype(float)
    pix = np.stack([uv[..., 0] * (size[0] - 1), (1 - uv[..., 1]) * (size[1] - 1)], -1)
    p0, p1, p2 = pix[:, 0], pix[:, 1], pix[:, 2]
    den = (p1[:, 1] - p2[:, 1]) * (p0[:, 0] - p2[:, 0]) + (p2[:, 0] - p1[:, 0]) * (p0[:, 1] - p2[:, 1])
    ok = np.abs(den) > 1e-9
    p0, p1, p2, den = p0[ok], p1[ok], p2[ok], den[ok]
    lo, hi = np.minimum(np.minimum(p0, p1), p2), np.maximum(np.maximum(p0, p1), p2)

    def on(u, v):
        sel = (lo[:, 0] <= u) & (hi[:, 0] >= u) & (lo[:, 1] <= v) & (hi[:, 1] >= v)
        if not sel.any():
            return False
        q0, q1, q2, dd = p0[sel], p1[sel], p2[sel], den[sel]
        w0 = ((q1[:, 1] - q2[:, 1]) * (u - q2[:, 0]) + (q2[:, 0] - q1[:, 0]) * (v - q2[:, 1])) / dd
        w1 = ((q2[:, 1] - q0[:, 1]) * (u - q2[:, 0]) + (q0[:, 0] - q2[:, 0]) * (v - q2[:, 1])) / dd
        return bool(((w0 >= .02) & (w1 >= .02) & (w0 + w1 <= .98)).any())
    seeds = []
    for shape in polys:
        cand = _inside_points(shape)
        first = next(([round(float(u), 1), round(float(v), 1)] for u, v in cand if on(u, v)), None)
        if first is None:
            continue
        seeds.append(first)
        for u, v in cand[::max(1, len(cand) // per_shape)]:
            if on(u, v):
                s = [round(float(u), 1), round(float(v), 1)]
                if s not in seeds:
                    seeds.append(s)
    return seeds


def plan_design(plans, geometry, materials, size=(8192, 8192), S=553.8, extra_seeds=()):
    layers, polys = [], []
    for plan_path in plans:
        plan_path = Path(plan_path)
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        base = plan_path.parent
        items = []
        for el in plan['elements']:
            pts, holes = _polygon(el['polygon'], base) if 'polygon' in el else (el['points_px'], [])
            holes = [h for h in el.get('holes_px', holes) if len(h) >= 3]     # a ring collapsed to a line is no hole
            polys.append((pts, holes))
            item = dict(id=el['id'], type='polygon', chart='atlas', points=[[round(x / S, 6), round(y / S, 6)] for x, y in pts], fill=_fill(el['fill'], base, S))
            if holes:
                item['holes'] = [[[round(x / S, 6), round(y / S, 6)] for x, y in ring] for ring in holes]
            items.append(item)
        layers.append(dict(name=plan['layer'], items=items))
    seeds = _seeds(polys, geometry, materials, size) + [list(s) for s in extra_seeds]
    chart = dict(id='atlas', u='x', v='z', island=seeds,
                 frame=dict(origin=[0., 0.], x=[S, 0.], y=[0., S], note=f'atlas pixels / {S}: shapes sit where the author drew them'))
    if materials:
        chart['materials'] = list(materials)
    return dict(schema_version=1, supersample=4, bleed_px=4, palette={}, charts=[chart], layers=layers,
                provenance='measured reconstruction of a reference livery from its map (replica study, not an original design)')


# ---------------------------------------------------------------- check
def check(a):
    need = rm.need; need(ndimage, 'scipy')
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('--out must be new or empty')
    out.mkdir(parents=True, exist_ok=True)
    author = rm.load_rgb(a.author)
    u0, v0, u1, v1 = a.region
    cls = rm.classify(author, a.clear)
    keep = list(a.keep)
    for plan_path in a.keep_plan:
        keep += json.loads(Path(plan_path).read_text(encoding='utf-8')).get('skipped_boxes', [])
    box_mask = np.zeros(cls.shape, bool); box_mask[v0:v1, u0:u1] = True
    for k0, l0, k1, l1 in keep:
        box_mask[l0:l1, k0:k1] = False
    clear = ndimage.binary_dilation(cls, iterations=2) & box_mask
    base = author.copy(); base[clear] = a.coat
    Image.fromarray(base).save(out / 'base.png')
    run([HERE / 'vector_paint.py', '--geometry', a.geometry, '--design', a.design, '--base', out / 'base.png', '--out', out / 'paint'])
    ours = np.asarray(Image.open(out / 'paint/composite.png').convert('RGB'))
    ra, ro = author[v0:v1, u0:u1].astype(int), ours[v0:v1, u0:u1].astype(int)
    ca, co = rm.classify(ra, a.clear), rm.classify(ro, a.clear)
    scored = box_mask[v0:v1, u0:u1]
    invisible = 0
    if a.used:
        used = np.asarray(Image.open(a.used)) > 0
        invisible = int((ca & scored & ~used[v0:v1, u0:u1]).sum())
        scored = scored & used[v0:v1, u0:u1]
    ca, co = ca & scored, co & scored
    rep = dict(region=a.region, keep=keep, scored_on='used texels' if a.used else 'all texels', author_px_invisible=invisible,
               iou=round(float((ca & co).sum() / max((ca | co).sum(), 1)), 4), author_px=int(ca.sum()), ours_px=int(co.sum()),
               missing_px=int((ca & ~co).sum()), extra_px=int((co & ~ca).sum()), colour_diff=_colour(ra, ro, ca & co),
               note='IoU and colour differences are diagnostics; the art review is done on the native pair and the views')
    pair = Image.new('RGB', ((u1 - u0) * 2 + 24, (v1 - v0) + 40), (236, 236, 236))
    pair.paste(Image.fromarray(ra.astype(np.uint8)), (0, 40)); pair.paste(Image.fromarray(ro.astype(np.uint8)), (u1 - u0 + 24, 40))
    d = ImageDraw.Draw(pair); f = font(22)
    d.text((8, 6), f'参考原图 · 原像素 1:1 · atlas {u0},{v0}-{u1},{v1}', fill=(20, 20, 20), font=f)
    d.text((u1 - u0 + 32, 6), '本组输出 · 原像素 1:1（同 atlas 坐标）', fill=(20, 20, 20), font=f)
    pair.save(out / 'native-pair.png')
    diff = np.zeros(ca.shape + (3,), np.uint8); diff[ca & co] = 220; diff[ca & ~co] = (255, 60, 60); diff[co & ~ca] = (60, 160, 255)
    Image.fromarray(diff).save(out / 'native-diff.png')
    _views(a, out, Path(a.author), out / 'paint/composite.png', '本组输出')
    _composa(out, [Path(a.author), out / 'paint/composite.png'], (u0, v0, u1, v1))
    (out / 'report.json').write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding='utf-8')
    return rep


def _colour(ra, ro, both):
    if not both.any():
        return {}
    dc = np.abs(ra[both] - ro[both])
    rep = dict(mean_abs=[round(float(v), 2) for v in dc.mean(0)], p95_abs=[round(float(v), 1) for v in np.percentile(dc, 95, axis=0)])
    # low frequency (sigma 40 px): a mosaic with its own shade order differs texel by texel, its tone must still agree
    w = ndimage.gaussian_filter(both.astype(float), 40)
    la = np.stack([ndimage.gaussian_filter(ra[..., c] * both, 40) for c in range(3)], -1) / np.maximum(w, 1e-6)[..., None]
    lo = np.stack([ndimage.gaussian_filter(ro[..., c] * both, 40) for c in range(3)], -1) / np.maximum(w, 1e-6)[..., None]
    core = ndimage.binary_erosion(both, iterations=40)
    if core.any():
        dl = np.abs(la[core] - lo[core])
        rep.update(lowfreq_mean_abs=[round(float(v), 2) for v in dl.mean(0)], lowfreq_p95_abs=[round(float(v), 1) for v in np.percentile(dl, 95, axis=0)])
    return rep


def _views(a, out, author_path, ours_path, label):
    if not a.views:
        return
    scene = json.loads(Path(a.scene).read_text(encoding='utf-8'))
    f = font(24)
    for tag, path in (('author', author_path), ('ours', ours_path)):
        s = json.loads(json.dumps(scene))
        h = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for m in s['materials']:
            if m.get('color'):
                m['color'] = dict(path=str(Path(path).resolve()), sha256=h)
        (out / f'scene-{tag}.json').write_text(json.dumps(s, indent=1), encoding='utf-8')
        (out / 'views' / tag).mkdir(parents=True, exist_ok=True)
        for v in a.views:
            run([HERE / 'scene_preview.py', 'render', '--scene', out / f'scene-{tag}.json', '--camera', Path(a.cameras) / f'{v}.json',
                 '--mode', 'layout', '--out', out / 'views' / tag / f'{v}.png'])
    rows = []
    for v in a.views:
        A, B = Image.open(out / 'views/author' / f'{v}.png').convert('RGB'), Image.open(out / 'views/ours' / f'{v}.png').convert('RGB')
        row = Image.new('RGB', (A.width + B.width + 16, A.height + 40), (236, 236, 236))
        row.paste(A, (0, 40)); row.paste(B, (A.width + 16, 40))
        d = ImageDraw.Draw(row)
        d.text((8, 4), f'{v} · 参考', fill=(20, 20, 20), font=f); d.text((A.width + 24, 4), f'{v} · {label}', fill=(20, 20, 20), font=f)
        row.save(out / f'pair-{v}.png'); rows.append(row)
    sheet = Image.new('RGB', (max(r.width for r in rows), sum(r.height for r in rows)), (236, 236, 236))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height
    sheet.save(out / 'views.png')


def _composa(out, paths, box):
    u0, v0, u1, v1 = box
    calls = []
    for p in paths:
        calls += [dict(name='open_document', arguments=dict(path=str(Path(p).resolve()))),
                  dict(name='render', arguments=dict(x=u0, y=v0, width=u1 - u0, height=v1 - v0, maxSide=min(2048, max(u1 - u0, v1 - v0))))]
    (out / 'composa-calls.json').write_text(json.dumps(calls, indent=1), encoding='utf-8')


# ---------------------------------------------------------------- assemble
def mechanical_mask(img, coat, mechanical_rgb, context_min=.6, context_area=30000, context_min_large=.15, ring=6):
    """Design-coloured components that are original mechanical parts: white ones small and off the coat; red ones
    only in the game's flat red, off the coat (a large one only when it lies wholly over detail)."""
    red, white = rm.classify(img, 'redall'), rm.classify(img, 'white')
    coat_m = np.abs(img.astype(int) - np.array(coat)).max(-1) <= 8
    design = red | white
    keep = np.zeros(red.shape, bool)
    listed = []
    for name, m in (('red', red), ('white', white)):
        lab, n = ndimage.label(m)
        if not n:
            continue
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        for i, sl in enumerate(ndimage.find_objects(lab)):
            y0, y1 = max(0, sl[0].start - ring - 2), min(img.shape[0], sl[0].stop + ring + 2)
            x0, x1 = max(0, sl[1].start - ring - 2), min(img.shape[1], sl[1].stop + ring + 2)
            comp = lab[y0:y1, x0:x1] == i + 1
            band = ndimage.binary_dilation(comp, iterations=ring) & ~ndimage.binary_dilation(comp, iterations=2)
            ctx = float((coat_m[y0:y1, x0:x1] | design[y0:y1, x0:x1])[band].mean()) if band.any() else 1.
            if name == 'red':
                inner = ndimage.binary_erosion(comp, iterations=2)     # anti-aliased rim texels are not the part's paint
                px = img[y0:y1, x0:x1][inner if inner.sum() >= 10 else comp].astype(float)
                flat = mechanical_rgb is not None and np.abs(np.median(px, 0) - np.array(mechanical_rgb)).max() <= 6 and px.std(0).max() <= 6
                hit = flat and ctx < (context_min if sizes[i] < context_area else context_min_large)
            else:
                hit = ctx < context_min and sizes[i] < context_area
            if hit:
                keep[y0:y1, x0:x1] |= comp
                listed.append(dict(cls=name, px=int(sizes[i]), box=[x0, y0, x1, y1], context=round(ctx, 2)))
    return keep, listed


def assemble(a):
    rm.need(ndimage, 'scipy')
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('--out must be new or empty')
    out.mkdir(parents=True, exist_ok=True)
    author = rm.load_rgb(a.author)
    img = author.astype(int)
    keep, listed = mechanical_mask(img, a.coat, a.mechanical_rgb)
    if a.plan:
        # shapes the measurement kept as design win: a kept component under any plan shape is cleared, so measurement
        # and assembly never disagree (an author's darkest ramp step can equal the game red)
        cover = np.zeros(keep.shape, bool)
        for pp in a.plan:
            pp = Path(pp); plan = json.loads(pp.read_text(encoding='utf-8'))
            refs = [(el.get('points_px') or _polygon(el['polygon'], pp.parent)[0]) for el in plan['elements']]
            if refs:
                cover |= rm.polygon_mask(keep.shape, (0, 0), refs)
        lab, n = ndimage.label(keep)
        if n:
            hit = np.unique(lab[cover & keep])
            keep &= ~np.isin(lab, hit[hit > 0])
        listed = [m for m in listed if keep[m['box'][1]:m['box'][3], m['box'][0]:m['box'][2]].any()]
    design_cls = rm.classify(img, 'redall+white')
    clear = ndimage.binary_dilation(design_cls & ~keep, iterations=2) & ~keep
    icons = []
    for d in a.icon:
        fit = json.loads((Path(d) / 'fit.json').read_text(encoding='utf-8'))
        u0, v0, u1, v1 = fit['box']
        box = np.zeros_like(clear); box[v0:v1, u0:u1] = True
        clear |= box & (img[..., 0] > img[..., 1] + 8)          # the icon and its dull shadow
        icons.append((Path(d), fit))
    base = author.copy(); base[clear] = a.coat
    Image.fromarray(base).save(out / 'base.png')
    # one vector_paint run per group over the previous result: in one merged design the first matching chart would
    # claim every triangle and a later group with the same selection would get none
    current, painted = out / 'base.png', []
    for k, dpath in enumerate(a.design):
        dpath = Path(dpath)
        step = out / 'paint' / f'{k:02d}-{dpath.parent.name}-{dpath.stem}'
        step.parent.mkdir(exist_ok=True)
        run([HERE / 'vector_paint.py', '--geometry', a.geometry, '--design', dpath, '--base', current, '--out', step])
        current = step / 'composite.png'
        painted.append(dict(order=k, design=str(dpath.resolve()), sha256=hashlib.sha256(dpath.read_bytes()).hexdigest()))
    final = Image.open(current).convert('RGBA')
    for d, fit in icons:
        final.alpha_composite(Image.open(d / 'placed.png').convert('RGBA'), (fit['box'][0], fit['box'][1]))
    final = final.convert('RGB'); final.save(out / 'final-color.png')
    ours = np.asarray(final).astype(int)
    used = np.asarray(Image.open(a.used)) > 0 if a.used else np.ones(keep.shape, bool)
    rep = dict(designs=painted, icons=[str(d.resolve()) for d, _ in icons], scored_on='used texels' if a.used else 'all texels',
               base_rule='reference map minus every design-coloured component; original mechanical parts kept (listed)',
               kept_mechanical=listed, cleared_px=int(clear.sum()), classes={})
    diff = np.zeros(img.shape, np.uint8)
    for name in ('redall', 'white'):
        ca = rm.classify(img, name) & ~keep & used
        co = rm.classify(ours, name) & ~keep & used
        miss, extra = ca & ~co, co & ~ca
        regions = []
        lab, n = ndimage.label(ndimage.binary_dilation(miss, iterations=4))
        if n:
            sz = ndimage.sum(miss, lab, range(1, n + 1)); sls = ndimage.find_objects(lab)
            for i in np.argsort(sz)[::-1][:30]:
                s = sls[i]; regions.append(dict(px=int(sz[i]), box=[s[1].start, s[0].start, s[1].stop, s[0].stop]))
        rep['classes'][name] = dict(iou=round(float((ca & co).sum() / max((ca | co).sum(), 1)), 4), author_px=int(ca.sum()), ours_px=int(co.sum()),
                                    missing_px=int(miss.sum()), extra_px=int(extra.sum()), colour=_colour_flat(img, ours, ca & co), largest_missing=regions)
        diff[ca & co] = 200; diff[miss] = (255, 60, 60); diff[extra] = (60, 160, 255)
    Image.fromarray(diff).save(out / 'native-diff.png')
    (out / 'native').mkdir(exist_ok=True)
    f, t = font(26), a.tile
    A_img = Image.fromarray(author)
    for v0 in range(0, author.shape[0], t):
        for u0 in range(0, author.shape[1], t):
            box = (u0, v0, min(u0 + t, author.shape[1]), min(v0 + t, author.shape[0]))
            w, h = box[2] - box[0], box[3] - box[1]
            pair = Image.new('RGB', (w * 2 + 24, h + 44), (236, 236, 236))
            pair.paste(A_img.crop(box), (0, 44)); pair.paste(final.crop(box), (w + 24, 44))
            d = ImageDraw.Draw(pair)
            d.text((8, 6), f'参考原图 · 原像素 1:1 · atlas {box[0]},{box[1]}-{box[2]},{box[3]}', fill=(20, 20, 20), font=f)
            d.text((w + 32, 6), '整机组装输出 · 原像素 1:1', fill=(20, 20, 20), font=f)
            pair.save(out / 'native' / f'tile-u{u0:05d}-v{v0:05d}.png')
    side = min(2048, author.shape[1])
    ov = Image.new('RGB', (side * 2 + 24, side + 44), (236, 236, 236))
    ov.paste(A_img.resize((side, side), Image.LANCZOS), (0, 44)); ov.paste(final.resize((side, side), Image.LANCZOS), (side + 24, 44))
    d = ImageDraw.Draw(ov)
    d.text((8, 6), '参考原图 · 全图缩小，仅作总览；核对看 native/ 原像素瓦片', fill=(20, 20, 20), font=f)
    d.text((side + 32, 6), '整机组装输出 · 同比例', fill=(20, 20, 20), font=f)
    ov.save(out / 'overview.png')
    _views(a, out, Path(a.author), out / 'final-color.png', '整机组装输出')
    _composa(out, [Path(a.author), out / 'final-color.png'], (0, 0, author.shape[1], author.shape[0]))
    (out / 'report.json').write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding='utf-8')
    return rep


def _colour_flat(img, ours, both):
    if not both.any():
        return {}
    dc = np.abs(img[both] - ours[both])
    return dict(mean_abs=[round(float(v), 2) for v in dc.mean(0)], p95_abs=[round(float(v), 1) for v in np.percentile(dc, 95, axis=0)])


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('used'); p.add_argument('--geometry', required=True); p.add_argument('--scene', required=True)
    p.add_argument('--size', type=int, nargs=2, default=[8192, 8192]); p.add_argument('--out', required=True)
    p = sub.add_parser('edit'); p.add_argument('--plan', required=True); p.add_argument('--out', required=True)
    p.add_argument('--drop', nargs='*', default=[]); p.add_argument('--mosaic', nargs=2, action='append', default=[], metavar=('ID', 'FIT'))
    p.add_argument('--mirror', nargs=5, action='append', default=[], metavar=('ID', 'U0', 'V0', 'U1', 'V1'),
                   help='kaleidoscope axis: texels right of U0,V0 -> U1,V1 (atlas v down) repeat the other side mirrored')
    p.add_argument('--base-from-fit', action='store_true'); p.add_argument('--seed-start', type=int, default=200); p.add_argument('--note', default='')
    p.add_argument('--straighten', nargs=5, action='append', default=[], metavar=('ID', 'U0', 'V0', 'U1', 'V1'),
                   help='join the outline vertices nearest U0,V0 and U1,V1 by one straight edge (measured straight in the reference)')
    p = sub.add_parser('plan'); p.add_argument('--plan', action='append', required=True); p.add_argument('--geometry', required=True)
    p.add_argument('--scene', required=True, help='materials with a colour map become the chart materials')
    p.add_argument('--size', type=int, nargs=2, default=[8192, 8192]); p.add_argument('--px-per-unit', type=float, default=553.8)
    p.add_argument('--extra-seed', type=float, nargs=2, action='append', default=[]); p.add_argument('--out', required=True)
    for name in ('check', 'assemble'):
        p = sub.add_parser(name)
        p.add_argument('--author', required=True); p.add_argument('--geometry', required=True); p.add_argument('--scene', required=True)
        p.add_argument('--cameras', required=True); p.add_argument('--views', nargs='*', default=['top', 'bottom', 'left', 'right', 'front', 'rear', 'iso'])
        p.add_argument('--coat', type=int, nargs=3, default=[51, 51, 52]); p.add_argument('--used', help='used-texel mask from the used subcommand')
        p.add_argument('--out', required=True)
        if name == 'check':
            p.add_argument('--design', required=True); p.add_argument('--region', type=int, nargs=4, required=True)
            p.add_argument('--clear', default='redall+white'); p.add_argument('--keep', type=int, nargs=4, action='append', default=[])
            p.add_argument('--keep-plan', action='append', default=[], help='plan whose skipped_boxes stay as in the reference')
        else:
            p.add_argument('--design', action='append', required=True, help='verified group designs, painted in this order')
            p.add_argument('--icon', action='append', default=[], help='replica_measure.py icon output folders')
            p.add_argument('--mechanical-rgb', type=int, nargs=3, default=None); p.add_argument('--tile', type=int, default=2048)
            p.add_argument('--plan', action='append', default=[], help='replica plans: a component under any of their shapes is design')
    a = ap.parse_args(argv)
    if a.cmd == 'used':
        used = used_mask(a.geometry, skin_materials(a.scene), a.size)
        Image.fromarray((used * 255).astype(np.uint8), 'L').save(a.out)
        print(json.dumps(dict(used_texels=int(used.sum()), share=round(float(used.mean()), 4))))
    elif a.cmd == 'edit':
        plan = edit(a.plan, a.out, a.drop, a.mosaic, a.mirror, a.base_from_fit, a.seed_start, a.note, a.straighten)
        print(json.dumps(dict(elements=len(plan['elements']))))
    elif a.cmd == 'plan':
        design = plan_design(a.plan, a.geometry, skin_materials(a.scene), tuple(a.size), a.px_per_unit, a.extra_seed)
        out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(design, indent=1), encoding='utf-8')
        print(json.dumps(dict(layers={l['name']: len(l['items']) for l in design['layers']}, seeds=len(design['charts'][0]['island']))))
    elif a.cmd == 'check':
        print(json.dumps(check(a), ensure_ascii=True))
    elif a.cmd == 'assemble':
        rep = assemble(a)
        print(json.dumps({n: {k: v for k, v in c.items() if k != 'largest_missing'} for n, c in rep['classes'].items()}, ensure_ascii=True))


if __name__ == '__main__':
    sys.exit(main())
