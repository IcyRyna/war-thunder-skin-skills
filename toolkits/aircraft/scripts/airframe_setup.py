"""Set up a new airframe for UV-native design: where every atlas island is on the model, a metre frame for every
flat island, a clean one-coat base with a mechanical-part mask, and base-layout area shares on rendered views.

  map     --geometry G --scene S [--texture T] --out DIR
          node-coloured atlas with island labels; islands.json: island, dominant node, area, 3D centroid, mean
          normal, facing.  Also coords.npz (per texel model x, y, z, normal y/z, used) at --size for lookups, and
          landmarks.png: station lines every 0.5 m (white each metre), centre line (red), top/side/bottom limits
          (yellow) over the stock map.  Read the axes from the table first (which way is the nose, which side is
          left); do not assume them.
  frames  --geometry G --scene S [--texture T] --out frames.json
          one entry per UV island (triangles sharing UV vertices, the vector_paint island rule, so a slat and its
          wing or a rudder and its fin are one) of at least --min-area m2: a least-squares affine
          atlas px = origin + a * x + b * y  from the two model axes lying in the island (from its dominant normal),
          refitted after dropping outlying triangles so a curved fillet does not bend the frame of a flat wing.  The result is a vector_paint chart frame (metres in,
          straight atlas lines out) plus a seed inside the island.  residual_px tells whether the island is flat
          enough to draw on with it; developed fuselage bands come out with large residuals and need their own
          station x girth frame.
  clean   --geometry G --scene S [--texture T] --template stock.tga --out DIR [--skin-seed U V ...]
          per-island classification of the stock map: islands mostly light camouflage grey are skin and are
          repainted with --coat; the rest keep the stock pixels and go into mechanical-mask.png (white = keep).
          Thresholds come from the stock map's own statistics (--grey-light, --grey-sat), not guesses.
  shares  --views DIR
          dark / signature / tint / white shares inside the model mask of top, bottom and left renders
          (scene_preview.py render output); compare with base-layout.md.  Writes area-shares.json and seven.png.

Helper boxes with whole-atlas UVs are dropped everywhere (vector_paint.helper_triangles).  Atlas pixels have a
top-left origin, texel centres at integers, as in vector_paint.py.  Dependencies: NumPy, Pillow, SciPy, Numba.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import vector_paint
from surface_preview import load_geometry

Image.MAX_IMAGE_PIXELS = None
AXES = 'xyz'


# ---------------------------------------------------------------- shared
def skin(geometry_path, scene_path=None, texture=None):
    """Geometry and the triangles that really sample the skin colour map (helpers dropped)."""
    g = load_geometry(geometry_path, allow_repeat_uv=True)
    materials = ['*']
    if scene_path:
        from replica_check import skin_materials
        materials = skin_materials(scene_path, texture)
    keep = vector_paint.sampling_triangles({'charts': [{'materials': list(materials)}]}, g)
    return g, keep


def raster_ids(uv, tri_ids, size):
    """Per texel id of the first listed triangle group that covers it (-1 none): tri_ids maps triangle -> id."""
    owner = np.full((size, size), -1, np.int32)
    for k in np.unique(tri_ids[tri_ids >= 0]):
        m = np.zeros((size, size), np.bool_)
        vector_paint._used(uv[tri_ids == k], size, size, m)
        owner[m & (owner < 0)] = k
    return owner


def triangle_island(uv, labels, size):
    c = uv.mean(1)
    px = np.clip(np.round(c[:, 0] * (size - 1)).astype(int), 0, size - 1)
    py = np.clip(np.round((1 - c[:, 1]) * (size - 1)).astype(int), 0, size - 1)
    return labels[py, px]


def facing_name(n):
    a = int(np.argmax(np.abs(n)))
    return ['x-', 'y-', 'z-'][a] if n[a] < 0 else ['x+', 'y+', 'z+'][a]


def font(size):
    for f in ('C:/Windows/Fonts/bahnschrift.ttf', 'C:/Windows/Fonts/arial.ttf', '/System/Library/Fonts/Helvetica.ttc',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


# ---------------------------------------------------------------- map
@vector_paint.njit(cache=True)
def _coords(uv, xyz, nrm, S, out, used):
    for t in range(uv.shape[0]):
        p = np.empty((3, 2))
        for k in range(3):
            p[k, 0] = uv[t, k, 0] * (S - 1); p[k, 1] = (1 - uv[t, k, 1]) * (S - 1)
        den = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(den) < 1e-12:
            continue
        x0 = max(0, int(np.floor(min(p[0, 0], p[1, 0], p[2, 0])))); x1 = min(S - 1, int(np.ceil(max(p[0, 0], p[1, 0], p[2, 0]))))
        y0 = max(0, int(np.floor(min(p[0, 1], p[1, 1], p[2, 1])))); y1 = min(S - 1, int(np.ceil(max(p[0, 1], p[1, 1], p[2, 1]))))
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                a = ((p[1, 1] - p[2, 1]) * (xx - p[2, 0]) + (p[2, 0] - p[1, 0]) * (yy - p[2, 1])) / den
                b = ((p[2, 1] - p[0, 1]) * (xx - p[2, 0]) + (p[0, 0] - p[2, 0]) * (yy - p[2, 1])) / den
                c = 1 - a - b
                if a >= -1e-3 and b >= -1e-3 and c >= -1e-3:
                    for k in range(3):
                        out[yy, xx, k] = a * xyz[t, 0, k] + b * xyz[t, 1, k] + c * xyz[t, 2, k]
                    out[yy, xx, 3] = nrm[t, 1]
                    out[yy, xx, 4] = nrm[t, 2]
                    used[yy, xx] = True
    return 0


def cmd_map(a):
    g, keep = skin(a.geometry, a.scene, a.texture)
    uv = np.asarray(g['uvs'], np.float64); xyz = np.asarray(g['triangles'], np.float64)
    n = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]); area = np.linalg.norm(n, axis=1) / 2
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    names = [str(s) for s in g['names']]; node = np.asarray(g['node_ids'])
    S = a.size
    owner = raster_ids(uv, np.where(keep, node, -1), S)
    used = owner >= 0
    lab, count = ndimage.label(used)
    ti = np.where(keep, triangle_island(uv, lab, S), 0)
    rows = []
    objs = ndimage.find_objects(lab); K = a.atlas / S
    for i in range(1, count + 1):
        t = ti == i
        if area[t].sum() < a.min_area:
            continue
        w = area[t]; cen = (xyz[t].mean(1) * w[:, None]).sum(0) / w.sum()
        nm = (n[t] * w[:, None]).sum(0); nm = nm / (np.linalg.norm(nm) + 1e-12)
        nodes, cnt = np.unique(node[t], return_counts=True)
        sl = objs[i - 1]
        rows.append(dict(island=i, node=names[int(nodes[np.argmax(cnt)])], nodes=sorted(names[int(k)] for k in nodes),
                         area_m2=round(float(w.sum()), 3), centroid=[round(float(v), 2) for v in cen],
                         normal=[round(float(v), 2) for v in nm], facing=facing_name(nm),
                         bbox=[int(sl[1].start * K), int(sl[0].start * K), int(sl[1].stop * K), int(sl[0].stop * K)]))
    rows.sort(key=lambda r: -r['area_m2'])
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pal = np.random.default_rng(3).integers(60, 230, (len(names), 3)).astype(np.uint8)
    img = np.zeros((S, S, 3), np.uint8); img[used] = pal[owner[used]]
    im = Image.fromarray(img); d = ImageDraw.Draw(im); f = font(max(12, S // 110))
    for r in rows[:a.labels]:
        x0, y0, x1, y1 = [v / K for v in r['bbox']]
        d.rectangle([x0, y0, x1, y1], outline=(255, 255, 255))
        d.text((x0 + 3, y0 + 2), f"#{r['island']} {r['node']} {r['facing']}", fill=(255, 255, 255), font=f, stroke_width=2, stroke_fill=(0, 0, 0))
    im.save(out / 'atlas-map.png')
    # per-texel coordinates and landmarks
    C = np.zeros((S, S, 5), np.float32); U = np.zeros((S, S), np.bool_)
    _coords(uv[keep], xyz[keep], n[keep], S, C, U)
    np.savez_compressed(out / 'coords.npz', x=C[..., 0], y=C[..., 1], z=C[..., 2], ny=C[..., 3], nz=C[..., 4], used=U,
                        atlas=np.int32(a.atlas))
    if a.template:
        base = (np.asarray(Image.open(a.template).convert('RGB').resize((S, S), Image.BILINEAR), np.float32) * .45).astype(np.uint8)
    else:
        base = (img * .45).astype(np.uint8)
    ax = AXES.index(a.station_axis)

    def crossing(f, step):
        q = np.floor(f / step); e = np.zeros_like(U)
        e[:, 1:] |= (q[:, 1:] != q[:, :-1]) & U[:, 1:] & U[:, :-1]
        e[1:, :] |= (q[1:, :] != q[:-1, :]) & U[1:, :] & U[:-1, :]
        return e
    base[crossing(C[..., ax], .5)] = (90, 200, 255)
    base[crossing(C[..., ax], 1.)] = (255, 255, 255)
    base[crossing((C[..., 2] > 0).astype(np.float32), .5)] = (255, 60, 60)
    base[crossing(C[..., 3] + .5, 1.)] = (255, 220, 0)
    Image.fromarray(base).save(out / 'landmarks.png')
    (out / 'islands.json').write_text(json.dumps(dict(raster=S, atlas=a.atlas, station_axis=a.station_axis,
                                                      used_share=round(float(used.mean()), 4), helper_triangles=int((~keep & vector_paint.same_texture_triangles({'charts': [{}]}, g)).sum()),
                                                      landmarks='white: station every metre, light blue: every 0.5 m, red: z = 0 centre line, yellow: normal y = +-0.5 (top / side / bottom limits)',
                                                      islands=rows), indent=1), encoding='utf-8')
    print(json.dumps(dict(islands=len(rows), used_share=round(float(used.mean()), 4))))


# ---------------------------------------------------------------- frames
def uv_components(uv, keep):
    """Island id per triangle (-1 for dropped triangles): triangles sharing a UV vertex belong together, the same
    rule as vector_paint's chart island seeds (so a slat and its wing, or a rudder and its fin, are one island)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    idx = np.flatnonzero(keep)
    comp = np.full(len(uv), -1, np.int64)
    if not len(idx):
        return comp
    keys = np.round(uv[idx].reshape(-1, 2) * (1 << 20)).astype(np.int64)
    _, vid = np.unique(keys[:, 0] * (1 << 22) + keys[:, 1], return_inverse=True)
    vid = vid.reshape(-1, 3); nv = int(vid.max()) + 1
    rows = np.r_[vid[:, 0], vid[:, 1]]; cols = np.r_[vid[:, 1], vid[:, 2]]
    graph = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(nv, nv))
    _, lab = connected_components(graph, directed=False)
    comp[idx] = lab[vid[:, 0]]
    return comp


