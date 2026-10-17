#!/usr/bin/env python3
"""Prepare original-UV geometry, render content-bound guides, and bake overlays.

Requires NumPy, Pillow, Numba. Layout rendering approximates diffuse light, not
the game's material shader. Original UV coordinates are never re-unwrapped.
"""
from __future__ import annotations
import argparse
from collections import OrderedDict
import contextlib
import fnmatch
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import zipfile
import numpy as np
import tempfile
# Keep Numba's on-disk cache out of the Skill folder (and any installed copy).
os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'war-thunder-user-skins-numba'))
from numba import njit
from PIL import Image
from artifact_io import ArtifactError, ArtifactTransaction
from inspect_skins import open_rgba, write_json

GUIDE_SCHEMA = 2
CAMERA_KEYS = ('basis', 'center', 'scale', 'width', 'height')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_camera(meta):
    basis, center = np.asarray(meta['basis'], dtype=np.float32), np.asarray(meta['center'], dtype=np.float32)
    scale, width, height = float(meta['scale']), meta['width'], meta['height']
    if basis.shape != (3, 3) or not np.isfinite(basis).all() or not np.allclose(basis @ basis.T, np.eye(3), atol=1e-5, rtol=0):
        raise ValueError('Camera basis must be a finite orthonormal 3x3 matrix')
    if center.shape != (2,) or not np.isfinite(center).all():
        raise ValueError('Camera center must contain two finite numbers')
    if not math.isfinite(scale) or scale <= 0 or scale > np.finfo(np.float32).max:
        raise ValueError('Camera scale must be finite and positive')
    if (isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, (int, np.integer))
            or not isinstance(height, (int, np.integer)) or not 1 <= width <= 4096 or not 1 <= height <= 4096):
        raise ValueError('Camera dimensions must be integers in 1..4096')
    return np.ascontiguousarray(basis), np.ascontiguousarray(center), scale, int(width), int(height)


def camera_fingerprint(meta):
    basis, center, scale, width, height = validate_camera(meta)
    normalized = dict(basis=basis.astype(float).tolist(), center=center.astype(float).tolist(), scale=scale, width=width, height=height)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_geometry_arrays(world, uvs, *, allow_repeat_uv=False):
    world, uvs = np.asarray(world), np.asarray(uvs)
    if world.ndim != 3 or world.shape[1:] != (3, 3) or not 0 < len(world) <= 10_000_000:
        raise ValueError('Geometry triangles must have shape (N,3,3), N > 0')
    if uvs.shape != (len(world), 3, 2) or world.dtype.kind not in 'fiu' or uvs.dtype.kind not in 'fiu':
        raise ValueError('Geometry UVs must be numeric shape (N,3,2) matching triangles')
    if not np.isfinite(world).all() or not np.isfinite(uvs).all():
        raise ValueError('Geometry contains nonfinite coordinates')
    if not allow_repeat_uv and (np.any(uvs < 0) or np.any(uvs > 1)):
        raise ValueError('UVs outside 0..1 are unsupported; repeating UVs require an explicit future contract')
    area = np.linalg.norm(np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0]), axis=1)
    if not np.any(area > 1e-10):
        raise ValueError('Geometry contains only degenerate world triangles')
    world, uvs = np.ascontiguousarray(world, dtype=np.float32), np.ascontiguousarray(uvs, dtype=np.float32)
    if not np.isfinite(world).all() or not np.isfinite(uvs).all():
        raise ValueError('Geometry exceeds finite float32 coordinates')
    return world, uvs


def _integer_ids(array, count, limit, name):
    array = np.asarray(array)
    if array.shape != (count,) or array.dtype.kind not in 'iu' or limit <= 0 or np.any(array < 0) or np.any(array >= limit):
        raise ValueError(f'{name} must contain one valid integer index per triangle')
    return np.ascontiguousarray(array, dtype=np.int32)


def _check_npz_size(path):
    with zipfile.ZipFile(path) as archive:
        if sum(member.file_size for member in archive.infolist()) > 1024 ** 3:
            raise ValueError('NPZ exceeds the supported uncompressed size')


def load_geometry(path, *, allow_repeat_uv=False):
    path = Path(path).resolve()
    raw = path.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    _check_npz_size(io.BytesIO(raw))
    with np.load(io.BytesIO(raw), allow_pickle=False) as data:
        world, uvs = validate_geometry_arrays(data['triangles'], data['uvs'], allow_repeat_uv=allow_repeat_uv)
        names = np.asarray(data['names'])
        if names.ndim != 1 or not len(names) or names.dtype.kind not in 'US':
            raise ValueError('Geometry names must be a nonempty string array')
        result = dict(triangles=world, uvs=uvs, names=names.copy(), node_ids=_integer_ids(data['node_ids'], len(world), len(names), 'node_ids'))
        if 'material_ids' in data:
            names = np.asarray(data['material_names']); resources = np.asarray(data['material_resources'])
            if names.ndim != 1 or names.dtype.kind not in 'US' or resources.shape != names.shape or resources.dtype.kind not in 'US':
                raise ValueError('Material names/resources must have one string per material')
            result.update(material_ids=_integer_ids(data['material_ids'], len(world), len(names), 'material_ids'),
                          material_names=names.copy(), material_resources=resources.copy())
    if sha256_file(path) != fingerprint:
        raise ValueError('Geometry changed while being read; retry with a stable input')
    result['_sha256'] = fingerprint
    return result


def paint_image(path):
    path = Path(path)
    if path.suffix.lower() in {'.dds', '.tga'}:
        return open_rgba(path)[0]
    if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}:
        raise ValueError('Unsupported paint image format')
    with Image.open(path) as image:
        if image.width * image.height > 8192 * 8192:
            raise ValueError('Paint image exceeds the validated pixel limit')
        image.load()
        return image.convert('RGBA')


def paint_snapshot(path):
    """Existing DDS/TGA decoder uses paths; verify both sides of its read."""
    fingerprint = sha256_file(path)
    image = paint_image(path)
    if sha256_file(path) != fingerprint:
        image.close()
        raise ValueError(f'Paint input changed while being decoded: {path}')
    return image, fingerprint


def verify_input_snapshots(snapshots):
    for path, expected in snapshots.items():
        if sha256_file(path) != expected:
            raise ValueError(f'Input changed before output commit: {path}')


