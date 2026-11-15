"""Sample paint footprints at the world locations shown on a diagnostic map."""

import math
from pathlib import Path
import numpy as np
from scipy import ndimage
import os
import tempfile

os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "war-thunder-skins-numba"))
from numba import njit

from vector_paint import _inside, compile_images, stroke_outline
from uv_ownership import triangle_setup, edge_distance


class Shape(tuple):
    def __new__(cls, label, chart, kind, points, *, holes=(), image=None, region=None):
        shape = super().__new__(cls, (label, chart, kind, points))
        shape.holes = holes
        shape.image = image
        shape.region = region
        return shape


def footprints(design, selected, directory=Path(".")):
    shapes = []
    for layer in design.get("layers", []):
        for item in layer.get("items", []):
            if item["chart"] not in selected:
                continue
            points = item["points"]
            if item["type"] == "stroke":
                length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
                span = item.get("taper_length", length)
                taper = item.get("taper", "none")
                points = stroke_outline(
                    points,
                    item["width"],
                    span if taper in ("start", "both") else 0,
                    span if taper in ("end", "both") else 0,
                )
            shapes.append(
                Shape(
                    item.get("id", layer["name"]),
                    item["chart"],
                    item["type"],
                    points,
                    holes=item.get("holes", ()),
                )
            )
    chart_ids = [c["id"] for c in design.get("charts", [])] or sorted(selected)
    image_layers = []
    for layer in design.get("layers", []):
        images = [s for s in layer.get("images", []) if s["chart"] in selected]
        if images:
            image_layers.append(dict(name=layer["name"], images=images))
    compiled = compile_images(
        dict(charts=[dict(id=n) for n in chart_ids], layers=image_layers),
        design.get("palette", {}),
        directory,
        float(design.get("text_pixels_per_metre", 400)),
    )
    regions = design.get("inspection_regions", [])
    seen = set()
    for li, placements in compiled:
        for spec, im in zip(image_layers[li]["images"], placements):
            chart = chart_ids[im["chart"]]
            label = im["id"]
            kind = "text" if "text" in spec else "image"
            angle = im["angle"]
            c, s = math.cos(angle), math.sin(angle)
            w, h = im["size"]

            def corners(box):
                x0, y0, x1, y1 = box
                pts = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) - [0.5, 0.5]
                pts *= np.array([-w if im["flip"] else w, -h])
                return pts @ np.array([[c, s], [-s, c]]) + im["center"]

            shapes.append(Shape(label, chart, kind, corners([0, 0, 1, 1]), image=im))
            for i, r in enumerate(regions):
                if (r["chart"], r["item"]) != (chart, label):
                    continue
                if i in seen:
                    raise ValueError(f"Ambiguous inspection region {r}")
                box = r["box"]
                if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                    raise ValueError(
                        "Inspection box must be inside the cropped source, in normalized coordinates"
                    )
                if not r["name"]:
                    raise ValueError("An inspection region needs a name")
                shapes.append(
                    Shape(label + "/" + r["name"], chart, "focus", corners(box), image=im, region=box)
                )
                seen.add(i)
    if any(i not in seen and r["chart"] in selected for i, r in enumerate(regions)):
        raise ValueError("Inspection region references a missing image or text item")
    return shapes


@njit(cache=True)
def in_polygon(u, v, points):
    result = np.zeros(u.shape, np.bool_)
    for y in range(u.shape[0]):
        for x in range(u.shape[1]):
            result[y, x] = _inside(u[y, x], v[y, x], points, 0, len(points))
    return result


def footprint_mask(shape, u, v):
    pts = np.asarray(shape[3], np.float64)
    result = in_polygon(u, v, pts)
    for ring in shape.holes:
        result &= ~in_polygon(u, v, np.asarray(ring, np.float64))
    im = shape.image
    if im is None or not result.any():
        return result
    du = u[result] - im["center"][0]
    dv = v[result] - im["center"][1]
    ca, sa = math.cos(im["angle"]), math.sin(im["angle"])
    lx = (du * ca + dv * sa) * (-1 if im["flip"] else 1)
    ly = -du * sa + dv * ca
    alpha = im["image"][:, :, 3]
    h, w = alpha.shape
    x = np.clip((lx / im["size"][0] + 0.5) * w - 0.5, 0, w - 1)
    y = np.clip((0.5 - ly / im["size"][1]) * h - 0.5, 0, h - 1)
    ix = x.astype(int)
    iy = y.astype(int)
    nx = np.minimum(ix + 1, w - 1)
    ny = np.minimum(iy + 1, h - 1)
    dx = x - ix
    dy = y - iy
    weight = (
        (alpha[iy, ix] * (1 - dx) + alpha[iy, nx] * dx) * (1 - dy)
        + (alpha[ny, ix] * (1 - dx) + alpha[ny, nx] * dx) * dy
    ) * im["opacity"]
    fade = im["fade"]
    if fade[0]:
        fx, fy = fade[3:] - fade[1:3]
        t = np.clip(((u[result] - fade[1]) * fx + (v[result] - fade[2]) * fy) / (fx * fx + fy * fy), 0, 1)
        weight *= 1 - t * t * (3 - 2 * t)
    result[result] = weight > 0
    if len(im["clip"]):
        result &= in_polygon(u, v, im["clip"])
    return result


