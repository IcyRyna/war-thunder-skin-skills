"""Texel ownership in vector_paint's native, top-left atlas convention."""

import math
import os
import tempfile
import numpy as np

os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "war-thunder-skins-numba"))
from numba import njit


@njit(cache=True)
def triangle_setup(uv, width, height):
    p = np.empty((3, 2), np.float64)
    for k in range(3):
        p[k, 0] = uv[k, 0] * (width - 1)
        p[k, 1] = (1 - uv[k, 1]) * (height - 1)
    den = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
    altitude = np.empty(3, np.float64)
    for k in range(3):
        a, b = p[(k + 1) % 3], p[(k + 2) % 3]
        altitude[k] = abs(den) / max(math.hypot(a[0] - b[0], a[1] - b[1]), 1e-12)
    bounds = (
        max(0, math.floor(p[:, 0].min()) - 1),
        min(width, math.ceil(p[:, 0].max()) + 2),
        max(0, math.floor(p[:, 1].min()) - 1),
        min(height, math.ceil(p[:, 1].max()) + 2),
    )
    return p, den, altitude, bounds


@njit(cache=True)
def edge_distance(p, den, altitude, x, y):
    a = ((p[1, 1] - p[2, 1]) * (x - p[2, 0]) + (p[2, 0] - p[1, 0]) * (y - p[2, 1])) / den
    b = ((p[2, 1] - p[0, 1]) * (x - p[2, 0]) + (p[0, 0] - p[2, 0]) * (y - p[2, 1])) / den
    return min(a * altitude[0], b * altitude[1], (1 - a - b) * altitude[2])


@njit(cache=True)
def surface_owners(uvs, assignment, facing, width, height):
    """Match the legacy vector winner, including its stored float32 score and first-on-tie rule."""
    owners = np.full((height, width), -1, np.int32)
    best = np.full((height, width), -1e30, np.float32)
    for tri in range(len(uvs)):
        chart = assignment[tri]
        if chart < 0:
            continue
        p, den, altitude, (x0, x1, y0, y1) = triangle_setup(uvs[tri], width, height)
        if abs(den) < 1e-12:
            continue
        for y in range(y0, y1):
            for x in range(x0, x1):
                edge = edge_distance(p, den, altitude, x, y)
                if edge < -0.75:
                    continue
                score = -chart * 10.0 + facing[tri] + (5.0 if edge >= 0 else 0.0)
                if score > best[y, x]:
                    best[y, x] = score
                    owners[y, x] = tri
    return owners
