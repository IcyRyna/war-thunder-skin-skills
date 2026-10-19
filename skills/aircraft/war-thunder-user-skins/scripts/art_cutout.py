"""Clean cutout of a character painted on a flat backdrop, for a livery: sharp edges, no backdrop haze or fringe.

  python -B art_cutout.py --src picture-on-grey.png --out cutout.png [--inner 10 --outer 34 --min-area 600]

Use it on pictures whose backdrop is one flat colour: official art whose background was replaced with flat grey by an
image model, or a generated picture asked for on a plain #808080 backdrop.  Model-based subject masks (Composa
"person" / "any") keep glows and translucent light as a grey haze on a dark coat and leave soft edges; a flat
backdrop can be keyed exactly.

Composa's "plain" background removal only erases backdrop connected to the picture edges; grey enclosed between an
arm and the body stays.  Here every sizeable patch of the backdrop colour is backdrop, wherever it is:
  * distance d of each pixel from the backdrop colour (median of the picture border);
  * seeds: connected patches with d < --inner of at least --min-area pixels (small grey details inside the figure,
    such as sword metal highlights, are smaller and stay);
  * the backdrop zone grows from the seeds through pixels with d < --outer, so the anti-aliased rim is included;
  * alpha = 0 in the core, a linear ramp from --inner to --outer on the rim, 1 elsewhere;
  * the one-pixel ring next to the backdrop gets alpha = d / d(least backdrop-like neighbour), for strongly coloured edges;
  * rim colours are un-mixed from the backdrop (c = (obs - (1 - a) * bg) / a), so no grey fringe shows on a dark coat.
Writes the RGBA cutout and a check sheet over the dark coat (#333334).
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def cutout(rgb, inner=10., outer=34., min_area=600):
    """(RGBA uint8, backdrop colour, report) for an RGB float array."""
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    d = np.sqrt(((rgb - bg) ** 2).sum(-1))
    core = d < inner
    lab, n = ndimage.label(core)
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    seeds = np.isin(lab, 1 + np.flatnonzero(sizes >= min_area))
    zone_lab, _ = ndimage.label(d < outer)
    zone = np.isin(zone_lab, np.unique(zone_lab[seeds & (zone_lab > 0)]))
    alpha = np.ones(d.shape, np.float32)
    alpha[zone] = np.clip((d[zone] - inner) / (outer - inner), 0, 1)
    alpha[seeds] = 0
    # Strongly coloured edges: a pixel half covered by a red figure is far from the backdrop colour yet not opaque.
    # For the one-pixel ring around the backdrop, take the neighbour (5 x 5) least like the backdrop as the figure's
    # own colour and set alpha = d / d(neighbour); without this a grey-mixed rim stays opaque on the dark coat.
    ring = (ndimage.distance_transform_edt(~zone) <= 1.5) & ~zone
    if ring.any():
        ys, xs = np.nonzero(ring)
        H, W = d.shape
        best = d[ys, xs].copy()
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                yy, xx = np.clip(ys + dy, 0, H - 1), np.clip(xs + dx, 0, W - 1)
                best = np.maximum(best, np.where(zone[yy, xx], 0, d[yy, xx]))
        alpha[ys, xs] = np.minimum(alpha[ys, xs], np.clip(d[ys, xs] / np.maximum(best, 1e-3), 0, 1))
    safe = np.maximum(alpha, 1e-3)[..., None]
    col = np.clip((rgb - (1 - alpha[..., None]) * bg) / safe, 0, 255)
    col = np.where(alpha[..., None] > 0, col, 0)
    out = np.dstack([col, alpha * 255]).round().astype(np.uint8)
    return out, bg, dict(transparent=round(float((alpha == 0).mean()), 4), rim=round(float(((alpha > 0) & (alpha < 1)).mean()), 4))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--src', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--inner', type=float, default=10.); ap.add_argument('--outer', type=float, default=34.)
    ap.add_argument('--min-area', type=int, default=600)
    a = ap.parse_args(argv)
    rgb = np.asarray(Image.open(a.src).convert('RGB'), np.float32)
    out, bg, stats = cutout(rgb, a.inner, a.outer, a.min_area)
    Image.fromarray(out, 'RGBA').save(a.out)
    dark = Image.new('RGBA', (out.shape[1], out.shape[0]), (51, 51, 52, 255)); dark.alpha_composite(Image.fromarray(out, 'RGBA'))
    dark.convert('RGB').save(Path(a.out).with_name(Path(a.out).stem + '-on-coat.png'))
    rep = dict(src=a.src, backdrop=[round(float(v), 1) for v in bg], inner=a.inner, outer=a.outer, min_area=a.min_area, **stats)
    Path(a.out).with_suffix('.json').write_text(json.dumps(rep, indent=1), encoding='utf-8')
    print(json.dumps(rep))


if __name__ == '__main__':
    main()
