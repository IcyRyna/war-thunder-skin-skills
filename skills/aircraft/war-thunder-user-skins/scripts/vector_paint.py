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
    meta, values = [0, 0, 0, 0], [0.] * 63
    if not isinstance(spec, dict):
        spec = {'color': spec}
    unknown = set(spec) - {'color', 'opacity', 'gradient', 'shade', 'pattern', 'cell', 'jitter', 'levels', 'contrast', 'inset', 'offset', 'angle', 'seed', 'from', 'to', 'gamma', 'invert', 'mirror'}
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
    if 'shade' in spec:
        # Brightness multiplier across the shape, piecewise linear between 2-6 stops along from -> to: the tube
        # shading of Akamywek's pinstripes (full at the top third, down to x0.73 at the bottom edge).
        shade = spec['shade']
        if not isinstance(shade, dict) or set(shade) != {'from', 'to', 'stops'}:
            raise ValueError('shade needs from, to and stops')
        start, end = point(shade['from'], 'shade.from'), point(shade['to'], 'shade.to')
        stops = shade['stops']
        if start == end or not isinstance(stops, list) or not 2 <= len(stops) <= 6 or any(
                not isinstance(s, (list, tuple)) or len(s) != 2 for s in stops):
            raise ValueError('shade needs different endpoints and 2-6 [position, factor] stops')
        ts = [float(t) for t, _ in stops]
        if ts != sorted(ts) or ts[0] < 0 or ts[-1] > 1 or any(not 0 <= float(f) <= 1.5 for _, f in stops):
            raise ValueError('shade stop positions rise within 0..1 and factors are 0..1.5')
        values[16], values[17:19], values[19:21] = len(stops), start, end
        for n, (t, f) in enumerate(stops):
            values[46 + 2 * n], values[47 + 2 * n] = float(t), float(f)
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
        if 'levels' in spec:
            # Discrete shade steps instead of continuous jitter: [[factor, weight], ...], up to 6.  A factor below 1
            # darkens by multiplying; above 1 it lightens toward white by (factor - 1), so light triangles turn paler,
            # not more saturated (Akamywek's F-2A: dark steps x0.84-0.97, light steps 3-13 % toward white).
            levels = spec['levels']
            if kind != 'tri-mosaic' or 'jitter' in spec:
                raise ValueError('levels apply to tri-mosaic fills and replace jitter')
            if not isinstance(levels, list) or not 1 <= len(levels) <= 6 or any(not isinstance(l, (list, tuple)) or len(l) != 2 for l in levels):
                raise ValueError('levels is a list of 1-6 [factor, weight] pairs')
            total = sum(float(w) for _, w in levels)
            if not math.isfinite(total) or total <= 0 or any(not 0.5 <= float(f) <= 1.5 or float(w) < 0 for f, w in levels):
                raise ValueError('level factors are 0.5-1.5 and weights are nonnegative with a positive sum')
            values[15] = len(levels)
            acc = 0.
            for n, (factor, weight) in enumerate(levels):
                acc += float(weight) / total
                values[34 + n], values[40 + n] = float(factor), acc
            values[12] = 0.
        if 'contrast' in spec:
            # Pattern strength along a ramp: 1 keeps the levels or jitter, 0 flattens them to the fill colour.
            # Akamywek's F-2A nose fades the mosaic out towards the tip.
            ramp = spec['contrast']
            if kind != 'tri-mosaic' or not isinstance(ramp, dict) or set(ramp) != {'from', 'to', 'values'}:
                raise ValueError('contrast needs tri-mosaic and {from, to, values}')
            start, end = point(ramp['from'], 'contrast.from'), point(ramp['to'], 'contrast.to')
            weights = ramp['values']
            if start == end or not isinstance(weights, (list, tuple)) or len(weights) != 2 or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in weights):
                raise ValueError('contrast needs different endpoints and two values in 0..1')
            values[24:31] = [1., *start, *end, *weights]
        if 'inset' in spec:
            # A gap of the fill colour between triangles, as a barycentric fraction of the triangle (0..1/3).
            inset = float(spec['inset'])
            if kind != 'tri-mosaic' or not math.isfinite(inset) or not 0 <= inset < 1 / 3:
                raise ValueError('inset needs tri-mosaic and a fraction in 0..1/3')
            values[31] = inset
        if 'offset' in spec:
            # Where a lattice vertex sits, in design units, so the grid can be aligned to a reference or a panel edge.
            values[32:34] = point(spec['offset'], 'offset')
        if 'mirror' in spec:
            # Kaleidoscope: points left of the line from -> to are reflected across it before the lattice lookup, so
            # both halves show the same triangles and shades mirrored (Akamywek's F-2A slats mirror the mosaic about
            # the centre line of each arrow).
            mirror = spec['mirror']
            if kind != 'tri-mosaic' or not isinstance(mirror, dict) or set(mirror) != {'from', 'to'}:
                raise ValueError('mirror needs tri-mosaic and {from, to}')
            start, end = point(mirror['from'], 'mirror.from'), point(mirror['to'], 'mirror.to')
            if start == end:
                raise ValueError('mirror needs different endpoints')
            values[58:62], values[62] = [*start, *end], 1.
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
    elif any(key in spec for key in ('cell', 'jitter', 'levels', 'contrast', 'inset', 'offset', 'angle', 'seed', 'from', 'to', 'gamma', 'invert', 'mirror')):
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