def affine(P, Q, plane, atlas):
    qx, qy = Q[:, 0] * (atlas - 1), (1 - Q[:, 1]) * (atlas - 1)
    A = np.c_[P[:, plane[0]], P[:, plane[1]], np.ones(len(P))]
    cu = np.linalg.lstsq(A, qx, rcond=None)[0]; cv = np.linalg.lstsq(A, qy, rcond=None)[0]
    return cu, cv, np.hypot(A @ cu - qx, A @ cv - qy)


def fit_frames(g, keep, atlas=8192, min_area=.05, flat_deg=30., rounds=4):
    """Metre frame per UV island.  The fit starts on the triangles within flat_deg of the island normal, then drops
    triangles whose residual exceeds max(4 px, 2.5 x median) and refits, so a curved fillet that shares the island
    with a flat wing no longer bends the wing's frame."""
    uv = np.asarray(g['uvs'], np.float64); xyz = np.asarray(g['triangles'], np.float64)
    n = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]); area = np.linalg.norm(n, axis=1) / 2
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    names = [str(s) for s in g['names']]; node = np.asarray(g['node_ids'])
    comp = uv_components(uv, keep)
    cen_xyz = xyz.mean(1); cen_uv = uv.mean(1)
    rows = []
    for c in np.unique(comp[comp >= 0]):
        t = comp == c
        w = area[t]
        if w.sum() < min_area:
            continue
        nm = (n[t] * w[:, None]).sum(0); nm /= np.linalg.norm(nm) + 1e-12
        a_n = int(np.argmax(np.abs(nm))); plane = [k for k in range(3) if k != a_n]
        fit = t & (n @ nm > np.cos(np.radians(flat_deg)))
        if area[fit].sum() < .3 * w.sum():
            fit = t.copy()
        At = np.c_[cen_xyz[t][:, plane[0]], cen_xyz[t][:, plane[1]], np.ones(int(t.sum()))]
        for _ in range(rounds):
            P = np.concatenate([xyz[fit].reshape(-1, 3), cen_xyz[fit]]); Q = np.concatenate([uv[fit].reshape(-1, 2), cen_uv[fit]])
            cu, cv, _ = affine(P, Q, plane, atlas)
            r = np.hypot(At @ cu - cen_uv[t][:, 0] * (atlas - 1), At @ cv - (1 - cen_uv[t][:, 1]) * (atlas - 1))
            good = np.zeros(len(uv), bool); good[np.flatnonzero(t)[r <= max(4., 2.5 * np.median(r))]] = True
            nxt = fit & good
            if area[nxt].sum() < .3 * w.sum() or nxt.sum() == fit.sum():
                break
            fit = nxt
        P = np.concatenate([xyz[fit].reshape(-1, 3), cen_xyz[fit]]); Q = np.concatenate([uv[fit].reshape(-1, 2), cen_uv[fit]])
        cu, cv, res_fit = affine(P, Q, plane, atlas)
        Pa = np.concatenate([xyz[t].reshape(-1, 3), cen_xyz[t]]); Qa = np.concatenate([uv[t].reshape(-1, 2), cen_uv[t]])
        Aa = np.c_[Pa[:, plane[0]], Pa[:, plane[1]], np.ones(len(Pa))]
        res_all = np.hypot(Aa @ cu - Qa[:, 0] * (atlas - 1), Aa @ cv - (1 - Qa[:, 1]) * (atlas - 1))
        tri = np.flatnonzero(t)[np.argmax(w)]; seed = cen_uv[tri]     # inside a triangle: vector_paint tests seeds that way
        nodes, cnt = np.unique(node[t], return_counts=True)
        side = 'l' if Pa[:, 2].mean() < -.05 else 'r' if Pa[:, 2].mean() > .05 else 'c'
        px = Qa[:, 0] * (atlas - 1); py = (1 - Qa[:, 1]) * (atlas - 1)
        rows.append(dict(name=f'{names[int(nodes[np.argmax(cnt)])]}_{facing_name(nm)}_{side}',
                         nodes=[names[int(k)] for k in nodes[np.argsort(-cnt)]], area_m2=round(float(w.sum()), 3),
                         plane=[AXES[plane[0]], AXES[plane[1]]], facing=facing_name(nm),
                         seed=[round(float(seed[0] * (atlas - 1)), 1), round(float((1 - seed[1]) * (atlas - 1)), 1)],
                         bbox=[int(px.min()), int(py.min()), int(np.ceil(px.max())), int(np.ceil(py.max()))],
                         frame=dict(origin=[round(float(cu[2]), 2), round(float(cv[2]), 2)], x=[round(float(cu[0]), 3), round(float(cv[0]), 3)],
                                    y=[round(float(cu[1]), 3), round(float(cv[1]), 3)]),
                         fitted_share=round(float(area[fit].sum() / w.sum()), 3),
                         residual_px=dict(fitted=[round(float(v), 1) for v in np.percentile(res_fit, [50, 95, 99])],
                                          island=[round(float(v), 1) for v in np.percentile(res_all, [50, 95, 99])]),
                         range={AXES[k]: [round(float(Pa[:, k].min()), 2), round(float(Pa[:, k].max()), 2)] for k in range(3)}))
    rows.sort(key=lambda r: -r['area_m2'])
    seen = {}
    for r in rows:
        seen[r['name']] = seen.get(r['name'], 0) + 1
        if seen[r['name']] > 1:
            r['name'] += str(seen[r['name']])
    return rows