def resolve_asset_tools(explicit=None, project_hint=None):
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
    elif os.environ.get('WT_ASSET_TOOLS'):
        candidate = Path(os.environ['WT_ASSET_TOOLS']).expanduser().resolve()
    else:
        candidate = None
        starts = [Path(project_hint).resolve()] if project_hint is not None else []
        starts.append(Path(__file__).resolve())
        for start in starts:
            for parent in (start, *start.parents):
                settings = parent / '.skin-workshop.json'
                if settings.is_file():
                    value = json.loads(settings.read_text(encoding='utf-8')).get('tools', {}).get('asset_decoder')
                    if value:
                        path = Path(value).expanduser()
                        candidate = path.resolve() if path.is_absolute() else (parent / path).resolve()
                        break
            if candidate is not None:
                break
        if candidate is None:
            raise ValueError('Configure --tools, WT_ASSET_TOOLS, or project tools.asset_decoder')
    if not (candidate / 'wt_assets.py').is_file() or not (candidate / 'dae_backend.py').is_file():
        raise ValueError(f'Resource decoder is unavailable at {candidate}')
    return candidate


def prepare(game, vehicle, resource, output, tools=None, excluded=()):
    game, output = Path(game).resolve(), Path(output).resolve()
    tools = resolve_asset_tools(tools, output)
    sys.path.insert(0, str(tools))
    from wt_assets import locate
    from dae_backend import load_model
    matches = locate(game, vehicle)
    packs = [Path(e['pack']).resolve() for e in matches['matches'] if e['name'] == vehicle and e['class_id'] == 0xB4B7D9C4]
    if not packs:
        raise ValueError(f'No dynamic model {vehicle!r}')
    descriptors = [game / 'patch/content/base/res/dynModelDesc.bin', game / 'content/base/res/dynModelDesc.bin']
    target, record, log_file = output / 'geometry.npz', output / 'geometry.json', output / 'geometry-decode.log'
    inputs = [packs[0], tools / 'wt_assets.py', tools / 'dae_backend.py', *[p for p in descriptors if p.exists()]]
    with ArtifactTransaction([target, record, log_file], inputs=inputs, label='prepare-geometry', failure_directory=output / '.artifact-failures') as tx:
        snapshots = {path: sha256_file(path) for path in inputs}
        with tx.stage(log_file).open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
            model, _ = load_model(packs[0], vehicle, 0, descriptors)
        selected = [m for m in model.materials or [] if m.getTextureSlots() and m.getTextureSlots()[0] and fnmatch.fnmatchcase(m.getTextureSlots()[0], resource)]
        material_names = [m.getName() for m in selected]
        material_resources = [json.dumps(list(m.getTextureSlots()), ensure_ascii=False) for m in selected]
        material_index = {name: index for index, name in enumerate(material_names)}
        vertices, uvs, nodes, names, materials = [], [], [], [], []
        for obj in model:
            if any(fnmatch.fnmatchcase(obj.name, pattern) for pattern in excluded) or not set(obj.materials.values()) & set(material_names):
                continue
            bone = model.skeleton.getNodeByName(obj.name) if model.skeleton is not None and not obj.skinned else None
            name_id, count, current, cache = len(names), 0, None, {}
            for index, face in enumerate(obj.faces):
                if index in obj.materials:
                    current = obj.materials[index]
                if current not in material_index:
                    continue
                if len(face) != 3:
                    raise ValueError('Decoder returned a non-triangular face')
                points, coords = [], []
                for vertex_id in face:
                    if vertex_id not in cache:
                        p, uv = model.getVertex(vertex_id, parentBone=bone), model.getUV(vertex_id)
                        cache[vertex_id] = ((float(p[0]), float(p[1]), -float(p[2])), (float(uv[0]), float(uv[1])))
                    p, uv = cache[vertex_id]; points.append(p); coords.append(uv)
                vertices.append(points); uvs.append(coords); nodes.append(name_id); materials.append(material_index[current]); count += 1
            if count:
                names.append(obj.name)
        points, coords = validate_geometry_arrays(np.asarray(vertices), np.asarray(uvs))
        np.savez_compressed(tx.stage(target), triangles=points, uvs=coords, node_ids=np.asarray(nodes, dtype=np.int32), names=np.asarray(names),
                            material_ids=np.asarray(materials, dtype=np.int32), material_names=np.asarray(material_names), material_resources=np.asarray(material_resources))
        meta = dict(schema_version=2, vehicle=vehicle, resource=resource, source_pack=str(packs[0]), geometry_sha256=sha256_file(tx.stage(target)),
                    triangles=len(points), nodes=len(names), coordinates='Native X/Y, reflected Z; original UV; static assembly transforms applied.',
                    selected_materials=material_names, material_resources=[json.loads(value) for value in material_resources],
                    excluded_node_patterns=list(excluded), layout_only=True)
        write_json(tx.stage(record), meta)
        verify_input_snapshots(snapshots)
        tx.commit()
    return {'geometry': str(target), **meta}


def camera_basis(view):
    axes = {'left': ([-1, 0, 0], [0, 1, 0], [0, 0, -1]), 'right': ([1, 0, 0], [0, 1, 0], [0, 0, 1]),
            'top': ([0, 0, 1], [1, 0, 0], [0, 1, 0]), 'bottom': ([0, 0, -1], [1, 0, 0], [0, -1, 0]),
            'front': ([0, 0, -1], [0, 1, 0], [1, 0, 0]), 'rear': ([0, 0, 1], [0, 1, 0], [-1, 0, 0])}
    if view == 'iso':
        eye = np.array([1.0, .65, 1.0]); eye /= np.linalg.norm(eye)
        right = np.cross(np.array([0., 1., 0.]), eye); right /= np.linalg.norm(right)
        return np.stack((right, np.cross(eye, right), eye)).astype(np.float32)
    return np.asarray(axes[view], dtype=np.float32)