def select_charts(design, geometry, size=None):
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
    helper = helper_triangles(geometry)          # never painted: whole-atlas helper boxes
    for index, chart in enumerate(design['charts']):
        unknown = set(chart) - {'id', 'u', 'v', 'nodes', 'materials', 'normal', 'facing', 'where', 'frame', 'atlas_box', 'island'}
        if unknown:
            raise ValueError(f'Unknown chart keys in {chart["id"]}: {sorted(unknown)}')
        (ua, um), (va, vm) = parse_axis(chart.get('u', '')), parse_axis(chart.get('v', ''))
        if ua == va:
            raise ValueError(f'Chart {chart["id"]} needs two different axes')
        axes[index, :4] = ua, um, va, vm
        mask = (assignment < 0) & ~helper
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
        if 'atlas_box' in chart:
            # Triangles whose atlas centroid lies in [u0, v0, u1, v1] (fractions of the atlas, top-left origin): the
            # natural way to pick one UV island when a design is drawn on the unwrapped map.
            u0, v0, u1, v1 = (float(v) for v in chart['atlas_box'])
            if not (0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1):
                raise ValueError(f'Chart {chart["id"]}: atlas_box is [u0, v0, u1, v1] in 0..1 with u0 < u1, v0 < v1')
            centre_uv = geometry['uvs'].mean(axis=1)
            cu, cv = centre_uv[:, 0], 1 - centre_uv[:, 1]
            mask &= (cu >= u0) & (cu <= u1) & (cv >= v0) & (cv <= v1)
        if 'island' in chart:
            # Keep only the UV islands (triangles connected through shared UV vertices) that contain the given
            # atlas points [[u, v], ...] in pixels (top-left origin): one painted island, not its neighbours.
            # Seeds are atlas pixels of the real map: --base size, else design.atlas, else 8192.
            if size is None:
                atlas = design.get('atlas', {})
                size = (int(atlas.get('width', MAX_ATLAS)), int(atlas.get('height', MAX_ATLAS)))
            mask &= uv_islands(geometry['uvs'], mask, chart['island'], chart['id'], size)
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
        if 'frame' in chart:
            # A frame chart takes its coordinates from the atlas pixel, not from the u/v world axes, so their
            # foreshortening says nothing (a developed fuselage band reads 36 % "foreshortened").  Widths follow
            # the island's own texel density; check them with airframe_setup.py frames residuals and 1:1 crops.
            quality[chart['id']]['frame'] = True
        elif stretched > .05:
            warnings.append(f'Chart {chart["id"]}: {stretched:.1%} of its area is foreshortened over 2x; patterns and line widths will streak there. Split it by normal/where or use a chart whose axes lie in that surface.')
    return assignment, axes, facing, quality, warnings


