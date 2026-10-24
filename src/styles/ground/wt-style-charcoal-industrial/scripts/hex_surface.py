"""Paint a regular, unbounded flat-top hex field in explicit surface coordinates."""
from pathlib import Path
import argparse
import json
import math
import numpy as np
from PIL import Image


def paint_field(image, u, v, paint, protected, shared, *, radius, gap, base, palette):
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 4:
        raise ValueError('input must be uint8 RGBA')
    shape = image.shape[:2]
    arrays = [np.asarray(x) for x in (u, v, paint, protected, shared)]
    if any(x.shape != shape for x in arrays):
        raise ValueError('all maps must match image height/width')
    u, v, paint, protected, shared = arrays
    for mask in (paint, protected, shared):
        if not np.all(np.isin(mask, [0, 1, 255])):
            raise ValueError('masks must be binary (bool, 0/1 or 0/255)')
    paint, protected, shared = [x.astype(bool) for x in (paint, protected, shared)]
    if not paint.any():
        raise ValueError('empty paint mask')
    if np.any(paint & (protected | shared)):
        raise ValueError('resolve protected/shared intersections before painting')
    if not np.isfinite(radius) or radius <= 0 or not np.isfinite(gap) or not 0 <= gap < math.sqrt(3)*radius:
        raise ValueError('radius must be positive; gap must fit the cell')
    colors = np.asarray(palette)
    if colors.ndim != 2 or colors.shape[1] != 3 or colors.shape[0] == 0:
        raise ValueError('palette must contain RGB triplets')
    values = np.concatenate((np.asarray(base).reshape(-1), colors.reshape(-1)))
    if np.asarray(base).shape != (3,) or not np.isfinite(values).all() or np.any((values < 0) | (values > 255)) or np.any(values != np.floor(values)):
        raise ValueError('base/palette must be integer RGB in 0..255')
    x, y = np.asarray(u[paint], dtype=np.float64), np.asarray(v[paint], dtype=np.float64)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('selected surface coordinates must be finite')
    # Adjacent columns of flat-top hexagons are staggered by half a row.
    c0 = np.rint(x/(1.5*radius))
    if np.max(np.abs(c0)) > 1e9 or np.max(np.abs(y/(math.sqrt(3)*radius))) > 1e9:
        raise ValueError('coordinate/radius scale exceeds supported grid range')
    c0 = c0.astype(np.int64)
    best = np.full(x.shape, np.inf)
    bx, by = np.zeros_like(x), np.zeros_like(y)
    bc, br = np.zeros_like(c0), np.zeros_like(c0)
    for shift in (-1, 0, 1):
        col = c0 + shift
        row = np.rint(y/(math.sqrt(3)*radius) - .5*(col % 2)).astype(np.int64)
        dx = x-col*(1.5*radius)
        dy = y-(row+.5*(col % 2))*(math.sqrt(3)*radius)
        d = dx*dx+dy*dy
        take = d < best
        best[take], bx[take], by[take], bc[take], br[take] = d[take], dx[take], dy[take], col[take], row[take]
    inward = np.minimum(math.sqrt(3)*radius/2-abs(by),
                        math.sqrt(3)*radius/2-math.sqrt(3)*abs(bx)/2-abs(by)/2)
    ids = ((bc*73856093) ^ (br*19349663)) % len(colors)
    rgb = np.tile(np.asarray(base, dtype=np.uint8), (len(x), 1))
    inside = inward >= gap/2
    rgb[inside] = colors.astype(np.uint8)[ids[inside]]
    result = image.copy()
    result[paint, :3] = rgb
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('input', 'maps', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--radius', type=float, required=True)
    p.add_argument('--gap', type=float, required=True)
    p.add_argument('--base', type=int, required=True, help='neutral RGB base 0..255')
    p.add_argument('--palette', required=True, help='comma separated neutral gray levels')
    a = p.parse_args()
    if a.out.exists():
        p.error('output exists; use a new path')
    with Image.open(a.input) as im:
        image = np.array(im.convert('RGBA'))
    with np.load(a.maps, allow_pickle=False) as maps:
        result = paint_field(image, *(maps[k] for k in ('u','v','paint','protected','shared')),
                             radius=a.radius, gap=a.gap, base=[a.base]*3,
                             palette=[[int(v)]*3 for v in a.palette.split(',')])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('xb') as f:
        Image.fromarray(result).save(f, format='PNG')
    print(json.dumps({'output':str(a.out),'alpha_preserved':True,'outside_preserved':True}))


if __name__ == '__main__':
    main()