def cmd_frames(a):
    g, keep = skin(a.geometry, a.scene, a.texture)
    rows = fit_frames(g, keep, a.atlas, a.min_area, a.flat_deg)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(atlas=a.atlas, note='frame: atlas px = origin + plane[0] * x + plane[1] * y (metres); '
                                   'large residual_px = not one flat development, use a station x girth frame', islands=rows), indent=1), encoding='utf-8')
    for r in rows:
        if r['area_m2'] >= a.print_area:
            print(f"{r['name']:24s} {r['area_m2']:7.2f} m2  plane {''.join(r['plane'])}  fitted {r['fitted_share']:.2f}  residual fitted {r['residual_px']['fitted']} island {r['residual_px']['island']}")


# ---------------------------------------------------------------- clean base
def classify(stock, used, grey_light=(95, 225), grey_sat=.14, share=.6, forced=()):
    """Per island: skin when at least `share` of its texels are the light camouflage grey."""
    mx, mn = stock.max(2), stock.min(2)
    light = (mx + mn) / 2; sat = (mx - mn) / np.maximum(mx, 1)
    grey = (sat < grey_sat) & (light > grey_light[0]) & (light < grey_light[1])
    lab, count = ndimage.label(used)
    idx = np.arange(1, count + 1)
    px = ndimage.sum(np.ones_like(lab), lab, idx); gs = ndimage.sum(grey, lab, idx) / np.maximum(px, 1)
    is_skin = np.zeros(count + 1, bool); is_skin[1:] = gs >= share
    for L in forced:
        if L:
            is_skin[L] = True
    return lab, is_skin, gs, px