def uv_islands(uvs, candidates, seeds, chart_id, size=(8192, 8192)):
    """Mask of the candidate triangles in the UV islands that contain the seed atlas pixels."""
    idx = np.flatnonzero(candidates)
    if not len(idx):
        return candidates
    keys = np.round(uvs[idx].reshape(-1, 2) * (1 << 20)).astype(np.int64)
    _, vid = np.unique(keys[:, 0] * (1 << 22) + keys[:, 1], return_inverse=True)
    vid = vid.reshape(-1, 3)
    parent = np.arange(vid.max() + 1)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, c in vid:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    roots = np.array([find(v) for v in vid[:, 0]])
    pix = np.stack([uvs[idx][..., 0] * (size[0] - 1), (1 - uvs[idx][..., 1]) * (size[1] - 1)], axis=-1)
    chosen = set()
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f'Chart {chart_id}: island needs a list of [u, v] atlas pixels')
    for s in seeds:
        su, sv = (float(v) for v in s)
        p0, p1, p2 = pix[:, 0], pix[:, 1], pix[:, 2]
        d = (p1[:, 1] - p2[:, 1]) * (p0[:, 0] - p2[:, 0]) + (p2[:, 0] - p1[:, 0]) * (p0[:, 1] - p2[:, 1])
        with np.errstate(divide='ignore', invalid='ignore'):
            w0 = ((p1[:, 1] - p2[:, 1]) * (su - p2[:, 0]) + (p2[:, 0] - p1[:, 0]) * (sv - p2[:, 1])) / d
            w1 = ((p2[:, 1] - p0[:, 1]) * (su - p2[:, 0]) + (p0[:, 0] - p2[:, 0]) * (sv - p2[:, 1])) / d
        hit = np.flatnonzero((w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1))
        if not len(hit):
            raise ValueError(f'Chart {chart_id}: island seed {s} is not on any candidate triangle')
        chosen.update(roots[hit].tolist())
    keep = np.zeros_like(candidates)
    keep[idx[np.isin(roots, list(chosen))]] = True
    return keep