def screen_vertices(triangles, basis, width, height):
    basis, _, _, width, height = validate_camera(dict(basis=basis, center=[0, 0], scale=1, width=width, height=height))
    triangles = np.asarray(triangles, dtype=np.float32)
    if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError('Screen geometry must have finite shape (N,3,3)')
    projected = triangles @ basis.T
    low, high = projected[:, :, :2].min(axis=(0, 1)), projected[:, :, :2].max(axis=(0, 1))
    center = (low + high) * .5
    scale = min(width * .88 / max(float(high[0] - low[0]), 1e-6), height * .82 / max(float(high[1] - low[1]), 1e-6))
    screen = projected.copy()
    screen[:, :, 0] = (projected[:, :, 0] - center[0]) * scale + width * .5
    screen[:, :, 1] = (center[1] - projected[:, :, 1]) * scale + height * .5
    return screen.astype(np.float32), dict(basis=basis.tolist(), center=center.tolist(), scale=scale, width=width, height=height)


@njit(cache=True)
def sample_rgba(texture, u, v):
    x, y = min(texture.shape[1] - 1, max(0., u * (texture.shape[1] - 1))), min(texture.shape[0] - 1, max(0., (1 - v) * (texture.shape[0] - 1)))
    x0, y0 = int(x), int(y); x1, y1 = min(x0 + 1, texture.shape[1] - 1), min(y0 + 1, texture.shape[0] - 1)
    dx, dy = x - x0, y - y0
    result = np.empty(4, dtype=np.float32)
    for c in range(4):
        result[c] = (texture[y0, x0, c] * (1 - dx) + texture[y0, x1, c] * dx) * (1 - dy) + (texture[y1, x0, c] * (1 - dx) + texture[y1, x1, c] * dx) * dy
    return result


@njit(cache=True)
def _rasterize(screen, world, uvs, texture, width, height, handedness=1.):
    frame = np.empty((height, width, 3), dtype=np.uint8); frame[:] = 238
    depth = np.full((height, width), -np.inf, dtype=np.float32); owners = np.full((height, width), -1, dtype=np.int32)
    light = np.array([.3, .85, .4], dtype=np.float32); light /= np.sqrt((light * light).sum())
    for i in range(len(screen)):
        p = screen[i]
        denom = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if denom * handedness >= -1e-8:
            continue
        xmin, xmax = max(0, int(math.floor(p[:, 0].min()))), min(width - 1, int(math.ceil(p[:, 0].max())))
        ymin, ymax = max(0, int(math.floor(p[:, 1].min()))), min(height - 1, int(math.ceil(p[:, 1].max())))
        n = np.cross(world[i, 1] - world[i, 0], world[i, 2] - world[i, 0]); length = np.sqrt((n * n).sum())
        shade = .7 + .3 * abs((n * light).sum() / length) if length > 1e-10 else 1.
        for y in range(ymin, ymax + 1):
            for x in range(xmin, xmax + 1):
                a = ((p[1, 1] - p[2, 1]) * (x + .5 - p[2, 0]) + (p[2, 0] - p[1, 0]) * (y + .5 - p[2, 1])) / denom
                b = ((p[2, 1] - p[0, 1]) * (x + .5 - p[2, 0]) + (p[0, 0] - p[2, 0]) * (y + .5 - p[2, 1])) / denom
                c = 1 - a - b
                if a < -.0001 or b < -.0001 or c < -.0001:
                    continue
                z = a * p[0, 2] + b * p[1, 2] + c * p[2, 2]
                if z <= depth[y, x]:
                    continue
                u, v = a * uvs[i, 0, 0] + b * uvs[i, 1, 0] + c * uvs[i, 2, 0], a * uvs[i, 0, 1] + b * uvs[i, 1, 1] + c * uvs[i, 2, 1]
                color = sample_rgba(texture, u, v)
                for channel in range(3):
                    frame[y, x, channel] = min(255, max(0, int(color[channel] * shade)))
                depth[y, x], owners[y, x] = z, i
    return frame, depth, owners


def rasterize(screen, world, uvs, texture, width, height, handedness=1.):
    world, uvs = validate_geometry_arrays(world, uvs)
    screen, texture = np.asarray(screen), np.asarray(texture)
    if screen.shape != world.shape or screen.dtype.kind not in 'fiu' or not np.isfinite(screen).all():
        raise ValueError('Screen triangles must match finite world geometry')
    if texture.ndim != 3 or texture.shape[2] != 4 or texture.dtype != np.uint8 or not texture.shape[0] or not texture.shape[1]:
        raise ValueError('Texture must be a nonempty uint8 RGBA array')
    validate_camera(dict(basis=np.eye(3), center=[0, 0], scale=1, width=width, height=height))
    if not math.isfinite(float(handedness)) or not math.isclose(abs(handedness), 1., abs_tol=1e-5):
        raise ValueError('Camera handedness must be +1 or -1')
    screen = np.ascontiguousarray(screen, dtype=np.float32)
    if not np.isfinite(screen).all():
        raise ValueError('Screen coordinates exceed float32 range')
    return _rasterize(screen, world, uvs, np.ascontiguousarray(texture), width, height, float(handedness))


def guide_metadata(geometry, meta, depth_file, view, *, depth_hash=None, geometry_hash=None):
    validate_camera(meta)
    return {'schema_version': GUIDE_SCHEMA, 'view': view, 'geometry': str(Path(geometry).resolve()), 'geometry_sha256': geometry_hash or sha256_file(geometry),
            **{key: meta[key] for key in CAMERA_KEYS}, 'camera_sha256': camera_fingerprint(meta), 'depth_file': str(Path(depth_file).resolve()),
            'depth_sha256': depth_hash or sha256_file(depth_file), 'visibility': 'Front-facing triangle owner at each pixel center',
            'layout_only': True, 'shader': 'Approximate diffuse lighting; game material shader is not simulated.'}