def barycentric_field(screen, uv, tri, atlas_size):
    """Interpolate the actual UV at each screen pixel centre of the carrier triangle."""
    h, w = tri.shape
    selected = tri >= 0
    if not selected.any():
        return None
    if not selected.all():
        iy, ix = ndimage.distance_transform_edt(~selected, return_distances=False, return_indices=True)
        tri = tri[iy, ix]
    yy, xx = np.indices((h, w), dtype=np.float64)
    px = np.empty((h, w))
    py = np.empty((h, w))
    for top in range(0, h, 128):
        sl = slice(top, top + 128)
        ids = tri[sl]
        a, b, c = np.moveaxis(screen[ids, :, :2].astype(np.float64), 2, 0)
        ex = b - a
        fx = c - a
        dx = xx[sl] + 0.5 - a[:, :, 0]
        dy = yy[sl] + 0.5 - a[:, :, 1]
        det = ex[:, :, 0] * fx[:, :, 1] - ex[:, :, 1] * fx[:, :, 0]
        w1 = (dx * fx[:, :, 1] - dy * fx[:, :, 0]) / det
        w2 = (ex[:, :, 0] * dy - ex[:, :, 1] * dx) / det
        au, bu, cu = np.moveaxis(uv[ids], 2, 0)
        value = au + w1[:, :, None] * (bu - au) + w2[:, :, None] * (cu - au)
        px[sl] = value[:, :, 0] * (atlas_size[0] - 1)
        py[sl] = (1 - value[:, :, 1]) * (atlas_size[1] - 1)
    return px, py


@njit(cache=True)
def inside_uv(uv, u, v):
    """Strict interior: adjacent triangles on a normal shared edge are not UV aliases."""
    ax, ay = uv[0]
    bx, by = uv[1]
    cx, cy = uv[2]
    den = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(den) < 1e-24:
        return False
    b = ((u - ax) * (cy - ay) - (v - ay) * (cx - ax)) / den
    c = ((bx - ax) * (v - ay) - (by - ay) * (u - ax)) / den
    return min(b, c, 1. - b - c) > 1e-7


@njit(cache=True)
def chart_aliases(uvs, assignment, carriers, winners, px, py, width, height):
    aliases = np.zeros(len(carriers), np.bool_)
    for i in range(len(carriers)):
        tri, winner = carriers[i], winners[i]
        if winner < 0 or winner == tri or assignment[winner] != assignment[tri]:
            continue
        u, v = px[i] / (width - 1), 1. - py[i] / (height - 1)
        aliases[i] = inside_uv(uvs[winner], u, v) and inside_uv(uvs[tri], u, v)
    return aliases


@njit(cache=True)
def triangle_risks(uvs, assignment, owners, protected):
    """Aggregate only for coarse callers. The visible map samples individual texels."""
    h, w = owners.shape
    flags = np.zeros((len(uvs), 3), np.bool_)
    for tri in range(len(uvs)):
        chart = assignment[tri]
        if chart < 0:
            continue
        p, den, alt, (x0, x1, y0, y1) = triangle_setup(uvs[tri], w, h)
        if abs(den) < 1e-12:
            continue
        for y in range(y0, y1):
            for x in range(x0, x1):
                if edge_distance(p, den, alt, x, y) < -0.75:
                    continue
                winner = owners[y, x]
                if winner >= 0 and assignment[winner] != chart:
                    flags[tri, 0] = True
                elif winner >= 0 and winner != tri and not flags[tri, 2]:
                    u, v = x / (w - 1), 1. - y / (h - 1)
                    flags[tri, 2] = inside_uv(uvs[winner], u, v) and inside_uv(uvs[tri], u, v)
                if protected[y, x]:
                    flags[tri, 1] = True
    return flags