def chart_frames(design):
    """Per chart [mode, origin_u, origin_v, a, b, c, d]: design (x, y) = M (atlas pixel - origin).

    A chart with a "frame" is evaluated on the atlas itself: its shapes stay straight lines in the original UV,
    as a painter working on the unwrapped map draws them.  The frame says where design (0, 0) sits in atlas
    pixels (top-left origin, texel centres at integers) and which atlas displacement one metre of design x and
    one metre of design y make.  Fit it to the island with uv_frame.py.  Charts without a frame keep the world
    axes, which bend straight UV edges wherever the unwrap follows a curved surface.
    """
    frames = np.zeros((len(design['charts']), 7), np.float64)
    for index, chart in enumerate(design['charts']):
        frame = chart.get('frame')
        if frame is None:
            continue
        if not isinstance(frame, dict) or set(frame) - {'origin', 'x', 'y', 'note'} or not {'origin', 'x', 'y'} <= set(frame):
            raise ValueError(f'Chart {chart["id"]}: frame needs origin, x and y (atlas pixels; x and y per metre)')
        o, ex, ey = (point(frame[k], f'{chart["id"]} frame {k}') for k in ('origin', 'x', 'y'))
        det = ex[0] * ey[1] - ex[1] * ey[0]
        if not abs(det) > 1e-9:
            raise ValueError(f'Chart {chart["id"]}: frame x and y must not be parallel')
        # Inverse of [[ex.u, ey.u], [ex.v, ey.v]] maps an atlas displacement back to metres.
        frames[index] = 1, o[0], o[1], ey[1] / det, -ey[0] / det, -ex[1] / det, ex[0] / det
    return frames


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
            holes = item.get('holes', [])
            if holes:
                # Even-odd fill: walk out and back along the same bridge from the outer ring's first point to each hole,
                # so the two bridge edges cancel and only the rings count.
                if kind != 'polygon' or not isinstance(holes, list):
                    raise ValueError(f'{label}: holes apply to polygons (a list of point rings)')
                outer = pts + [pts[0]]
                for ring in holes:
                    ring = [point(q, f'{label} hole point') for q in ring]
                    if len(ring) < 3:
                        raise ValueError(f'{label}: a hole needs at least 3 points')
                    outer += ring + [ring[0], pts[0]]
                pts = outer
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
        fill_meta, fill_values, boxes = [[0, 0, 0, 0]], [[0.] * 63], [[1e30, 1e30, -1e30, -1e30]]
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
    if fv[16] > 0:
        dx, dy = fv[19] - fv[17], fv[20] - fv[18]
        r = min(1., max(0., ((x - fv[17]) * dx + (y - fv[18]) * dy) / (dx * dx + dy * dy)))
        n = int(fv[16])
        f = fv[47 + 2 * (n - 1)]
        if r <= fv[46]:
            f = fv[47]
        else:
            for k in range(n - 1):
                t0, t1 = fv[46 + 2 * k], fv[48 + 2 * k]
                if r <= t1:
                    w = (r - t0) / (t1 - t0) if t1 > t0 else 1.
                    f = fv[47 + 2 * k] * (1 - w) + fv[49 + 2 * k] * w
                    break
        for c in range(3):
            out[c] = min(255., out[c] * f)
    kind = fm[0]
    if kind == 0:
        return
    upper = 0
    l0 = l1 = l2 = 0.
    cell, angle = fv[11], fv[13]
    if fv[62] > 0:
        dx, dy = fv[60] - fv[58], fv[61] - fv[59]
        side = dx * (y - fv[59]) - dy * (x - fv[58])
        if side > 0:
            d2 = dx * dx + dy * dy
            t = ((x - fv[58]) * dx + (y - fv[59]) * dy) / d2
            fx, fy = fv[58] + t * dx, fv[59] + t * dy
            x, y = 2 * fx - x, 2 * fy - y
    ca, sa = math.cos(-angle), math.sin(-angle)
    qx, qy = x - fv[32], y - fv[33]
    px, py = (qx * ca - qy * sa) / cell, (qx * sa + qy * ca) / cell
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
        tint = 0
        if fv[15] > 0:
            tint = 1
            pick = (_hash(i, j, upper, fm[1]) + 1.) * .5
            k = fv[34 + int(fv[15]) - 1]
            for n in range(int(fv[15])):
                if pick <= fv[40 + n]:
                    k = fv[34 + n]
                    break
        if l0 < fv[31] or l1 < fv[31] or l2 < fv[31]:
            k = 1.
        if fv[24] > 0:
            dx, dy = fv[27] - fv[25], fv[28] - fv[26]
            r = min(1., max(0., ((x - fv[25]) * dx + (y - fv[26]) * dy) / (dx * dx + dy * dy)))
            k = 1 + (k - 1) * (fv[29] * (1 - r) + fv[30] * r)
        for c in range(3):
            if tint and k > 1:
                out[c] = min(255., out[c] + (255. - out[c]) * (k - 1))
            else:
                out[c] = min(255., max(0., out[c] * k))
        return
    # Halftone scale from the mark's own centre, so every mark keeps one size.
    gx, gy = cx * cell, cy * cell
    ux = gx * math.cos(angle) - gy * math.sin(angle) + fv[32]
    uy = gx * math.sin(angle) + gy * math.cos(angle) + fv[33]
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
def _used(uvs, width, height, used):
    """Mark every atlas texel that any triangle of the model samples (with the painter's 0.75 px margin)."""
    for tri in range(uvs.shape[0]):
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
                a = ((p[1, 1] - p[2, 1]) * (xx - p[2, 0]) + (p[2, 0] - p[1, 0]) * (yy - p[2, 1])) / den
                b = ((p[2, 1] - p[0, 1]) * (xx - p[2, 0]) + (p[0, 0] - p[2, 0]) * (yy - p[2, 1])) / den
                if min(a * scale[0], b * scale[1], (1 - a - b) * scale[2]) >= -.75:
                    used[yy, xx] = True
    return 0


def same_texture_triangles(design, geometry):
    """Triangles whose material samples the colour texture of the materials the charts paint (all if unknown)."""
    names, resources, ids = (geometry.get(k) for k in ('material_names', 'material_resources', 'material_ids'))
    count = len(geometry['uvs'])
    if names is None or resources is None or ids is None:
        return np.ones(count, bool)
    patterns = [p for chart in design['charts'] for p in chart.get('materials', ['*'])] or ['*']
    colour = []
    for res in resources:
        try:
            slots = json.loads(str(res))
        except (TypeError, ValueError):
            slots = []
        colour.append(slots[0] if slots else None)
    target = {colour[i] for i, n in enumerate(names) if any(fnmatch.fnmatchcase(str(n), p) for p in patterns) and colour[i]}
    if not target:
        return np.ones(count, bool)
    keep = np.array([c in target for c in colour])
    return keep[np.asarray(ids)]


