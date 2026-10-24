"""Find visible UV aliases per painted texel, not by whole-face centroids."""
import numpy as np
from numba import njit


@njit(cache=False)
def _aliases(positions, uv, paint, boxes):
    height, width = paint.shape
    unsafe = np.zeros((height, width), np.uint8)
    hits = np.zeros((height, width), np.uint16)
    for t in range(len(positions)):
        q = uv[t]
        umin, umax = int(np.floor(q[:, 0].min())), int(np.floor(q[:, 0].max()))
        vmin, vmax = int(np.floor(q[:, 1].min())), int(np.floor(q[:, 1].max()))
        if umax-umin > 2 or vmax-vmin > 2:
            continue
        for tileu in range(umin, umax+1):
            for tilev in range(vmin, vmax+1):
                px = (q[:, 0]-tileu)*width-.5
                py = (1-(q[:, 1]-tilev))*height-.5
                x0, x1 = max(0, int(np.ceil(px.min()))), min(width-1, int(np.floor(px.max())))
                y0, y1 = max(0, int(np.ceil(py.min()))), min(height-1, int(np.floor(py.max())))
                den = (py[1]-py[2])*(px[0]-px[2])+(px[2]-px[1])*(py[0]-py[2])
                if abs(den) < 1e-9:
                    continue
                for y in range(y0, y1+1):
                    for x in range(x0, x1+1):
                        if not paint[y, x]:
                            continue
                        a = ((py[1]-py[2])*(x-px[2])+(px[2]-px[1])*(y-py[2]))/den
                        b = ((py[2]-py[0])*(x-px[2])+(px[0]-px[2])*(y-py[2]))/den
                        c = 1-a-b
                        if min(a, b, c) < -1e-5:
                            continue
                        p = positions[t, 0]*a+positions[t, 1]*b+positions[t, 2]*c
                        inside = False
                        for box in boxes:
                            if box[0] <= p[0] <= box[1] and box[2] <= p[1] <= box[3] and box[4] <= p[2] <= box[5]:
                                inside = True
                        hits[y, x] += 1
                        if not inside:
                            unsafe[y, x] = 1
    return unsafe, hits


def check_paint_scope(positions, uv, paint, allowed_boxes):
    p, q = np.asarray(positions, np.float32), np.asarray(uv, np.float32)
    mask, boxes = np.asarray(paint, bool), np.asarray(allowed_boxes, np.float32)
    if p.ndim != 3 or p.shape[1:] != (3, 3) or q.shape != (len(p), 3, 2) or mask.ndim != 2 or not mask.any():
        raise ValueError('Explicit native triangles, UVs and nonempty paint mask are required')
    if boxes.ndim != 2 or boxes.shape[1] != 6 or not len(boxes) or not np.isfinite(p).all() or not np.isfinite(q).all() or not np.isfinite(boxes).all():
        raise ValueError('Finite geometry and allowed model-space boxes are required')
    if max(mask.shape) > 8192 or np.any(boxes[:, [0, 2, 4]] > boxes[:, [1, 3, 5]]):
        raise ValueError('Invalid scope bounds')
    unsafe, hits = _aliases(p, q, mask, boxes)
    safe = mask & (unsafe == 0) & (hits > 0)
    return safe, {'requested_texels': int(mask.sum()), 'safe_texels': int(safe.sum()),
                  'unsafe_alias_texels': int((mask & (unsafe > 0)).sum()),
                  'unmapped_texels': int((mask & (hits == 0)).sum()),
                  'method': 'per-texel barycentric positions across declared visible users; whole-triangle centroid is not a scope test'}