def cmd_clean(a):
    g, keep = skin(a.geometry, a.scene, a.texture)
    W = a.work; uv = np.asarray(g['uvs'], np.float64)
    used = np.zeros((W, W), np.bool_); vector_paint._used(uv[keep], W, W, used)
    stock = np.asarray(Image.open(a.template).convert('RGB').resize((W, W), Image.BOX), np.float32)
    lab0, _ = ndimage.label(used)
    forced = [int(lab0[int(sy * W / a.atlas), int(sx * W / a.atlas)]) for sx, sy in a.skin_seed]
    lab, is_skin, gs, px = classify(stock, used, tuple(a.grey_light), a.grey_sat, a.skin_share, forced)
    mech = ndimage.binary_dilation(used & ~is_skin[lab], iterations=1)
    S = a.atlas
    mech_big = np.asarray(Image.fromarray((mech * 255).astype(np.uint8)).resize((S, S), Image.NEAREST)) > 127
    coat = tuple(int(a.coat[i:i + 2], 16) for i in (1, 3, 5))
    base = np.empty((S, S, 3), np.uint8); base[:] = coat
    big = np.asarray(Image.open(a.template).convert('RGB').resize((S, S), Image.BICUBIC))
    base[mech_big] = big[mech_big]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(base).save(out / 'clean-base.png')
    Image.fromarray((mech_big * 255).astype(np.uint8), 'L').save(out / 'mechanical-mask.png')
    Image.fromarray(base).resize((1024, 1024), Image.BOX).save(out / 'clean-base-1k.png')
    mx, mn = stock.max(2), stock.min(2)
    stats = dict(lightness_pct=[round(float(v), 1) for v in np.percentile(((mx + mn) / 2)[used], [5, 25, 50, 75, 95])],
                 saturation_pct=[round(float(v), 3) for v in np.percentile(((mx - mn) / np.maximum(mx, 1))[used], [5, 25, 50, 75, 95])])
    rep = dict(work_size=W, coat=a.coat, grey_light=a.grey_light, grey_sat=a.grey_sat, skin_share=a.skin_share, forced_skin=forced,
               stock_stats_on_used=stats, skin_islands=int(is_skin[1:].sum()), mechanical_islands=int(len(is_skin) - 1 - is_skin[1:].sum()),
               mechanical_share_of_used=round(float((used & ~is_skin[lab]).sum() / used.sum()), 4),
               islands=[dict(island=int(i), px_work=int(p), grey_share=round(float(s), 3), skin=bool(is_skin[i]))
                        for i, (p, s) in enumerate(zip(px, gs), 1) if p >= 50])
    (out / 'islands.json').write_text(json.dumps(rep, indent=1), encoding='utf-8')
    print(json.dumps({k: rep[k] for k in ('skin_islands', 'mechanical_islands', 'mechanical_share_of_used', 'stock_stats_on_used')}))