def helper_triangles(geometry, outlier=8.):
    """Helper boxes and caps whose UVs span the whole atlas (J-10C `tail` holds a 10 cm cube with 0-1 UVs on every
    face).  They sample every texel at about 150 times the skin's texel density and are not a paintable surface.
    Counted as used they stop bleed everywhere; left in a chart, every island seed lands on them (their triangles
    cover the whole atlas), the first chart takes them, and their top priority repaints every texel of the atlas
    from that one chart.  A triangle is a helper when its texels per metre exceed `outlier` times the
    area-weighted median of the triangles sampling the same colour map."""
    uv = np.asarray(geometry['uvs'], np.float64); xyz = np.asarray(geometry['triangles'], np.float64)
    e1, e2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    uv_area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
    surface = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1) / 2
    density = np.sqrt(uv_area / np.maximum(surface, 1e-12))
    group = np.zeros(len(uv), np.int64)
    names, resources, ids = (geometry.get(k) for k in ('material_names', 'material_resources', 'material_ids'))
    if names is not None and resources is not None and ids is not None:
        colour = []
        for res in resources:
            try:
                slots = json.loads(str(res))
            except (TypeError, ValueError):
                slots = []
            colour.append(slots[0] if slots else None)
        keys = {c: k for k, c in enumerate(dict.fromkeys(colour))}
        group = np.array([keys[c] for c in colour])[np.asarray(ids)]
    helper = np.zeros(len(uv), bool)
    for g in np.unique(group):
        idx = np.flatnonzero((group == g) & (surface > 1e-12))
        if idx.size < 3:
            continue
        order = idx[np.argsort(density[idx])]
        weight = np.cumsum(surface[order]); weight /= weight[-1]
        median = density[order][min(np.searchsorted(weight, .5), order.size - 1)]
        if median > 0:
            helper[idx[density[idx] > outlier * median]] = True
    return helper


def sampling_triangles(design, geometry, outlier=8.):
    """same_texture_triangles minus helper boxes (helper_triangles): the texels a model really samples."""
    return same_texture_triangles(design, geometry) & ~helper_triangles(geometry, outlier)


def bleed(layer, used, steps):
    """Extend a layer's colour into atlas texels no triangle uses, so filtering at island edges never mixes in
    whatever lies outside the island (a dark rim along every UV seam otherwise).  Texels of other islands stay put."""
    if steps <= 0:
        return layer
    alpha = layer[:, :, 3] > 0
    if not alpha.any():
        return layer
    ys, xs = np.nonzero(alpha)
    y0, y1, x0, x1 = max(ys.min() - steps, 0), min(ys.max() + steps + 1, layer.shape[0]), max(xs.min() - steps, 0), min(xs.max() + steps + 1, layer.shape[1])
    sub = layer[y0:y1, x0:x1].copy()
    free = ~used[y0:y1, x0:x1]
    for _ in range(steps):
        filled = sub[:, :, 3] > 0
        grow = free & ~filled
        best = np.zeros_like(sub)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            src = np.roll(np.roll(sub, dy, axis=0), dx, axis=1)
            take = grow & (src[:, :, 3] > best[:, :, 3])
            best[take] = src[take]
        sub[grow & (best[:, :, 3] > 0)] = best[grow & (best[:, :, 3] > 0)]
    out = layer.copy()
    out[y0:y1, x0:x1] = sub
    return out


@njit(cache=True)
def _coords(xyz, px, py, axes, frames, chart):
    """Design coordinates of one sample: world axes, or a linear frame on the atlas pixel itself."""
    if frames[chart, 0] > 0:
        du, dv = px - frames[chart, 1], py - frames[chart, 2]
        return du * frames[chart, 3] + dv * frames[chart, 4], du * frames[chart, 5] + dv * frames[chart, 6]
    return _design(xyz, axes, chart)