def render(geometry, texture_path, views, output, width, height):
    geometry, texture_path, output = Path(geometry).resolve(), Path(texture_path).resolve(), Path(output).resolve()
    views = list(views)
    if not views or len(views) != len(set(views)):
        raise ValueError('Specify at least one distinct view')
    for view in views:
        camera_basis(view)
    outputs = [output / (view + suffix) for view in views for suffix in ('.png', '-mask.png', '-depth.npz', '.json')]
    with ArtifactTransaction(outputs, inputs=[geometry, texture_path], label='render-guides', failure_directory=output / '.artifact-failures') as tx:
        data = load_geometry(geometry); world, uvs = data['triangles'], data['uvs']
        image, texture_hash = paint_snapshot(texture_path)
        with image:
            texture = np.asarray(image).copy()
        snapshots = {geometry: data['_sha256'], texture_path: texture_hash}
        records = []
        for view in views:
            basis = camera_basis(view); screen, meta = screen_vertices(world, basis, width, height)
            frame, depth, owners = rasterize(screen, world, uvs, texture, width, height, float(np.linalg.det(basis)))
            image_file, mask_file, depth_file, guide_file = [output / (view + suffix) for suffix in ('.png', '-mask.png', '-depth.npz', '.json')]
            Image.fromarray(frame).save(tx.stage(image_file)); Image.fromarray(((owners >= 0) * 255).astype(np.uint8)).save(tx.stage(mask_file))
            np.savez_compressed(tx.stage(depth_file), depth=depth, owners=owners, geometry_sha256=np.asarray(data['_sha256']), camera_sha256=np.asarray(camera_fingerprint(meta)))
            write_json(tx.stage(guide_file), guide_metadata(geometry, meta, depth_file, view, depth_hash=sha256_file(tx.stage(depth_file)), geometry_hash=data['_sha256']))
            records.append(dict(view=view, image=str(image_file), covered_pixels=int((owners >= 0).sum())))
        verify_input_snapshots(snapshots)
        tx.commit()
    return dict(views=records, layout_only=True, guide_schema_version=GUIDE_SCHEMA)


def triangle_neighbors(world, node_ids=None):
    neighbors = np.full((len(world), 3), -1, dtype=np.int32)
    normals = np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0]); lengths = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(lengths[:, None], 1e-30)
    edges = {}
    for index, triangle in enumerate(world):
        for edge in range(3):
            a, b = tuple(triangle[edge]), tuple(triangle[(edge + 1) % 3])
            edges.setdefault(tuple(sorted((a, b))), []).append((index, edge, a, b))
    for members in edges.values():
        if len(members) != 2:
            continue
        a, b = members
        if a[2] != b[3] or a[3] != b[2] or float(normals[a[0]] @ normals[b[0]]) < .995:
            continue
        if node_ids is not None and node_ids[a[0]] != node_ids[b[0]]:
            continue
        neighbors[a[0], a[1]], neighbors[b[0], b[1]] = b[0], a[0]
    return neighbors


POLICY = ('Continuous projected UV texel-center query against all front-facing '
          'triangles in the intersecting screen tile; nearest depth at that '
          'exact point, float64 roundoff-only ties; actual visible-pixel '
          'bilinear support retained; no image dilation or depth tolerance.')
TILE_SIZE = 16
MAX_INDEX_ENTRIES = 32_000_000
_INDEX_CACHE = OrderedDict()


@njit(cache=False)
def _bounds_and_counts(screen, handedness, width, height, tile):
    columns, rows = (width + tile - 1) // tile, (height + tile - 1) // tile
    bounds = np.full((len(screen), 4), -1, dtype=np.int32)
    counts = np.zeros(columns * rows, dtype=np.int64)
    for i in range(len(screen)):
        p = screen[i]
        d = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
        if d * handedness >= 0:
            continue
        x0, x1 = max(0, int(math.floor((p[:, 0].min()-1e-7)/tile))), min(columns-1, int(math.floor((p[:, 0].max()+1e-7)/tile)))
        y0, y1 = max(0, int(math.floor((p[:, 1].min()-1e-7)/tile))), min(rows-1, int(math.floor((p[:, 1].max()+1e-7)/tile)))
        if x0 > x1 or y0 > y1:
            continue
        bounds[i, 0], bounds[i, 1], bounds[i, 2], bounds[i, 3] = x0, x1, y0, y1
        for y in range(y0, y1+1):
            for x in range(x0, x1+1):
                counts[y*columns+x] += 1
    return bounds, counts


@njit(cache=False)
def _populate_bins(bounds, offsets, columns):
    entries = np.empty(offsets[-1], dtype=np.int32)
    cursors = offsets[:-1].copy()
    for i in range(len(bounds)):
        x0, x1, y0, y1 = bounds[i]
        if x0 < 0:
            continue
        for y in range(y0, y1+1):
            for x in range(x0, x1+1):
                slot = y*columns+x
                entries[cursors[slot]] = i
                cursors[slot] += 1
    return entries


