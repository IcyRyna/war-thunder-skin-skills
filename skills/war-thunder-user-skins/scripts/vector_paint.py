"""Paint analytic airframe-space vectors straight into the original UV atlas.

Shapes are authored in metres on named charts such as top (x, |z|) or side
(x, y).  Raster layers place character art and font-rendered text on the
same charts with centre, width, rotation, fade and clip.  Every target texel is evaluated at supersampled positions on the real
triangles, so long tapers stay straight and anti-aliased at the atlas density
instead of being enlarged from a low-resolution projection overlay.  Outputs
are separate RGBA layers, an editable SVG per chart, an optional composite over
a base color map and a receipt.  The original UV is never changed.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import os
import tempfile
# Keep Numba's on-disk cache out of the Skill folder (and any installed copy).
os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'war-thunder-skins-numba'))
from numba import njit
from PIL import Image

from artifact_io import ArtifactError, ArtifactTransaction
from surface_preview import load_geometry

Image.MAX_IMAGE_PIXELS = 8192 * 8192
AXES = {'x': 0, 'y': 1, 'z': 2}
FILL_KINDS = {'solid': 0, 'tri-mosaic': 2, 'tri-halftone': 3, 'dot-halftone': 4}
TAPERS = ('none', 'start', 'end', 'both')
MAX_ATLAS = 8192


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_axis(spec):
    text = str(spec).strip().lower()
    mode = 0
    if text.startswith('abs_'):
        mode, text = 2, text[4:]
    elif text.startswith('-'):
        mode, text = 1, text[1:]
    if text not in AXES:
        raise ValueError(f'Chart axis must be x/y/z with optional - or abs_ prefix: {spec}')
    return AXES[text], mode


def parse_color(value, palette):
    if isinstance(value, str) and value in palette:
        value = palette[value]
    if not isinstance(value, str) or len(value) != 7 or value[0] != '#':
        raise ValueError(f'Colors must be #rrggbb or a palette name: {value}')
    try:
        return [int(value[i:i + 2], 16) for i in (1, 3, 5)]
    except ValueError:
        raise ValueError(f'Invalid hex color: {value}') from None


def point(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value):
        raise ValueError(f'{name} must be a finite [u, v] pair')
    return float(value[0]), float(value[1])


def compile_fill(spec, palette):
    """Return (meta[4], floats[16]) for one fill: kind, seed, gradient flag, invert."""
    meta, values = [0, 0, 0, 0], [0.] * 16
    if not isinstance(spec, dict):
        spec = {'color': spec}
    unknown = set(spec) - {'color', 'opacity', 'gradient', 'pattern', 'cell', 'jitter', 'angle', 'seed', 'from', 'to', 'gamma', 'invert'}
    if unknown:
        raise ValueError(f'Unknown fill keys: {sorted(unknown)}')
    kind = spec.get('pattern', 'solid')
    if kind not in FILL_KINDS:
        raise ValueError(f'Fill pattern must be one of {sorted(FILL_KINDS)}')
    meta[0] = FILL_KINDS[kind]
    gradient = spec.get('gradient')
    if gradient is not None:
        if not isinstance(gradient, dict) or set(gradient) != {'from', 'to', 'colors'} or len(gradient['colors']) != 2:
            raise ValueError('gradient needs from, to and two colors')
        values[0:3] = parse_color(gradient['colors'][0], palette)
        values[3:6] = parse_color(gradient['colors'][1], palette)
        values[7:9] = point(gradient['from'], 'gradient.from')
        values[9:11] = point(gradient['to'], 'gradient.to')
        meta[2] = 1
        if 'color' in spec:
            raise ValueError('Use either color or gradient in one fill')
    else:
        values[0:3] = values[3:6] = parse_color(spec.get('color'), palette)
    opacity = float(spec.get('opacity', 1))
    if not 0 < opacity <= 1:
        raise ValueError('opacity must be in (0, 1]')
    values[6] = opacity
    if meta[0]:
        cell = float(spec.get('cell', 0))
        if not 0.005 <= cell <= 5:
            raise ValueError('Pattern cell must be 0.005-5 design units (metres)')
        values[11], values[13] = cell, math.radians(float(spec.get('angle', 0)))
        values[12] = float(spec.get('jitter', 0.06 if kind == 'tri-mosaic' else 0))
        if not 0 <= values[12] <= 0.5:
            raise ValueError('jitter must be 0-0.5')
        meta[1] = int(spec.get('seed', 1)) & 0x7fffffff
        if kind != 'tri-mosaic':
            if 'from' not in spec or 'to' not in spec:
                raise ValueError(f'{kind} needs from and to: full-size marks at from, vanished at to')
            start, end = point(spec['from'], 'from'), point(spec['to'], 'to')
            if start == end:
                raise ValueError('Halftone from and to must differ')
            values[14] = float(spec.get('gamma', 1))
            if not 0.2 <= values[14] <= 5:
                raise ValueError('gamma must be 0.2-5')
            meta[3] = 1 if spec.get('invert') else 0
            return meta, values, (start, end)
    elif any(key in spec for key in ('cell', 'jitter', 'angle', 'seed', 'from', 'to', 'gamma', 'invert')):
        raise ValueError('Pattern parameters require a pattern fill')
    return meta, values, None


def load_design(path):
    design = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(design, dict) or design.get('schema_version') != 1:
        raise ValueError('Design schema_version must be 1')
    palette = design.get('palette', {})
    if not isinstance(palette, dict):
        raise ValueError('palette must map names to #rrggbb')
    for name, value in palette.items():
        parse_color(value, {})
    charts = design.get('charts')
    layers = design.get('layers')
    if not isinstance(charts, list) or not charts or not isinstance(layers, list) or not layers:
        raise ValueError('Design needs nonempty charts and layers lists')
    ids = [c.get('id') for c in charts]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        raise ValueError('Chart ids must be unique nonempty strings')
    names = [layer.get('name') for layer in layers]
    if len(set(names)) != len(names) or not all(isinstance(n, str) and n and '/' not in n and '\\' not in n for n in names):
        raise ValueError('Layer names must be unique file-safe strings')
    ss = int(design.get('supersample', 4))
    if not 1 <= ss <= 8:
        raise ValueError('supersample must be 1-8 samples per axis')
    return design, palette, ss


def select_charts(design, geometry):
    """Assign each triangle to the first matching chart, or -1."""
    world = geometry['triangles']
    names = np.asarray(geometry['names']).astype(str)
    node_names = names[geometry['node_ids']]
    material_names = None
    if 'material_ids' in geometry:
        material_names = np.asarray(geometry['material_names']).astype(str)[geometry['material_ids']]
    normal = np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0]).astype(np.float64)
    area = np.linalg.norm(normal, axis=1) * .5
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-30)
    centroid = world.mean(axis=1).astype(np.float64)
    assignment = np.full(len(world), -1, np.int32)
    axes = np.zeros((len(design['charts']), 5), np.int32)
    facing = np.zeros(len(world), np.float32)
    quality, warnings = {}, []
    for index, chart in enumerate(design['charts']):
        unknown = set(chart) - {'id', 'u', 'v', 'nodes', 'materials', 'normal', 'facing', 'where'}
        if unknown:
            raise ValueError(f'Unknown chart keys in {chart["id"]}: {sorted(unknown)}')
        (ua, um), (va, vm) = parse_axis(chart.get('u', '')), parse_axis(chart.get('v', ''))
        if ua == va:
            raise ValueError(f'Chart {chart["id"]} needs two different axes')
        axes[index, :4] = ua, um, va, vm
        mask = assignment < 0
        if 'nodes' in chart:
            patterns = chart['nodes']
            if not isinstance(patterns, list) or not patterns:
                raise ValueError('chart nodes must be a nonempty list of fnmatch patterns')
            unique = np.unique(node_names)
            chosen = [n for n in unique if any(fnmatch.fnmatchcase(n, p) for p in patterns)]
            mask &= np.isin(node_names, chosen)
        if 'materials' in chart:
            if material_names is None:
                raise ValueError('Geometry has no material names for chart material filters')
            unique = np.unique(material_names)
            chosen = [n for n in unique if any(fnmatch.fnmatchcase(n, p) for p in chart['materials'])]
            mask &= np.isin(material_names, chosen)
        if 'normal' in chart:
            rule = chart['normal']
            axis, sign = parse_axis(rule.get('axis', ''))
            component = normal[:, axis]
            component = np.abs(component) if sign == 2 else -component if sign == 1 else component
            mask &= (component >= float(rule.get('min', -1))) & (component <= float(rule.get('max', 1)))
        if 'where' in chart:
            if not isinstance(chart['where'], dict) or not chart['where']:
                raise ValueError('chart where maps axis specs to [min, max] on triangle centroids')
            for spec, bounds in chart['where'].items():
                axis, sign = parse_axis(spec)
                lo, hi = point(bounds, f'{chart["id"]} where {spec}')
                component = centroid[:, axis]
                component = np.abs(component) if sign == 2 else -component if sign == 1 else component
                mask &= (component >= lo) & (component <= hi)
        if 'facing' in chart:
            axis, sign = parse_axis(chart['facing'])
            component = normal[:, axis]
            component = np.abs(component) if sign == 2 else -component if sign == 1 else component
            facing[mask] = component[mask]
        assignment[mask] = index
        if not mask.any():
            raise ValueError(f'Chart {chart["id"]} selects no triangles')
        chart_uvs = geometry['uvs'][mask]
        if chart_uvs.min() < 0 or chart_uvs.max() > 1:
            raise ValueError(f'Chart {chart["id"]} selects repeating/out-of-tile UVs; narrow it with materials or nodes')
        # A chart only works where its two axes lie roughly in the surface.
        tri = world[mask].astype(np.float64)
        coords = []
        for spec in (chart['u'], chart['v']):
            axis, sign = parse_axis(spec)
            value = tri[:, :, axis]
            coords.append(np.abs(value) if sign == 2 else -value if sign == 1 else value)
        uu, vv = coords
        flat = .5 * np.abs((uu[:, 1] - uu[:, 0]) * (vv[:, 2] - vv[:, 0]) - (uu[:, 2] - uu[:, 0]) * (vv[:, 1] - vv[:, 0]))
        ratio = flat / np.maximum(area[mask], 1e-30)
        weight = area[mask].sum()
        stretched = float(area[mask][ratio < .5].sum() / weight) if weight > 0 else 0.
        quality[chart['id']] = dict(triangles=int(mask.sum()), world_area_m2=round(float(weight), 4),
                                    foreshortened_area_fraction=round(stretched, 4))
        if stretched > .05:
            warnings.append(f'Chart {chart["id"]}: {stretched:.1%} of its area is foreshortened over 2x; patterns and line widths will streak there. Split it by normal/where or use a chart whose axes lie in that surface.')
    return assignment, axes, facing, quality, warnings


def compile_items(design, palette):
    chart_index = {c['id']: i for i, c in enumerate(design['charts'])}
    meta, floats, points, lengths, fill_meta, fill_values, boxes, labels = [], [], [], [], [], [], [], []
    for layer_index, layer in enumerate(design['layers']):
        if 'images' in layer:
            if 'items' in layer:
                raise ValueError(f'Layer {layer["name"]}: a layer holds either vector items or images, not both')
            continue
        items = layer.get('items')
        if not isinstance(items, list) or not items:
            raise ValueError(f'Layer {layer["name"]} needs a nonempty items list or an images list')
        for item_index, item in enumerate(items):
            label = item.get('id', f'{layer["name"]}[{item_index}]')
            kind = item.get('type')
            if kind not in ('polygon', 'stroke'):
                raise ValueError(f'{label}: type must be polygon or stroke')
            if item.get('chart') not in chart_index:
                raise ValueError(f'{label}: unknown chart {item.get("chart")}')
            pts = [point(p, f'{label} point') for p in item.get('points', [])]
            if len(pts) < (3 if kind == 'polygon' else 2):
                raise ValueError(f'{label}: too few points')
            fm, fv, halftone = compile_fill(item.get('fill'), palette)
            if halftone:
                # Halftone ramp endpoints reuse slots 7-10 only when no color gradient exists.
                if fm[2]:
                    raise ValueError(f'{label}: halftone fills use one solid color')
                fv[7:9], fv[9:11] = halftone
            width = taper0 = taper1 = 0.
            arc = [0.]
            for a, b in zip(pts, pts[1:]):
                arc.append(arc[-1] + math.dist(a, b))
            if kind == 'stroke':
                width = float(item.get('width', 0))
                if not width > 0:
                    raise ValueError(f'{label}: stroke width must be positive')
                taper = item.get('taper', 'none')
                if taper not in TAPERS:
                    raise ValueError(f'{label}: taper must be one of {TAPERS}')
                span = float(item.get('taper_length', arc[-1]))
                if not 0 < span <= arc[-1] * (1 if taper != 'both' else .5) + 1e-9:
                    raise ValueError(f'{label}: taper_length must fit inside the stroke')
                taper0 = span if taper in ('start', 'both') else 0.
                taper1 = span if taper in ('end', 'both') else 0.
                if any(math.dist(a, b) <= 0 for a, b in zip(pts, pts[1:])):
                    raise ValueError(f'{label}: repeated stroke point')
            elif any(key in item for key in ('width', 'taper', 'taper_length')):
                raise ValueError(f'{label}: width/taper apply to strokes only')
            array = np.asarray(pts)
            pad = width * .5
            boxes.append([array[:, 0].min() - pad, array[:, 1].min() - pad, array[:, 0].max() + pad, array[:, 1].max() + pad])
            meta.append([layer_index, chart_index[item['chart']], 0 if kind == 'polygon' else 1, len(points), len(pts), len(fill_meta)])
            floats.append([width, taper0, taper1, arc[-1]])
            points.extend(pts); lengths.extend(arc)
            fill_meta.append(fm); fill_values.append(fv)
            labels.append(dict(id=label, layer=layer['name'], chart=item['chart'], type=kind))
    if not meta:
        # Raster-only design: keep array shapes valid for the vector pass.
        meta, floats, points, lengths = [[-1, -1, 0, 0, 0, 0]], [[0., 0., 0., 0.]], [(0., 0.)], [0.]
        fill_meta, fill_values, boxes = [[0, 0, 0, 0]], [[0.] * 16], [[1e30, 1e30, -1e30, -1e30]]
    return dict(meta=np.asarray(meta, np.int32), floats=np.asarray(floats, np.float64),
                points=np.asarray(points, np.float64), lengths=np.asarray(lengths, np.float64),
                fill_meta=np.asarray(fill_meta, np.int32), fill_values=np.asarray(fill_values, np.float64),
                boxes=np.asarray(boxes, np.float64), labels=labels)


@njit(cache=True)
def _hash(i, j, k, seed):
    h = (i * 73856093) ^ (j * 19349663) ^ (k * 83492791) ^ (seed * 2654435761)
    h = (h ^ (h >> 13)) * 1274126177
    h = h ^ (h >> 16)
    return ((h & 0xffffff) / 8388607.5) - 1.


@njit(cache=True)
def _inside(x, y, pts, start, count):
    yes = False
    j = start + count - 1
    for i in range(start, start + count):
        ax, ay, bx, by = pts[i, 0], pts[i, 1], pts[j, 0], pts[j, 1]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            yes = not yes
        j = i
    return yes


@njit(cache=True)
def _half_width(s, width, taper0, taper1, total):
    w = width * .5
    if taper0 > 0 and s < taper0:
        w *= s / taper0
    if taper1 > 0 and total - s < taper1:
        w *= (total - s) / taper1
    return w


@njit(cache=True)
def _on_stroke(x, y, pts, arc, start, count, width, taper0, taper1, total):
    """Butt-ended stroke with round interior joins and linear tapers to real points."""
    for i in range(start, start + count - 1):
        ax, ay, bx, by = pts[i, 0], pts[i, 1], pts[i + 1, 0], pts[i + 1, 1]
        dx, dy = bx - ax, by - ay
        t = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
        if t < 0 or t > 1:
            continue
        half = _half_width(arc[i] + t * (arc[i + 1] - arc[i]), width, taper0, taper1, total)
        if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= half * half:
            return True
    for i in range(start + 1, start + count - 1):
        half = _half_width(arc[i], width, taper0, taper1, total)
        if (x - pts[i, 0]) ** 2 + (y - pts[i, 1]) ** 2 <= half * half:
            return True
    return False


@njit(cache=True)
def _fill(x, y, fm, fv, out):
    """Write straight RGBA (0-255, alpha 0-1) of one fill at a design point."""
    t = 0.
    if fm[2]:
        dx, dy = fv[9] - fv[7], fv[10] - fv[8]
        t = min(1., max(0., ((x - fv[7]) * dx + (y - fv[8]) * dy) / (dx * dx + dy * dy)))
    for c in range(3):
        out[c] = fv[c] * (1 - t) + fv[3 + c] * t
    out[3] = fv[6]
    kind = fm[0]
    if kind == 0:
        return
    upper = 0
    l0 = l1 = l2 = 0.
    cell, angle = fv[11], fv[13]
    ca, sa = math.cos(-angle), math.sin(-angle)
    px, py = (x * ca - y * sa) / cell, (x * sa + y * ca) / cell
    if kind == 4:
        i, j = int(math.floor(px)), int(math.floor(py))
        cx, cy = i + .5, j + .5
    else:
        root3 = math.sqrt(3.)
        a, b = px - py / root3, 2 * py / root3
        i, j = int(math.floor(a)), int(math.floor(b))
        fa, fb = a - i, b - j
        upper = 1 if fa + fb > 1 else 0
        if upper:
            l0, l1, l2 = fa + fb - 1, 1 - fb, 1 - fa
            ga, gb = i + 2. / 3, j + 2. / 3
        else:
            l0, l1, l2 = 1 - fa - fb, fa, fb
            ga, gb = i + 1. / 3, j + 1. / 3
        cy = gb * root3 / 2
        cx = ga + cy / root3
    if kind == 2:
        k = 1. + fv[12] * _hash(i, j, upper, fm[1])
        for c in range(3):
            out[c] = min(255., max(0., out[c] * k))
        return
    # Halftone scale from the mark's own centre, so every mark keeps one size.
    gx, gy = cx * cell, cy * cell
    ux, uy = gx * math.cos(angle) - gy * math.sin(angle), gx * math.sin(angle) + gy * math.cos(angle)
    dx, dy = fv[9] - fv[7], fv[10] - fv[8]
    ramp = min(1., max(0., ((ux - fv[7]) * dx + (uy - fv[8]) * dy) / (dx * dx + dy * dy)))
    size = (1. - ramp) ** fv[14]
    if fm[3]:
        size = 1. - size
    if kind == 4:
        hit = (px - cx) ** 2 + (py - cy) ** 2 <= (size * .5) ** 2
    else:
        floor_value = (1. - size) / 3.
        hit = size > 0 and l0 >= floor_value and l1 >= floor_value and l2 >= floor_value
    if not hit:
        out[3] = 0.


@njit(cache=True)
def _design(xyz, axes, chart):
    u = xyz[axes[chart, 0]]
    v = xyz[axes[chart, 2]]
    if axes[chart, 1] == 1:
        u = -u
    elif axes[chart, 1] == 2:
        u = abs(u)
    if axes[chart, 3] == 1:
        v = -v
    elif axes[chart, 3] == 2:
        v = abs(v)
    return u, v


@njit(cache=True)
def _paint(world, uvs, assignment, facing, axes, protect, meta, floats, pts, arc, fill_meta, fill_values, boxes,
           layer_count, ss, width, height, layers, best, hits):
    n_items = meta.shape[0]
    candidates = np.empty(n_items, np.int64)
    rgba = np.empty(4, np.float64)
    acc = np.zeros((layer_count, 4), np.float64)
    sample = np.zeros(4, np.float64)
    xyz = np.empty(3, np.float64)
    for tri in range(world.shape[0]):
        chart = assignment[tri]
        if chart < 0:
            continue
        p = np.empty((3, 2), np.float64)
        for k in range(3):
            p[k, 0] = uvs[tri, k, 0] * (width - 1)
            p[k, 1] = (1 - uvs[tri, k, 1]) * (height - 1)
        den = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(den) < 1e-12:
            continue
        # Pixel distance per unit barycentric for conservative edge texels.
        scale = np.empty(3, np.float64)
        for k in range(3):
            a, b = p[(k + 1) % 3], p[(k + 2) % 3]
            scale[k] = abs(den) / max(math.hypot(a[0] - b[0], a[1] - b[1]), 1e-12)
        lo_u, lo_v, hi_u, hi_v = 1e300, 1e300, -1e300, -1e300
        for k in range(3):
            for c in range(3):
                xyz[c] = world[tri, k, c]
            u, v = _design(xyz, axes, chart)
            lo_u, lo_v, hi_u, hi_v = min(lo_u, u), min(lo_v, v), max(hi_u, u), max(hi_v, v)
        margin = max(hi_u - lo_u, hi_v - lo_v) + 1e-6
        count = 0
        for item in range(n_items):
            if meta[item, 1] == chart and boxes[item, 0] <= hi_u + margin and boxes[item, 2] >= lo_u - margin \
                    and boxes[item, 1] <= hi_v + margin and boxes[item, 3] >= lo_v - margin:
                candidates[count] = item; count += 1
        x0, x1 = max(0, int(math.floor(min(p[0, 0], p[1, 0], p[2, 0]))) - 1), min(width - 1, int(math.ceil(max(p[0, 0], p[1, 0], p[2, 0]))) + 1)
        y0, y1 = max(0, int(math.floor(min(p[0, 1], p[1, 1], p[2, 1]))) - 1), min(height - 1, int(math.ceil(max(p[0, 1], p[1, 1], p[2, 1]))) + 1)
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                if protect[yy, xx]:
                    continue
                a = ((p[1, 1] - p[2, 1]) * (xx - p[2, 0]) + (p[2, 0] - p[1, 0]) * (yy - p[2, 1])) / den
                b = ((p[2, 1] - p[0, 1]) * (xx - p[2, 0]) + (p[0, 0] - p[2, 0]) * (yy - p[2, 1])) / den
                c = 1 - a - b
                edge = min(a * scale[0], b * scale[1], c * scale[2])
                if edge < -.75:
                    continue
                priority = -chart * 10. + facing[tri] + (5. if edge >= 0 else 0.)
                if priority <= best[yy, xx]:
                    continue
                best[yy, xx] = priority
                acc[:, :] = 0.
                for sy in range(ss):
                    for sx in range(ss):
                        ox, oy = xx + (sx + .5) / ss - .5, yy + (sy + .5) / ss - .5
                        aa = ((p[1, 1] - p[2, 1]) * (ox - p[2, 0]) + (p[2, 0] - p[1, 0]) * (oy - p[2, 1])) / den
                        bb = ((p[2, 1] - p[0, 1]) * (ox - p[2, 0]) + (p[0, 0] - p[2, 0]) * (oy - p[2, 1])) / den
                        for k in range(3):
                            xyz[k] = aa * world[tri, 0, k] + bb * world[tri, 1, k] + (1 - aa - bb) * world[tri, 2, k]
                        u, v = _design(xyz, axes, chart)
                        layer = -1
                        for n in range(count):
                            item = candidates[n]
                            if meta[item, 0] != layer:
                                if layer >= 0:
                                    for q in range(4):
                                        acc[layer, q] += sample[q]
                                layer = meta[item, 0]
                                sample[:] = 0.
                            if meta[item, 2] == 0:
                                covered = _inside(u, v, pts, meta[item, 3], meta[item, 4])
                            else:
                                covered = _on_stroke(u, v, pts, arc, meta[item, 3], meta[item, 4], floats[item, 0], floats[item, 1], floats[item, 2], floats[item, 3])
                            if not covered:
                                continue
                            _fill(u, v, fill_meta[meta[item, 5]], fill_values[meta[item, 5]], rgba)
                            alpha = rgba[3]
                            if alpha <= 0:
                                continue
                            hits[item] += 1
                            # Premultiplied source-over inside one layer.
                            for q in range(3):
                                sample[q] = rgba[q] * alpha + sample[q] * (1 - alpha)
                            sample[3] = alpha + sample[3] * (1 - alpha)
                        if layer >= 0:
                            for q in range(4):
                                acc[layer, q] += sample[q]
                total = ss * ss
                for layer in range(layer_count):
                    alpha = acc[layer, 3] / total
                    if alpha <= 0:
                        for q in range(4):
                            layers[layer, yy, xx, q] = 0
                        continue
                    for q in range(3):
                        layers[layer, yy, xx, q] = int(min(255., max(0., acc[layer, q] / acc[layer, 3] + .5)))
                    layers[layer, yy, xx, 3] = int(min(255., alpha * 255. + .5))
    return 0


def render_text(spec, palette, px_per_m):
    """Rasterise a text placement to straight RGBA; returns (array, width_m, height_m)."""
    from PIL import ImageDraw, ImageFont
    text = spec.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('text placements need nonempty text')
    height = float(spec.get('height', 0))
    if not 0 < height <= 10:
        raise ValueError('text height must be 0-10 m (cap height)')
    font_path = spec.get('font', os.environ.get('WT_SKIN_FONT', 'C:/Windows/Fonts/bahnschrift.ttf'))
    if not Path(font_path).is_file():
        raise ValueError(f'Font file not found: {font_path}')
    cap = max(24, min(800, int(round(height * px_per_m * 2))))
    font = ImageFont.truetype(str(font_path), cap)
    if spec.get('variation'):
        try:
            font.set_variation_by_name(spec['variation'])
        except (OSError, ValueError) as error:
            raise ValueError(f'Font variation {spec["variation"]!r} unavailable: {error}') from None
    tracking = float(spec.get('tracking', 0)) * cap
    color = parse_color(spec.get('color', '#ffffff'), palette)
    probe = ImageDraw.Draw(Image.new('L', (1, 1)))
    cap_box = probe.textbbox((0, 0), 'H', font=font)
    cap_px = cap_box[3] - cap_box[1]
    widths = [probe.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    box = probe.textbbox((0, 0), text, font=font)
    pad = int(cap * .15)
    canvas = Image.new('L', (int(total) + 2 * pad, box[3] - box[1] + 2 * pad), 0)
    draw = ImageDraw.Draw(canvas)
    x = pad
    for ch, w in zip(text, widths):
        draw.text((x, pad - box[1]), ch, fill=255, font=font)
        x += w + tracking
    rgba = np.zeros((canvas.height, canvas.width, 4), np.uint8)
    rgba[:, :, :3] = color
    rgba[:, :, 3] = np.asarray(canvas)
    scale = height / cap_px
    return rgba, canvas.width * scale, canvas.height * scale


def compile_images(design, palette, design_dir, px_per_m):
    """Raster layers as (layer_index, placements); images are premultiplied float32."""
    chart_index = {c['id']: i for i, c in enumerate(design['charts'])}
    layers = []
    for layer_index, layer in enumerate(design['layers']):
        if 'images' not in layer:
            continue
        if not isinstance(layer['images'], list) or not layer['images']:
            raise ValueError(f'Layer {layer["name"]} needs a nonempty images list')
        placements = []
        for index, spec in enumerate(layer['images']):
            label = spec.get('id', f'{layer["name"]}[{index}]')
            unknown = set(spec) - {'id', 'chart', 'source', 'text', 'font', 'variation', 'height', 'tracking', 'color',
                                   'center', 'width', 'rotation', 'flip', 'opacity', 'fade', 'clip', 'crop'}
            if unknown:
                raise ValueError(f'{label}: unknown image keys {sorted(unknown)}')
            if spec.get('chart') not in chart_index:
                raise ValueError(f'{label}: unknown chart {spec.get("chart")}')
            if ('source' in spec) == ('text' in spec):
                raise ValueError(f'{label}: give exactly one of source or text')
            if 'source' in spec:
                path = (design_dir / spec['source']).resolve()
                image = Image.open(path).convert('RGBA')
                if 'crop' in spec:
                    box = [int(v) for v in spec['crop']]
                    if len(box) != 4 or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                        raise ValueError(f'{label}: crop is x0,y0,x1,y1 inside the source image')
                    image = image.crop(box)
                rgba = np.asarray(image)
                width = float(spec.get('width', 0))
                if not 0 < width <= 40:
                    raise ValueError(f'{label}: image width must be 0-40 m')
                height = width * rgba.shape[0] / rgba.shape[1]
                source = str(path)
            else:
                rgba, width, height = render_text(spec, palette, px_per_m)
                source = None
            center = point(spec.get('center'), f'{label} center')
            opacity = float(spec.get('opacity', 1))
            if not 0 < opacity <= 1:
                raise ValueError(f'{label}: opacity must be in (0, 1]')
            fade = np.zeros(5)
            if 'fade' in spec:
                start, end = point(spec['fade'].get('from'), f'{label} fade.from'), point(spec['fade'].get('to'), f'{label} fade.to')
                if start == end:
                    raise ValueError(f'{label}: fade from and to must differ')
                fade = np.array([1., *start, *end])
            clip = np.zeros((0, 2))
            if 'clip' in spec:
                clip = np.asarray([point(q, f'{label} clip') for q in spec['clip']], np.float64)
                if len(clip) < 3:
                    raise ValueError(f'{label}: clip needs at least 3 points')
            premult = rgba.astype(np.float32) / 255.
            premult[:, :, :3] *= premult[:, :, 3:4]
            placements.append(dict(id=label, chart=chart_index[spec['chart']], image=np.ascontiguousarray(premult),
                                   center=np.array(center), size=np.array([width, height]),
                                   angle=math.radians(float(spec.get('rotation', 0))), flip=bool(spec.get('flip', False)),
                                   opacity=opacity, fade=fade, clip=clip, source=source,
                                   pixels_per_m=round(rgba.shape[1] / width, 1)))
        layers.append((layer_index, placements))
    return layers


@njit(cache=True)
def _image_sample(img, x, y, out):
    h, w = img.shape[0], img.shape[1]
    if x < 0 or y < 0 or x > w or y > h:
        out[:] = 0.
        return
    x = min(max(x - .5, 0.), w - 1.)
    y = min(max(y - .5, 0.), h - 1.)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1)
    dx, dy = x - x0, y - y0
    for c in range(4):
        out[c] = (img[y0, x0, c] * (1 - dx) + img[y0, x1, c] * dx) * (1 - dy) + (img[y1, x0, c] * (1 - dx) + img[y1, x1, c] * dx) * dy


@njit(cache=True)
def _paint_image(world, uvs, assignment, facing, axes, protect, chart, img, center, size, angle, flip, opacity,
                 fade, clip, ss, width, height, layer):
    """Composite one placement over a premultiplied float layer; returns covered samples."""
    best = np.full((height, width), -1e30, np.float32)
    ca, sa = math.cos(angle), math.sin(angle)
    radius = math.hypot(size[0] * .5, size[1] * .5)
    sample = np.empty(4, np.float64)
    acc = np.empty(4, np.float64)
    xyz = np.empty(3, np.float64)
    hits = 0
    clip_n = clip.shape[0]
    for tri in range(world.shape[0]):
        if assignment[tri] != chart:
            continue
        lo_u, lo_v, hi_u, hi_v = 1e300, 1e300, -1e300, -1e300
        for k in range(3):
            for c in range(3):
                xyz[c] = world[tri, k, c]
            u, v = _design(xyz, axes, chart)
            lo_u, lo_v, hi_u, hi_v = min(lo_u, u), min(lo_v, v), max(hi_u, u), max(hi_v, v)
        if hi_u < center[0] - radius or lo_u > center[0] + radius or hi_v < center[1] - radius or lo_v > center[1] + radius:
            continue
        p = np.empty((3, 2), np.float64)
        for k in range(3):
            p[k, 0] = uvs[tri, k, 0] * (width - 1)
            p[k, 1] = (1 - uvs[tri, k, 1]) * (height - 1)
        den = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(den) < 1e-12:
            continue
        scale = np.empty(3, np.float64)
        for k in range(3):
            a, b = p[(k + 1) % 3], p[(k + 2) % 3]
            scale[k] = abs(den) / max(math.hypot(a[0] - b[0], a[1] - b[1]), 1e-12)
        x0, x1 = max(0, int(math.floor(min(p[0, 0], p[1, 0], p[2, 0]))) - 1), min(width - 1, int(math.ceil(max(p[0, 0], p[1, 0], p[2, 0]))) + 1)
        y0, y1 = max(0, int(math.floor(min(p[0, 1], p[1, 1], p[2, 1]))) - 1), min(height - 1, int(math.ceil(max(p[0, 1], p[1, 1], p[2, 1]))) + 1)
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                if protect[yy, xx]:
                    continue
                a = ((p[1, 1] - p[2, 1]) * (xx - p[2, 0]) + (p[2, 0] - p[1, 0]) * (yy - p[2, 1])) / den
                b = ((p[2, 1] - p[0, 1]) * (xx - p[2, 0]) + (p[0, 0] - p[2, 0]) * (yy - p[2, 1])) / den
                edge = min(a * scale[0], b * scale[1], (1 - a - b) * scale[2])
                if edge < -.75:
                    continue
                priority = -chart * 10. + facing[tri] + (5. if edge >= 0 else 0.)
                if priority <= best[yy, xx]:
                    continue
                best[yy, xx] = priority
                acc[:] = 0.
                for sy in range(ss):
                    for sx in range(ss):
                        ox, oy = xx + (sx + .5) / ss - .5, yy + (sy + .5) / ss - .5
                        aa = ((p[1, 1] - p[2, 1]) * (ox - p[2, 0]) + (p[2, 0] - p[1, 0]) * (oy - p[2, 1])) / den
                        bb = ((p[2, 1] - p[0, 1]) * (ox - p[2, 0]) + (p[0, 0] - p[2, 0]) * (oy - p[2, 1])) / den
                        for k in range(3):
                            xyz[k] = aa * world[tri, 0, k] + bb * world[tri, 1, k] + (1 - aa - bb) * world[tri, 2, k]
                        u, v = _design(xyz, axes, chart)
                        if clip_n and not _inside(u, v, clip, 0, clip_n):
                            continue
                        du, dv = u - center[0], v - center[1]
                        lx, ly = du * ca + dv * sa, -du * sa + dv * ca
                        if flip:
                            lx = -lx
                        _image_sample(img, (lx / size[0] + .5) * img.shape[1], (.5 - ly / size[1]) * img.shape[0], sample)
                        if sample[3] <= 0:
                            continue
                        weight = opacity
                        if fade[0] > 0:
                            fx, fy = fade[3] - fade[1], fade[4] - fade[2]
                            t = min(1., max(0., ((u - fade[1]) * fx + (v - fade[2]) * fy) / (fx * fx + fy * fy)))
                            weight *= 1. - t * t * (3 - 2 * t)
                        for q in range(4):
                            acc[q] += sample[q] * weight
                        hits += 1
                total = ss * ss
                alpha = acc[3] / total
                if alpha <= 0:
                    continue
                for q in range(4):
                    layer[yy, xx, q] = acc[q] / total + layer[yy, xx, q] * (1 - alpha)
    return hits


def stroke_outline(pts, width, taper0, taper1):
    """Approximate a tapered butt stroke as a polygon for the editable SVG."""
    pts = np.asarray(pts, np.float64)
    arc = np.concatenate([[0.], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    total = arc[-1]
    left, right = [], []
    for i, base in enumerate(pts):
        if i == 0:
            d = pts[1] - pts[0]
        elif i == len(pts) - 1:
            d = pts[-1] - pts[-2]
        else:
            d = (pts[i + 1] - pts[i]) / np.linalg.norm(pts[i + 1] - pts[i]) + (pts[i] - pts[i - 1]) / np.linalg.norm(pts[i] - pts[i - 1])
        d = d / max(np.linalg.norm(d), 1e-12)
        normal = np.array([-d[1], d[0]])
        s, half = arc[i], width * .5
        if taper0 > 0 and s < taper0:
            half *= s / taper0
        if taper1 > 0 and total - s < taper1:
            half *= (total - s) / taper1
        left.append(base + normal * half); right.append(base - normal * half)
    return left + right[::-1]


def write_svg(path, design, palette, chart_id):
    parts, boxes = [], []
    for layer in design['layers']:
        group = []
        for item in layer.get('items', []):
            if item['chart'] != chart_id:
                continue
            fill = item['fill'] if isinstance(item['fill'], dict) else {'color': item['fill']}
            color = fill.get('color') or fill['gradient']['colors'][0]
            hex_color = '#' + ''.join(f'{v:02x}' for v in parse_color(color, palette))
            pts = item['points'] if item['type'] == 'polygon' else stroke_outline(
                item['points'], item['width'],
                *(lambda t, span: (span if t in ('start', 'both') else 0, span if t in ('end', 'both') else 0))(
                    item.get('taper', 'none'), item.get('taper_length', sum(math.dist(a, b) for a, b in zip(item['points'], item['points'][1:])))))
            boxes.extend(pts)
            note = json.dumps({k: v for k, v in fill.items() if k != 'color'}, ensure_ascii=False) if len(fill) > 1 else ''
            attr = f' data-fill="{note.replace(chr(34), "&quot;")}"' if note else ''
            ident = item.get('id', '')
            group.append(f'    <polygon id="{ident}" fill="{hex_color}"{attr} points="' + ' '.join(f'{x:.5f},{y:.5f}' for x, y in pts) + '"/>')
        if group:
            parts.append(f'  <g id="{layer["name"]}">\n' + '\n'.join(group) + '\n  </g>')
    if not boxes:
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n', encoding='utf-8')
        return
    array = np.asarray(boxes, np.float64)
    lo, hi = array.min(axis=0) - .2, array.max(axis=0) + .2
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{lo[0]:.4f} {lo[1]:.4f} {hi[0]-lo[0]:.4f} {hi[1]-lo[1]:.4f}">\n'
                    f'  <!-- chart {chart_id}: design units are metres; pattern fills are recorded in data-fill and rendered in the PNG layers -->\n'
                    + '\n'.join(parts) + '\n</svg>\n', encoding='utf-8')


def run(args):
    design_path, geometry_path = args.design.resolve(), args.geometry.resolve()
    inputs = [design_path, geometry_path, *(p.resolve() for p in (args.base, args.protect) if p is not None)]
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    for source in inputs:
        if out == source or out in source.parents or source in out.parents and source.is_dir():
            raise ArtifactError('Output directory must not contain or sit inside an input')
    design, palette, ss = load_design(design_path)
    geometry = load_geometry(geometry_path, allow_repeat_uv=True)
    base = None
    if args.base is not None:
        base = Image.open(args.base).convert('RGBA')
        size = base.size
    else:
        atlas = design.get('atlas', {})
        size = (int(atlas.get('width', 0)), int(atlas.get('height', 0)))
    if not all(16 <= s <= MAX_ATLAS for s in size):
        raise ValueError('Atlas size comes from --base or design.atlas width/height (16-8192)')
    protect = np.zeros((size[1], size[0]), np.bool_)
    if args.protect is not None:
        mask = Image.open(args.protect).convert('L')
        if mask.size != size:
            raise ValueError('Protect mask must match the atlas size')
        protect = np.asarray(mask) > 0
    assignment, axes, facing, chart_counts, warnings = select_charts(design, geometry)
    items = compile_items(design, palette)
    layer_count = len(design['layers'])
    layers = np.zeros((layer_count, size[1], size[0], 4), np.uint8)
    best = np.full((size[1], size[0]), -1e30, np.float32)
    hits = np.zeros(len(items['labels']), np.int64)
    _paint(np.ascontiguousarray(geometry['triangles'], np.float64), np.ascontiguousarray(geometry['uvs'], np.float64),
           assignment, facing, axes, protect, items['meta'], items['floats'], items['points'], items['lengths'],
           items['fill_meta'], items['fill_values'], items['boxes'], layer_count, ss, size[0], size[1], layers, best, hits)
    raster_layers = compile_images(design, palette, design_path.parent, float(design.get('text_pixels_per_metre', 400)))
    image_records = []
    world64 = np.ascontiguousarray(geometry['triangles'], np.float64)
    uv64 = np.ascontiguousarray(geometry['uvs'], np.float64)
    for layer_index, placements in raster_layers:
        buffer = np.zeros((size[1], size[0], 4), np.float32)
        for placement in placements:
            covered = _paint_image(world64, uv64, assignment, facing, axes, protect, placement['chart'], placement['image'],
                                   placement['center'], placement['size'], placement['angle'], placement['flip'],
                                   placement['opacity'], placement['fade'], placement['clip'], ss, size[0], size[1], buffer)
            image_records.append(dict(id=placement['id'], layer=design['layers'][layer_index]['name'], source=placement['source'],
                                      size_m=[round(float(v), 4) for v in placement['size']],
                                      source_pixels_per_m=placement['pixels_per_m'], sample_hits=int(covered)))
        alpha = buffer[:, :, 3]
        straight = np.where(alpha[:, :, None] > 0, buffer[:, :, :3] / np.maximum(alpha[:, :, None], 1e-6), 0)
        layers[layer_index, :, :, :3] = np.clip(straight * 255 + .5, 0, 255).astype(np.uint8)
        layers[layer_index, :, :, 3] = np.clip(alpha * 255 + .5, 0, 255).astype(np.uint8)
    names = [f'{i + 1:02d}-{layer["name"]}' for i, layer in enumerate(design['layers'])]
    outputs = [out / 'layers' / f'{n}.png' for n in names] + [out / 'charts' / f'{c["id"]}.svg' for c in design['charts']]
    outputs += [out / 'composite.png', out / 'chart-coverage.png', out / 'receipt.json']
    zero = [items['labels'][i]['id'] for i in np.flatnonzero(hits == 0) if items['meta'][i, 0] >= 0]
    zero += [record['id'] for record in image_records if record['sample_hits'] == 0]
    with ArtifactTransaction(outputs, inputs=inputs, label='vector-paint') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        composite = base.copy() if base is not None else Image.new('RGBA', size, (0, 0, 0, 0))
        for index, name in enumerate(names):
            layer = Image.fromarray(layers[index], 'RGBA')
            layer.save(staged[out / 'layers' / f'{name}.png'])
            composite = Image.alpha_composite(composite, layer)
        if base is not None:
            # Color alpha is a separate skin channel; keep the base value.
            composite.putalpha(base.getchannel('A'))
        composite.save(staged[out / 'composite.png'])
        Image.fromarray(np.where(best > -1e29, 255, 0).astype(np.uint8), 'L').save(staged[out / 'chart-coverage.png'])
        for chart in design['charts']:
            if any(item['chart'] == chart['id'] for layer in design['layers'] for item in layer.get('items', [])):
                write_svg(staged[out / 'charts' / f'{chart["id"]}.svg'], design, palette, chart['id'])
            else:
                staged[out / 'charts' / f'{chart["id"]}.svg'].write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n', encoding='utf-8')
        receipt = dict(schema_version=1, tool='vector_paint.py', atlas=dict(width=size[0], height=size[1]), supersample=ss,
                       inputs={str(p): sha256(p) for p in inputs}, charts=chart_counts,
                       layers=[dict(file=f'layers/{n}.png', painted_texels=int((layers[i, :, :, 3] > 0).sum())) for i, n in enumerate(names)],
                       items=[dict(label, sample_hits=int(h)) for label, h in zip(items['labels'], hits) if label['chart'] is not None],
                       images=image_records,
                       zero_hit_items=zero, warnings=warnings, composite_alpha='base color alpha preserved' if base is not None else 'layers only',
                       scope='Analytic vector coverage at original-UV subtexel samples. Layout evidence only: check the result on the model, in the editor and against references.')
        staged[out / 'receipt.json'].write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--geometry', type=Path, required=True, help='geometry.npz from surface_preview.py prepare or scene_preview.py prepare')
    parser.add_argument('--design', type=Path, required=True, help='Design JSON (schema_version 1): palette, charts, layers of polygon/stroke items or image/text placements')
    parser.add_argument('--base', type=Path, help='Base color map; sets atlas size and receives the composite')
    parser.add_argument('--protect', type=Path, help='Mask (same size); nonzero texels are never painted')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    receipt = run(parser.parse_args(argv))
    print(json.dumps(dict(layers=receipt['layers'], zero_hit_items=receipt['zero_hit_items'], charts=receipt['charts']), ensure_ascii=False))
    for warning in receipt['warnings']:
        print('WARNING:', warning, flush=True)
    if receipt['zero_hit_items']:
        print('WARNING: some items never reached a texel; check chart selection and coordinates', flush=True)


if __name__ == '__main__':
    main()