@njit(cache=True)
def _paint(world, uvs, assignment, facing, axes, frames, protect, meta, floats, pts, arc, fill_meta, fill_values, boxes,
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
            u, v = _coords(xyz, p[k, 0], p[k, 1], axes, frames, chart)
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
                        u, v = _coords(xyz, ox, oy, axes, frames, chart)
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


FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'


def resolve_font(value, design_dir=None):
    """Font path as written, relative to the design file, or a file name bundled in the Skill's assets/fonts."""
    value = value or os.environ.get('WT_SKIN_FONT', 'C:/Windows/Fonts/bahnschrift.ttf')
    path = Path(value)
    candidates = [path] if path.is_absolute() else [*([Path(design_dir) / path] if design_dir else []), FONT_DIR / path, path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(f'Font file not found: {value} (looked beside the design and in {FONT_DIR})')


def render_text(spec, palette, px_per_m, design_dir=None):
    """Rasterise a text placement to straight RGBA; returns (array, width_m, height_m)."""
    from PIL import ImageDraw, ImageFont
    text = spec.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('text placements need nonempty text')
    height = float(spec.get('height', 0))
    if not 0 < height <= 10:
        raise ValueError('text height must be 0-10 m (cap height)')
    font_path = resolve_font(spec.get('font'), design_dir)
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
                rgba, width, height = render_text(spec, palette, px_per_m, design_dir)
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
def _paint_image(world, uvs, assignment, facing, axes, frames, protect, chart, img, center, size, angle, flip, opacity,
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
            u, v = _coords(xyz, uvs[tri, k, 0] * (width - 1), (1 - uvs[tri, k, 1]) * (height - 1), axes, frames, chart)
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
                        u, v = _coords(xyz, ox, oy, axes, frames, chart)
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
            if item.get('holes'):
                rings = [item['points']] + item['holes']
                d = ' '.join('M ' + ' L '.join(f'{x:.5f},{y:.5f}' for x, y in ring) + ' Z' for ring in rings)
                group.append(f'    <path id="{ident}" fill="{hex_color}" fill-rule="evenodd"{attr} d="{d}"/>')
                continue
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
    assignment, axes, facing, chart_counts, warnings = select_charts(design, geometry, size)
    frames = chart_frames(design)
    items = compile_items(design, palette)
    layer_count = len(design['layers'])
    layers = np.zeros((layer_count, size[1], size[0], 4), np.uint8)
    best = np.full((size[1], size[0]), -1e30, np.float32)
    hits = np.zeros(len(items['labels']), np.int64)
    _paint(np.ascontiguousarray(geometry['triangles'], np.float64), np.ascontiguousarray(geometry['uvs'], np.float64),
           assignment, facing, axes, frames, protect, items['meta'], items['floats'], items['points'], items['lengths'],
           items['fill_meta'], items['fill_values'], items['boxes'], layer_count, ss, size[0], size[1], layers, best, hits)
    raster_layers = compile_images(design, palette, design_path.parent, float(design.get('text_pixels_per_metre', 400)))
    image_records = []
    world64 = np.ascontiguousarray(geometry['triangles'], np.float64)
    uv64 = np.ascontiguousarray(geometry['uvs'], np.float64)
    for layer_index, placements in raster_layers:
        buffer = np.zeros((size[1], size[0], 4), np.float32)
        for placement in placements:
            covered = _paint_image(world64, uv64, assignment, facing, axes, frames, protect, placement['chart'], placement['image'],
                                   placement['center'], placement['size'], placement['angle'], placement['flip'],
                                   placement['opacity'], placement['fade'], placement['clip'], ss, size[0], size[1], buffer)
            image_records.append(dict(id=placement['id'], layer=design['layers'][layer_index]['name'], source=placement['source'],
                                      size_m=[round(float(v), 4) for v in placement['size']],
                                      source_pixels_per_m=placement['pixels_per_m'], sample_hits=int(covered)))
        alpha = buffer[:, :, 3]
        straight = np.where(alpha[:, :, None] > 0, buffer[:, :, :3] / np.maximum(alpha[:, :, None], 1e-6), 0)
        layers[layer_index, :, :, :3] = np.clip(straight * 255 + .5, 0, 255).astype(np.uint8)
        layers[layer_index, :, :, 3] = np.clip(alpha * 255 + .5, 0, 255).astype(np.uint8)
    bleed_px = int(design.get('bleed_px', 4))
    if not 0 <= bleed_px <= 16:
        raise ValueError('bleed_px must be 0-16 atlas pixels')
    if bleed_px:
        # Texels count as taken only when a triangle samples this same colour map: glass, cockpit interior and
        # other materials may overlap the atlas area but read other textures.  Helper boxes with whole-atlas UVs
        # do not count either (sampling_triangles).
        used = np.zeros((size[1], size[0]), np.bool_)
        _used(uv64[sampling_triangles(design, geometry)], size[0], size[1], used)
        for index in range(layer_count):
            layers[index] = bleed(layers[index], used, bleed_px)
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