def visibility_index(world, basis, center, scale, width, height):
    """Content-keyed bounded cache; changing geometry or camera invalidates it."""
    digest = hashlib.sha256()
    for array in (world, basis, center):
        digest.update(np.ascontiguousarray(array).tobytes())
    digest.update(repr((float(scale), int(width), int(height), TILE_SIZE)).encode())
    key = digest.hexdigest()
    if key in _INDEX_CACHE:
        value = _INDEX_CACHE.pop(key)
        _INDEX_CACHE[key] = value
        return value
    # Double precision matters when a screen triangle is much smaller than one
    # framebuffer pixel. Inputs remain the validated original float32 geometry.
    screen = world.astype(np.float64) @ basis.astype(np.float64).T
    screen[:, :, 0] = (screen[:, :, 0]-float(center[0]))*scale+width*.5
    screen[:, :, 1] = (float(center[1])-screen[:, :, 1])*scale+height*.5
    screen = np.ascontiguousarray(screen)
    bounds, counts = _bounds_and_counts(screen, float(np.linalg.det(basis)), width, height, TILE_SIZE)
    total = int(counts.sum())
    if total > MAX_INDEX_ENTRIES:
        raise ValueError(f'Exact visibility index needs {total} entries; limit is {MAX_INDEX_ENTRIES}')
    offsets = np.empty(len(counts)+1, dtype=np.int64)
    offsets[0], offsets[1:] = 0, np.cumsum(counts)
    entries = _populate_bins(bounds, offsets, (width+TILE_SIZE-1)//TILE_SIZE)
    value = dict(key=key, screen=screen, offsets=offsets, entries=entries,
                 columns=(width+TILE_SIZE-1)//TILE_SIZE, tile=TILE_SIZE)
    _INDEX_CACHE[key] = value
    while len(_INDEX_CACHE) > 3:
        _INDEX_CACHE.popitem(last=False)
    return value


@njit(cache=False)
def _point_depth(screen, offsets, entries, columns, tile, sx, sy, source_id=-1, source_z=0., source_a=0., source_b=0., source_c=0.):
    """The nearest actual face at the requested continuous camera coordinate."""
    cell = int(sy)//tile*columns+int(sx)//tile
    # UV pull already proves this source point belongs to its generating face.
    # Re-solving that same skinny face in screen space can lose many digits.
    # Other faces must still prove coverage at the exact continuous point.
    best, owner = (source_z, source_id) if source_id >= 0 else (-np.inf, -1)
    for index in range(offsets[cell], offsets[cell+1]):
        j = entries[index]
        if j == source_id:
            continue
        p = screen[j]
        d = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
        if source_id < 0:
            a = ((p[1, 1]-p[2, 1])*(sx-p[2, 0])+(p[2, 0]-p[1, 0])*(sy-p[2, 1]))/d
            b = ((p[2, 1]-p[0, 1])*(sx-p[2, 0])+(p[0, 0]-p[2, 0])*(sy-p[2, 1]))/d
            c = 1-a-b
        else:
            # The exact query is the source barycentric point, before its x/y
            # are rounded into two scalars. Orientation is affine: evaluate
            # candidate edges at source vertices and combine those results.
            # Identical projected boundaries then agree exactly, including
            # distinct close front/back planes with identical x/y geometry.
            q = screen[source_id]
            a, b, c = 0., 0., 0.
            for k in range(3):
                weight = source_a if k == 0 else (source_b if k == 1 else source_c)
                a += weight*((p[1, 1]-p[2, 1])*(q[k, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(q[k, 1]-p[2, 1]))
                b += weight*((p[2, 1]-p[0, 1])*(q[k, 0]-p[0, 0])+(p[0, 0]-p[2, 0])*(q[k, 1]-p[0, 1]))
                c += weight*((p[0, 1]-p[1, 1])*(q[k, 0]-p[1, 0])+(p[1, 0]-p[0, 0])*(q[k, 1]-p[1, 1]))
            a, b, c = a/d, b/d, c/d
        if a < 0 or b < 0 or c < 0:
            continue
        z = a*p[0, 2]+b*p[1, 2]+c*p[2, 2]
        if z > best or (z == best and (owner < 0 or j < owner)):
            best, owner = z, j
    return best, owner


@njit(cache=False)
def _sample_overlay_premultiplied(overlay, x, y):
    """Bilinear premultiplied RGB/alpha at source pixel-center coordinates."""
    height, width = overlay.shape[:2]
    x, y = min(width-1., max(0., x)), min(height-1., max(0., y))
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    x1, y1 = min(x0+1, width-1), min(y0+1, height-1)
    dx, dy = x-x0, y-y0
    a00, a10 = float(overlay[y0,x0,3])/255., float(overlay[y0,x1,3])/255.
    a01, a11 = float(overlay[y1,x0,3])/255., float(overlay[y1,x1,3])/255.
    top_alpha, bottom_alpha = a00+(a10-a00)*dx, a01+(a11-a01)*dx
    alpha = top_alpha+(bottom_alpha-top_alpha)*dy
    rgb = np.empty(3, dtype=np.float64)
    for channel in range(3):
        p00, p10 = float(overlay[y0,x0,channel])*a00, float(overlay[y0,x1,channel])*a10
        p01, p11 = float(overlay[y1,x0,channel])*a01, float(overlay[y1,x1,channel])*a11
        top, bottom = p00+(p10-p00)*dx, p01+(p11-p01)*dx
        rgb[channel] = top+(bottom-top)*dy
    return rgb[0], rgb[1], rgb[2], alpha


@njit(cache=False)
def _exact_pull(world, uvs, basis, screen, offsets, entries, columns, tile,
                overlay, visible_owners, base, atlas, score, owner, min_facing):
    height, width = atlas.shape[:2]
    view_h, view_w = overlay.shape[:2]
    # Queries, accepted, framebuffer-owner mismatches accepted, true occluded,
    # no continuous coverage, visible samples losing UV score, committed writes.
    counts = np.zeros(7, dtype=np.int64)
    for i in range(len(world)):
        normal = np.cross(world[i, 1]-world[i, 0], world[i, 2]-world[i, 0])
        length = np.sqrt((normal*normal).sum())
        if length < 1e-10:
            continue
        facing = (normal*basis[2]).sum()/length
        if facing < min_facing:
            continue
        p = np.empty((3, 2), dtype=np.float64)
        for k in range(3):
            p[k, 0], p[k, 1] = float(uvs[i, k, 0])*(width-1), (1-float(uvs[i, k, 1]))*(height-1)
        d = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
        if abs(d) < 1e-8:
            continue
        for y in range(max(0, int(math.ceil(p[:, 1].min()))), min(height-1, int(math.floor(p[:, 1].max())))+1):
            for x in range(max(0, int(math.ceil(p[:, 0].min()))), min(width-1, int(math.floor(p[:, 0].max())))+1):
                a = ((p[1, 1]-p[2, 1])*(x-p[2, 0])+(p[2, 0]-p[1, 0])*(y-p[2, 1]))/d
                b = ((p[2, 1]-p[0, 1])*(x-p[2, 0])+(p[0, 0]-p[2, 0])*(y-p[2, 1]))/d
                c = 1-a-b
                if a < 0 or b < 0 or c < 0:
                    continue
                sx = a*screen[i, 0, 0]+b*screen[i, 1, 0]+c*screen[i, 2, 0]
                sy = a*screen[i, 0, 1]+b*screen[i, 1, 1]+c*screen[i, 2, 1]
                z = a*screen[i, 0, 2]+b*screen[i, 1, 2]+c*screen[i, 2, 2]
                px, py = int(math.floor(sx)), int(math.floor(sy))
                if px < 0 or px >= view_w or py < 0 or py >= view_h:
                    continue
                filtered = _sample_overlay_premultiplied(overlay, sx-.5, sy-.5)
                alpha = filtered[3]
                if alpha < .005:
                    continue
                counts[0] += 1
                nearest, nearest_owner = _point_depth(screen, offsets, entries, columns, tile, sx, sy, i, z, a, b, c)
                if nearest_owner < 0:
                    counts[4] += 1
                    continue
                # This is interpolation roundoff, not a scene-scale occlusion
                # allowance. In particular the old 3/scale depth gap is gone.
                magnitude = max(np.abs(screen[i, :, 2]).max(), np.abs(screen[nearest_owner, :, 2]).max(), abs(z), abs(nearest), 2.2250738585072014e-308)
                epsilon = 64*2.220446049250313e-16*magnitude
                if nearest-z > epsilon:
                    counts[3] += 1
                    continue
                counts[1] += 1
                if visible_owners[py, px] != i:
                    counts[2] += 1
                strength = facing*alpha
                if strength <= score[y, x]:
                    counts[5] += 1
                    continue
                score[y, x], owner[y, x] = strength, i
                for channel in range(3):
                    atlas[y, x, channel] = int(filtered[channel]+base[y, x, channel]*(1-alpha))
                counts[6] += 1
    return counts

# Internal JIT diagnostic handle retained for existing regression callers.
_project_overlay = _exact_pull


@njit(cache=True)
def _uv_overlap_mask(uvs, width, height):
    """Detect actual interior overlaps at UV texel centers, not padded boxes.

    This is a lower-bound diagnostic: bilinear footprints can share additional
    texels beyond polygon centers, and no finite atlas can encode those reads
    independently. Adjacent triangle boundaries alone are not overlap evidence.
    """
    occupied = np.zeros((height, width), dtype=np.uint8)
    for triangle in uvs:
        p = np.empty((3, 2), dtype=np.float32)
        for k in range(3):
            p[k, 0], p[k, 1] = triangle[k, 0]*(width-1), (1-triangle[k, 1])*(height-1)
        denominator = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
        if abs(denominator) < 1e-8:
            continue
        for y in range(max(0, int(math.ceil(p[:, 1].min()))), min(height-1, int(math.floor(p[:, 1].max())))+1):
            for x in range(max(0, int(math.ceil(p[:, 0].min()))), min(width-1, int(math.floor(p[:, 0].max())))+1):
                a = ((p[1, 1]-p[2, 1])*(x-p[2, 0])+(p[2, 0]-p[1, 0])*(y-p[2, 1]))/denominator
                b = ((p[2, 1]-p[0, 1])*(x-p[2, 0])+(p[0, 0]-p[2, 0])*(y-p[2, 1]))/denominator
                if a > 1e-5 and b > 1e-5 and 1-a-b > 1e-5:
                    occupied[y, x] = min(2, occupied[y, x]+1)
    return occupied >= 2


@njit(cache=True)
def _bilinear_footprint(screen, uvs, facings, overlay, visible_owners, base, atlas, score, owner, min_facing):
    """Fill only missing pull samples read by actual visible screen samples.

    Never traverse a UV neighborhood or authorise another visibility owner.
    The best weighted sample wins; this cannot create independent shared UVs.
    """
    height, width = atlas.shape[:2]
    qualities = np.zeros((height, width), dtype=np.float32)
    strengths = np.zeros((height, width), dtype=np.float32)
    sources = np.full((height, width), -1, dtype=np.int32)
    competition = np.zeros((height, width), dtype=np.uint8)
    for y in range(overlay.shape[0]):
        for x in range(overlay.shape[1]):
            i = visible_owners[y, x]
            if i < 0 or facings[i] < min_facing or overlay[y, x, 3] < 2:
                continue
            p = screen[i]
            denominator = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
            if abs(denominator) < 1e-8:
                continue
            a = ((p[1, 1]-p[2, 1])*(x+.5-p[2, 0])+(p[2, 0]-p[1, 0])*(y+.5-p[2, 1]))/denominator
            b = ((p[2, 1]-p[0, 1])*(x+.5-p[2, 0])+(p[0, 0]-p[2, 0])*(y+.5-p[2, 1]))/denominator
            c = 1-a-b
            if a < -.0001 or b < -.0001 or c < -.0001:
                continue
            u, v = a*uvs[i, 0, 0]+b*uvs[i, 1, 0]+c*uvs[i, 2, 0], a*uvs[i, 0, 1]+b*uvs[i, 1, 1]+c*uvs[i, 2, 1]
            tx, ty = min(width-1., max(0., u*(width-1))), min(height-1., max(0., (1-v)*(height-1)))
            x0, y0 = int(tx), int(ty)
            x1, y1 = min(x0+1, width-1), min(y0+1, height-1)
            dx, dy, alpha = tx-x0, ty-y0, overlay[y, x, 3]/255.
            strength = facings[i]*alpha
            for yy, xx, weight in ((y0, x0, (1-dx)*(1-dy)), (y0, x1, dx*(1-dy)),
                                   (y1, x0, (1-dx)*dy), (y1, x1, dx*dy)):
                if weight <= 1e-7 or score[yy, xx] > 0:
                    continue
                quality = weight*strength
                if qualities[yy, xx] > 0 and sources[yy, xx] != i:
                    # A competing colour is evidence of downsampling/shared
                    # footprint contention; it is reported, never called a fix.
                    for channel in range(3):
                        candidate = int(overlay[y, x, channel]*alpha + base[yy, xx, channel]*(1-alpha))
                        if abs(candidate-int(atlas[yy, xx, channel])) > 2:
                            competition[yy, xx] = 1
                if quality <= qualities[yy, xx]:
                    continue
                qualities[yy, xx], strengths[yy, xx], sources[yy, xx] = quality, strength, i
                for channel in range(3):
                    atlas[yy, xx, channel] = int(overlay[y, x, channel]*alpha + base[yy, xx, channel]*(1-alpha))
    filled, competed = 0, 0
    for y in range(height):
        for x in range(width):
            if qualities[y, x] > 0:
                score[y, x], owner[y, x] = strengths[y, x], sources[y, x]
                filled += 1
            if competition[y, x]:
                competed += 1
    return filled, competed


def validate_visibility(depth, owners, world_count, shape):
    depth, owners = np.asarray(depth), np.asarray(owners)
    if depth.shape != shape or depth.dtype.kind != 'f' or owners.shape != shape or owners.dtype.kind not in 'iu':
        raise ValueError('Depth/owners must match the camera canvas, with float depth and integer owners')
    if np.any(owners < -1) or np.any(owners >= world_count):
        raise ValueError('Visibility owner contains an out-of-range triangle index')
    covered = owners >= 0
    if not np.isfinite(depth[covered]).all() or not np.all(np.isneginf(depth[~covered])):
        raise ValueError('Depth must be finite on covered pixels and -inf on background')
    depth, owners = np.ascontiguousarray(depth, dtype=np.float32), np.ascontiguousarray(owners, dtype=np.int32)
    if not np.isfinite(depth[covered]).all() or not np.all(np.isneginf(depth[~covered])):
        raise ValueError('Depth exceeds finite float32 coordinates')
    return depth, owners


def project_overlay(world, uvs, basis, center, scale, overlay, depth, base,
                    atlas, score, owner, tolerance, min_facing=.45,
                    visible_owners=None, neighbors=None, diagnostics=None,
                    uv_overlap=None):
    world, uvs = validate_geometry_arrays(world, uvs)
    overlay = np.asarray(overlay)
    if overlay.ndim != 3 or overlay.shape[2] != 4 or overlay.dtype != np.uint8:
        raise ValueError('Overlay must be uint8 RGBA')
    basis, center, scale, width, height = validate_camera(dict(basis=basis, center=center, scale=scale, width=overlay.shape[1], height=overlay.shape[0]))
    if not math.isfinite(float(tolerance)) or tolerance < 0 or not math.isfinite(float(min_facing)) or not 0 <= min_facing <= 1:
        raise ValueError('Tolerance must be finite/nonnegative and minimum facing must be in 0..1')
    if base.ndim != 3 or base.shape[2] != 4 or base.dtype != np.uint8 or atlas.shape != base.shape or atlas.dtype != np.uint8:
        raise ValueError('Base and destination must be equally sized uint8 RGBA arrays')
    if score.shape != base.shape[:2] or score.dtype != np.float32 or not np.isfinite(score).all() or owner.shape != score.shape or owner.dtype != np.int32:
        raise ValueError('Score/owner must be float32/int32 arrays matching the atlas')
    if not all(array.flags.c_contiguous for array in (overlay, base, atlas, score, owner)):
        raise ValueError('Projection buffers must be contiguous')
    index = visibility_index(world, basis, center, scale, width, height)
    screen = index['screen']
    if visible_owners is None:
        _, expected_depth, visible_owners = rasterize(screen, world, uvs, base, width, height, float(np.linalg.det(basis)))
        if depth.shape != expected_depth.shape or not np.allclose(depth, expected_depth, atol=1e-5, rtol=1e-5):
            raise ValueError('Unbound depth does not match the supplied geometry and camera')
    depth, visible_owners = validate_visibility(depth, visible_owners, len(world), (height, width))
    if neighbors is not None and (neighbors.shape != (len(world), 3) or neighbors.dtype != np.int32 or np.any(neighbors < -1) or np.any(neighbors >= len(world))):
        raise ValueError('Triangle adjacency contains invalid indices')
    if diagnostics is not None and not isinstance(diagnostics, dict):
        raise ValueError('Projection diagnostics must be a mutable dict')
    if uv_overlap is not None and (uv_overlap.shape != base.shape[:2] or uv_overlap.dtype != np.bool_):
        raise ValueError('UV overlap diagnostic must match the atlas boolean canvas')
    counts = _exact_pull(world.astype(np.float64), uvs, basis.astype(np.float64), screen, index['offsets'], index['entries'], index['columns'], index['tile'], overlay, visible_owners, base, atlas, score, owner, float(min_facing))
    pull_pixels = int((score > 0).sum())
    normals = np.cross(world[:, 1]-world[:, 0], world[:, 2]-world[:, 0])
    facings = np.ascontiguousarray((normals@basis[2])/np.maximum(np.linalg.norm(normals, axis=1), 1e-30), dtype=np.float32)
    filled, competed = _bilinear_footprint(screen, uvs, facings, overlay, visible_owners, base, atlas, score, owner, float(min_facing))
    if diagnostics is not None:
        if uv_overlap is None:
            uv_overlap = _uv_overlap_mask(uvs, base.shape[1], base.shape[0])
        diagnostics.update(pull_painted_texels=pull_pixels, footprint_filled_texels=int(filled), footprint_color_competition_texels=int(competed), overlapping_uv_center_texels=int(uv_overlap.sum()), painted_overlapping_uv_center_texels=int((uv_overlap & (score > 0)).sum()), shared_uv_diagnostic='Strict triangle-interior texel-center overlap is a lower bound. Bilinear footprints may share more texels; shared reads cannot encode independent artwork.', footprint_policy='Actual visible pixel owner samples only; at most four real bilinear contributors with weight >1e-7; fill only missing pull texels.', exact_visibility=dict(policy=POLICY, index_sha256=index['key'], tile_size=index['tile'], index_entries=len(index['entries']), queried_samples=int(counts[0]), accepted_samples=int(counts[1]), framebuffer_owner_mismatch_accepted_samples=int(counts[2]), true_occluded_samples=int(counts[3]), no_continuous_coverage_samples=int(counts[4]), accepted_losing_uv_score_samples=int(counts[5]), committed_writes=int(counts[6])))
    return int(counts[6])+int(filled)


def bake(geometry, base_path, overlays, output, min_facing):
    geometry, base_path, output = Path(geometry).resolve(), Path(base_path).resolve(), Path(output).resolve()
    specifications, inputs, guide_snapshots = [], [geometry, base_path], {}
    for specification in overlays:
        view_file, overlay_file = (Path(value).resolve() for value in specification.split('=', 1))
        guide_raw = view_file.read_bytes()
        meta = json.loads(guide_raw.decode('utf-8'))
        guide_hash = hashlib.sha256(guide_raw).hexdigest()
        if view_file in guide_snapshots and guide_snapshots[view_file] != guide_hash:
            raise ValueError('Camera guide changed while collecting overlay specifications')
        guide_snapshots[view_file] = guide_hash
        depth_file = Path(meta.get('depth_file', view_file.with_name(view_file.stem + '-depth.npz')))
        depth_file = depth_file.resolve() if depth_file.is_absolute() else (view_file.parent / depth_file).resolve()
        inputs.extend((view_file, overlay_file, depth_file)); specifications.append((view_file, overlay_file, depth_file, meta))
    if not specifications:
        raise ValueError('At least one overlay is required')
    mask_file, receipt_file = output.with_name(output.stem + '-paint-mask.png'), output.with_suffix('.projection.json')
    with ArtifactTransaction([output, mask_file, receipt_file], inputs=inputs, label='bake-overlays', failure_directory=output.parent / '.artifact-failures') as tx:
        data = load_geometry(geometry); world, uvs = data['triangles'], data['uvs']; neighbors = triangle_neighbors(world, data['node_ids'])
        image, base_hash = paint_snapshot(base_path)
        with image:
            base = np.asarray(image).copy()
        snapshots = {**guide_snapshots, geometry: data['_sha256'], base_path: base_hash}
        uv_overlap = _uv_overlap_mask(uvs, base.shape[1], base.shape[0])
        canvas, score, owner = base.copy(), np.zeros(base.shape[:2], dtype=np.float32), np.full(base.shape[:2], -1, dtype=np.int32)
        records, active_pixels = [], 0
        for view_file, overlay_file, depth_file, meta in specifications:
            if meta.get('schema_version') != GUIDE_SCHEMA:
                raise ValueError('Unbound/legacy camera guide: regenerate schema_version 2 guides; historical files remain unchanged')
            if meta.get('geometry_sha256') != data['_sha256']:
                raise ValueError('Guide geometry content does not match; regenerate guides')
            if meta.get('camera_sha256') != camera_fingerprint(meta):
                raise ValueError('Guide camera binding is invalid; regenerate guides')
            depth_raw = depth_file.read_bytes()
            depth_hash = hashlib.sha256(depth_raw).hexdigest()
            if meta.get('depth_sha256') != depth_hash:
                raise ValueError('Guide depth/owner content does not match; regenerate guides')
            basis, center, scale, width, height = validate_camera(meta)
            bitmap, overlay_hash = paint_snapshot(overlay_file)
            with bitmap:
                overlay = np.asarray(bitmap).copy()
            for path, digest in ((depth_file, depth_hash), (overlay_file, overlay_hash)):
                if path in snapshots and snapshots[path] != digest:
                    raise ValueError(f'Input changed while processing overlays: {path}')
                snapshots[path] = digest
            if overlay.shape[:2] != (height, width):
                raise ValueError('Overlay must keep the exact orthographic canvas dimensions')
            _check_npz_size(io.BytesIO(depth_raw))
            with np.load(io.BytesIO(depth_raw), allow_pickle=False) as visibility:
                if str(visibility['geometry_sha256']) != data['_sha256'] or str(visibility['camera_sha256']) != meta['camera_sha256']:
                    raise ValueError('Depth archive belongs to a different geometry/camera')
                depth, visible_owners = validate_visibility(visibility['depth'], visibility['owners'], len(world), (height, width))
            candidate, local_score, local_owner = base.copy(), np.zeros(base.shape[:2], dtype=np.float32), np.full(base.shape[:2], -1, dtype=np.int32)
            active = int((overlay[:, :, 3] >= 2).sum()); active_pixels += active
            diagnostics = {}
            hits = project_overlay(world, uvs, basis, center, scale, overlay, depth, base, candidate, local_score, local_owner, 3.0 / scale, min_facing, visible_owners, neighbors, diagnostics, uv_overlap)
            if active and not hits:
                raise ValueError(f'Nontransparent overlay {overlay_file.name} produced zero UV hits: check visibility, facing, canvas alignment and UV carrier; no output committed')
            wins = local_score > score
            canvas[wins], score[wins], owner[wins] = candidate[wins], local_score[wins], local_owner[wins]
            records.append(dict(view=meta['view'], overlay=str(overlay_file), overlay_sha256=overlay_hash, active_overlay_pixels=active,
                                candidate_writes=int(hits), winning_pixels=int(wins.sum()), sampling=diagnostics))
        painted = int((score > 0).sum())
        if active_pixels and not painted:
            raise ValueError('Nontransparent overlays produced zero UV hits: check visibility, facing, canvas alignment and UV carrier; no output committed')
        Image.fromarray(canvas).save(tx.stage(output)); Image.fromarray(((score > 0) * 255).astype(np.uint8)).save(tx.stage(mask_file))
        meta = dict(schema_version=2, state='no_op' if not active_pixels else 'complete', output=str(output), geometry_sha256=data['_sha256'], painted_pixels=painted,
                    alpha_preserved=bool(np.array_equal(canvas[:, :, 3], base[:, :, 3])), overlays=records,
                    visibility_policy=POLICY,
                    projection_implementation='continuous-point-exact-v3',
                    shared_uv_policy='Highest facing*alpha; overlapping independent designs need review.')
        write_json(tx.stage(receipt_file), meta)
        verify_input_snapshots(snapshots)
        tx.commit()
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__); subs = parser.add_subparsers(dest='command', required=True)
    a = subs.add_parser('prepare'); a.add_argument('--game', type=Path, required=True); a.add_argument('--vehicle', required=True)
    a.add_argument('--resource', required=True); a.add_argument('--tools', type=Path); a.add_argument('--out', type=Path, required=True)
    a.add_argument('--exclude-node', action='append', default=[], help='Exclude a node glob for the chosen display/paint state')
    a = subs.add_parser('render'); a.add_argument('--geometry', type=Path, required=True); a.add_argument('--texture', type=Path, required=True)
    a.add_argument('--view', choices=['left', 'right', 'top', 'bottom', 'front', 'rear', 'iso'], action='append', required=True)
    a.add_argument('--width', type=int, default=1536); a.add_argument('--height', type=int, default=640); a.add_argument('--out', type=Path, required=True)
    a = subs.add_parser('bake'); a.add_argument('--geometry', type=Path, required=True); a.add_argument('--base', type=Path, required=True)
    a.add_argument('--overlay', action='append', required=True, help='camera.json=editor-overlay.png'); a.add_argument('--out', type=Path, required=True)
    a.add_argument('--min-facing', type=float, default=.45, help='Reject edge-on surfaces (0..1)')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.game, args.vehicle, args.resource, args.out, args.tools, args.exclude_node)
        elif args.command == 'render':
            if not 128 <= args.width <= 4096 or not 128 <= args.height <= 4096:
                raise ValueError('View dimensions must be 128..4096')
            result = render(args.geometry, args.texture, args.view, args.out, args.width, args.height)
        else:
            result = bake(args.geometry, args.base, args.overlay, args.out, args.min_facing)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, KeyError, ImportError, zipfile.BadZipFile, ArtifactError) as exc:
        print(f'Surface workflow failed: {exc}', file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