# ---------------------------------------------------------------- shares
CLASSES = 'dark sat<0.2 L<110; signature r>1.5g sat>0.45; tint r>1.25g sat 0.2-0.45 L>90; white sat<0.12 L>185'


def shares(rgb, mask):
    p = rgb[mask].astype(float); mx = p.max(1); mn = p.min(1); L = (mx + mn) / 2; sat = (mx - mn) / np.maximum(mx, 1); r, g, b = p.T
    cls = dict(dark=(sat < .2) & (L < 110), signature=(r > g * 1.5) & (sat > .45),
               tint=(r > g * 1.25) & (sat > .2) & (sat <= .45) & (L > 90), white=(sat < .12) & (L > 185))
    return {k: round(float(100 * v.sum() / max(mask.sum(), 1)), 1) for k, v in cls.items()}


def cmd_shares(a):
    d = Path(a.views); res = {}
    for v in ('top', 'bottom', 'left'):
        rgb = np.asarray(Image.open(d / f'{v}.png').convert('RGB')); m = np.asarray(Image.open(d / f'{v}-mask.png').convert('L')) > 127
        res[v] = shares(rgb, m)
    names = ['top', 'bottom', 'left', 'right', 'front', 'rear', 'iso']
    if all((d / f'{n}.png').exists() for n in names):
        W = Image.open(d / 'top.png').width; im = Image.new('RGB', (W * 4, W * 2), (238, 238, 238))
        for i, n in enumerate(names):
            im.paste(Image.open(d / f'{n}.png').convert('RGB'), ((i % 4) * W, (i // 4) * W))
        im.save(d / 'seven.png')
    (d / 'area-shares.json').write_text(json.dumps(dict(classes=CLASSES, views=res,
                                                        reference='F-2A by Akamywek: top 48 / 38 / 2.7 / 6.3, bottom 60 / 33 / 2.7 / 2.9, side 68 / 21 / 0.5 / 3.8 % (dark / signature / tint / white)'),
                                                   indent=1), encoding='utf-8')
    print(json.dumps(res))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('map', 'frames', 'clean'):
        p = sub.add_parser(name)
        p.add_argument('--geometry', required=True); p.add_argument('--scene', help='scene.json: limits to the skin colour map')
        p.add_argument('--texture', help='colour map the skin replaces (file or material name part) when the scene has several')
        p.add_argument('--atlas', type=int, default=8192); p.add_argument('--out', required=True)
    p = sub.choices['map']
    p.add_argument('--size', type=int, default=4096); p.add_argument('--min-area', type=float, default=.05)
    p.add_argument('--labels', type=int, default=60); p.add_argument('--template', help='stock colour map under the landmarks')
    p.add_argument('--station-axis', default='x', choices=list(AXES))
    p = sub.choices['frames']
    p.add_argument('--min-area', type=float, default=.05)
    p.add_argument('--flat-deg', type=float, default=30.); p.add_argument('--print-area', type=float, default=.5)
    p = sub.choices['clean']
    p.add_argument('--template', required=True); p.add_argument('--coat', default='#333334'); p.add_argument('--work', type=int, default=2048)
    p.add_argument('--grey-light', type=float, nargs=2, default=[95, 225]); p.add_argument('--grey-sat', type=float, default=.14)
    p.add_argument('--skin-share', type=float, default=.6)
    p.add_argument('--skin-seed', type=float, nargs=2, action='append', default=[], metavar=('U', 'V'),
                   help='atlas px of an island that is skin whatever its stock colour (a dark radome)')
    p = sub.add_parser('shares'); p.add_argument('--views', required=True)
    a = ap.parse_args(argv)
    dict(map=cmd_map, frames=cmd_frames, clean=cmd_clean, shares=cmd_shares)[a.cmd](a)


if __name__ == '__main__':
    main()
