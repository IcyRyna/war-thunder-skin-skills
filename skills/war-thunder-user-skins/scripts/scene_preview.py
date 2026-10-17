#!/usr/bin/env python3
"""Hash-bound multi-material orthographic scene previews.

The material mode uses an approximate GGX studio model, not the game shader.
R is interpreted as inverted roughness and B as metallicity. Tangent normals
require an explicit per-material convention; the default remains disabled. Glass proxies
are opaque and explicitly reported; this tool does not validate transparency.
Dependencies: Python 3.10+, NumPy, Pillow, Numba.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import os
import tempfile
# Keep Numba's on-disk cache out of the Skill folder (and any installed copy).
os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'war-thunder-user-skins-numba'))
from numba import njit
from numba.typed import List
from PIL import Image

import surface_preview as surface
from artifact_io import ArtifactError, ArtifactTransaction

STANDARD_VIEWS = ('top', 'bottom', 'left', 'right', 'front', 'rear', 'iso', 'reverse-iso')
LIMITATIONS = [
    'Offline orthographic approximation; not the War Thunder shader.',
    'No game environment, transparency, shadowing, extra detail-normal layers or anisotropy simulation.',
    'Packed R=inverted roughness, B=metallicity. Tangent normals are decoded only with explicit normal_convention; target shader channel axes/sign are not inferred.',
    'Opaque material proxies and source alpha do not establish glass or masking correctness.',
    'Full-scene owner IDs belong to this geometry and cannot be used with a subset geometry.',
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding='utf-8-sig') as source:
        return json.load(source)


def bound_file(reference: dict, root: Path, field: str) -> Path:
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        raise ValueError(f'{field} must contain path and sha256')
    path = Path(reference['path']).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=True)
    expected = reference.get('sha256')
    if not isinstance(expected, str) or len(expected) != 64 or file_hash(path) != expected.lower():
        raise ValueError(f'{field} source hash mismatch: {path}')
    if not path.is_file():
        raise ValueError(f'{field} is not a file')
    return path


def finite_vector(value: Any, length: int, field: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (length,) or not np.isfinite(result).all():
        raise ValueError(f'{field} must contain {length} finite numbers')
    return result


def scalar(value: Any, low: float, high: float, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{field} must be a finite number')
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f'{field} must be within {low}..{high}')
    return result


def dimensions(width: Any, height: Any) -> tuple[int, int]:
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int):
        raise ValueError('width and height must be integers')
    if not 16 <= width <= 4096 or not 16 <= height <= 4096:
        raise ValueError('preview dimensions must be within 16..4096')
    return width, height


def texture_dimensions(width: Any, height: Any) -> tuple[int, int]:
    if (isinstance(width, bool) or isinstance(height, bool)
            or not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0):
        raise ValueError('texture dimensions must be positive integers')
    if width * height > 8192 * 8192:
        raise ValueError('texture exceeds pixel limit')
    return width, height


def read_texture(path: Path, expected_sha256: str) -> np.ndarray:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256.lower():
        raise ValueError(f'texture changed before snapshot: {path}')
    with Image.open(BytesIO(raw)) as image:
        texture_dimensions(image.width, image.height)
        image.load()
        return np.array(image.convert('RGBA'), dtype=np.uint8, order='C', copy=True)


def load_scene(path: Path, *, reuse_textures: bool = False) -> dict:
    """Load bound resources; opt in to per-call shared read-only-use snapshots.

    The default preserves independent arrays for explicit texture references.
    Reuse avoids repeated image decoding/allocation, never per-reference source
    validation. Callers opting in must not mutate the shared texture arrays.
    """
    if not isinstance(reuse_textures, bool):
        raise ValueError('reuse_textures must be boolean')
    texture_cache: dict[tuple[Path, str], np.ndarray] = {}
    texture_versions: dict[Path, str] = {}

    def texture_snapshot(texture_path: Path, expected_sha256: str) -> np.ndarray:
        digest = expected_sha256.lower()
        previous = texture_versions.setdefault(texture_path, digest)
        if previous != digest:
            # One source path cannot bind two snapshots in the same scene.
            # Otherwise input_hashes would hide the earlier decoded version.
            raise ValueError(f'conflicting texture snapshots for one resolved path: {texture_path}')
        if not reuse_textures:
            return read_texture(texture_path, expected_sha256)
        key = (texture_path, digest)
        if key not in texture_cache:
            texture_cache[key] = read_texture(texture_path, expected_sha256)
        elif file_hash(texture_path) != key[1]:
            # bound_file already validated this reference. Keep the second
            # snapshot check that read_texture performs after that validation.
            raise ValueError(f'texture changed before snapshot: {texture_path}')
        return texture_cache[key]

    path = path.expanduser().resolve(strict=True)
    scene_bytes = path.read_bytes()
    raw = json.loads(scene_bytes.decode('utf-8-sig'))
    scene_sha256 = hashlib.sha256(scene_bytes).hexdigest()
    if not isinstance(raw, dict) or raw.get('schema_version') != 1:
        raise ValueError('scene schema_version must be 1')
    root = path.parent
    geometry_path = bound_file(raw.get('geometry'), root, 'geometry')
    geometry = surface.load_geometry(geometry_path, allow_repeat_uv=True)
    if geometry['_sha256'] != raw['geometry']['sha256'].lower():
        raise ValueError('geometry changed between scene validation and snapshot')
    if 'material_ids' not in geometry or 'material_names' not in geometry:
        raise ValueError('scene geometry needs per-triangle material_ids and material_names')
    material_ids = geometry['material_ids']
    if material_ids.shape != (len(geometry['triangles']),) or not np.issubdtype(material_ids.dtype, np.integer):
        raise ValueError('material_ids must be an integer per triangle')
    names = [str(name) for name in geometry['material_names']]
    records = raw.get('materials')
    if not isinstance(records, list) or not records or len(records) != len(names):
        raise ValueError('materials must match geometry material_names exactly')
    if sorted(record.get('id', -1) for record in records) != list(range(len(names))):
        raise ValueError('material IDs must be unique and consecutive')
    records = sorted(records, key=lambda item: item['id'])
    colors, packed, normal_textures, normal_codes, normal_strengths, normal_y_signs = [], [], [], [], [], []
    roughness, metallicity, double_sided, repeats = [], [], [], []
    inputs = [path, geometry_path]
    input_hashes = {path: scene_sha256, geometry_path: geometry['_sha256']}
    for index, record in enumerate(records):
        if record.get('name') != names[index]:
            raise ValueError(f'material name mismatch at ID {index}')
        if 'color' in record:
            color_path = bound_file(record['color'], root, f'materials[{index}].color')
            color = texture_snapshot(color_path, record['color']['sha256'])
            inputs.append(color_path)
            input_hashes[color_path] = record['color']['sha256'].lower()
        else:
            constant = finite_vector(record.get('base_color'), 4, f'materials[{index}].base_color')
            if (constant < 0).any() or (constant > 1).any():
                raise ValueError('base_color must use 0..1 RGBA')
            color = np.rint(constant * 255).astype(np.uint8).reshape(1, 1, 4)
        if record.get('packed') is not None:
            packed_path = bound_file(record['packed'], root, f'materials[{index}].packed')
            data = texture_snapshot(packed_path, record['packed']['sha256'])
            # All maps share normalized UVs; each sampler uses its own H/W.
            inputs.append(packed_path)
            input_hashes[packed_path] = record['packed']['sha256'].lower()
        else:
            data = np.zeros((1, 1, 4), dtype=np.uint8)
        convention = record.get('normal_convention', 'none')
        conventions = {'none': 0, 'rg_xy': 1, 'ga_xy': 2, 'ag_xy': 3}
        if convention not in conventions:
            raise ValueError('normal_convention must be none, rg_xy, ga_xy or ag_xy')
        if record.get('normal_texture') is not None:
            normal_path = bound_file(record['normal_texture'], root, f'materials[{index}].normal_texture')
            normal_data = texture_snapshot(normal_path, record['normal_texture']['sha256'])
            inputs.append(normal_path)
            input_hashes[normal_path] = record['normal_texture']['sha256'].lower()
        else:
            normal_data = data
        if convention != 'none' and record.get('normal_texture') is None and record.get('packed') is None:
            raise ValueError('normal_convention needs a hash-bound packed or normal_texture source')
        y_sign = scalar(record.get('normal_y_sign', 1.), -1., 1., 'normal_y_sign')
        if y_sign not in (-1., 1.):
            raise ValueError('normal_y_sign must be exactly -1 or 1')
        normal_textures.append(normal_data)
        normal_codes.append(conventions[convention])
        normal_strengths.append(scalar(record.get('normal_strength', 1.), 0., 4., 'normal_strength'))
        normal_y_signs.append(y_sign)
        roughness.append(scalar(record.get('roughness', .45), .04, 1., 'roughness'))
        metallicity.append(scalar(record.get('metallic', 0.), 0., 1., 'metallic'))
        if not isinstance(record.get('double_sided', False), bool):
            raise ValueError('double_sided must be boolean')
        double_sided.append(record.get('double_sided', False))
        uv_mode = record.get('uv_mode', 'unit')
        if uv_mode not in ('unit', 'repeat'):
            raise ValueError('uv_mode must be unit or repeat')
        selected_uvs = geometry['uvs'][material_ids == index]
        if uv_mode == 'unit' and selected_uvs.size and ((selected_uvs < -1e-6).any() or (selected_uvs > 1 + 1e-6).any()):
            raise ValueError(f'UV outside unit tile for material {index}; explicit repeat sampler required')
        repeats.append(uv_mode == 'repeat')
        colors.append(color)
        packed.append(data)
    if material_ids.min() < 0 or material_ids.max() >= len(records):
        raise ValueError('material_ids reference nonexistent material')
    state = raw.get('display_state')
    if not isinstance(state, dict) or not isinstance(state.get('description'), str):
        raise ValueError('scene must describe its static display_state')
    if state.get('source_ledger') is not None:
        ledger_path = bound_file(state['source_ledger'], root, 'display_state.source_ledger')
        inputs.append(ledger_path)
        input_hashes[ledger_path] = state['source_ledger']['sha256'].lower()
    width, height = dimensions(raw.get('width', 1024), raw.get('height', 1024))
    return dict(raw=raw, path=path, geometry_path=geometry_path, geometry=geometry, inputs=inputs, input_hashes=input_hashes,
                colors=colors, packed=packed, roughness=np.asarray(roughness, np.float32),
                normal_textures=normal_textures, normal_codes=np.asarray(normal_codes, np.int32),
                normal_strengths=np.asarray(normal_strengths, np.float32), normal_y_signs=np.asarray(normal_y_signs, np.float32),
                metallicity=np.asarray(metallicity, np.float32), double_sided=np.asarray(double_sided, np.bool_),
                repeats=np.asarray(repeats, np.bool_), has_packed=np.asarray([record.get('packed') is not None for record in records], np.bool_),
                width=width, height=height)


def basis_from_eye(eye: Any, up: Any = (0, 1, 0)) -> np.ndarray:
    eye = finite_vector(eye, 3, 'eye')
    if np.linalg.norm(eye) < 1e-8:
        raise ValueError('eye vector is zero')
    eye /= np.linalg.norm(eye)
    up = finite_vector(up, 3, 'up')
    right = np.cross(up, eye)
    if np.linalg.norm(right) < 1e-8:
        raise ValueError('eye and up are parallel')
    right /= np.linalg.norm(right)
    return np.asarray([right, np.cross(eye, right), eye], dtype=np.float32)


def select_camera(scene: dict, view: str, camera_path: Path | None = None) -> tuple[np.ndarray, dict, dict[Path, str]]:
    world = scene['geometry']['triangles']
    width, height = scene['width'], scene['height']
    extra_inputs = {}
    if camera_path:
        camera_path = camera_path.resolve(strict=True)
        camera_bytes = camera_path.read_bytes()
        camera = json.loads(camera_bytes.decode('utf-8-sig'))
        extra_inputs[camera_path] = hashlib.sha256(camera_bytes).hexdigest()
    elif view in scene['raw'].get('cameras', {}):
        camera = scene['raw']['cameras'][view]
    elif view in STANDARD_VIEWS:
        basis = basis_from_eye((-1., .65, -1.)) if view == 'reverse-iso' else surface.camera_basis(view)
        return (*surface.screen_vertices(world, basis, width, height), extra_inputs)
    else:
        raise ValueError(f'unknown view {view!r}; provide --camera or named scene camera')
    if not isinstance(camera, dict):
        raise ValueError('camera must be an object')
    if {'basis', 'center', 'scale', 'width', 'height'} <= camera.keys():
        basis, center, scale, width, height = surface.validate_camera(camera)
        dimensions(width, height)
        meta = dict(basis=basis.tolist(), center=center.tolist(), scale=scale, width=width, height=height)
    else:
        basis = basis_from_eye(camera.get('eye'), camera.get('up', (0, 1, 0)))
        width, height = dimensions(camera.get('width', width), camera.get('height', height))
        fitting = world
        selected_names = camera.get('fit_nodes')
        if selected_names is not None:
            if not isinstance(selected_names, list) or not selected_names or not all(isinstance(name, str) for name in selected_names):
                raise ValueError('fit_nodes must be a nonempty list of exact node names')
            actual_names = scene['geometry']['names']
            missing = set(selected_names) - set(actual_names.tolist())
            if missing:
                raise ValueError(f'fit_nodes missing: {sorted(missing)}')
            mask = np.isin(scene['geometry']['node_ids'], np.where(np.isin(actual_names, selected_names))[0])
            fitting = world[mask]
        _, meta = surface.screen_vertices(fitting, basis, width, height)
        if 'zoom' in camera:
            meta['scale'] *= scalar(camera['zoom'], .05, 20., 'camera.zoom')
        if 'target_world' in camera:
            target = finite_vector(camera['target_world'], 3, 'target_world')
            meta['center'] = (target @ basis.T)[:2].tolist()
    surface.validate_camera(meta)
    projected = world @ basis.T
    projected[:, :, 0] = (projected[:, :, 0] - meta['center'][0]) * meta['scale'] + meta['width'] * .5
    projected[:, :, 1] = (meta['center'][1] - projected[:, :, 1]) * meta['scale'] + meta['height'] * .5
    return np.ascontiguousarray(projected, np.float32), meta, extra_inputs


def smooth_normals(world: np.ndarray, node_ids: np.ndarray, material_ids: np.ndarray) -> np.ndarray:
    cross = np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0])
    face = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-10)
    # Never blend separate nodes/materials or opposite shell faces.
    keys = np.column_stack((np.repeat(node_ids, 3), np.repeat(material_ids, 3), np.round(world.reshape(-1, 3), 5)))
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    sums = np.zeros((int(inverse.max()) + 1, 3), np.float32)
    np.add.at(sums, inverse, np.repeat(cross, 3, axis=0))
    normals = sums[inverse].reshape(world.shape)
    normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1e-10)
    sharp = (normals * face[:, None, :]).sum(axis=2) < .65
    normals[sharp] = np.broadcast_to(face[:, None, :], normals.shape)[sharp]
    return np.ascontiguousarray(normals, np.float32)


def tangent_frames(world: np.ndarray, uvs: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Derive original-UV tangents; Gram-Schmidt is applied per shaded pixel."""
    edge1, edge2 = world[:, 1]-world[:, 0], world[:, 2]-world[:, 0]
    delta1, delta2 = uvs[:, 1]-uvs[:, 0], uvs[:, 2]-uvs[:, 0]
    determinant = delta1[:, 0]*delta2[:, 1]-delta2[:, 0]*delta1[:, 1]
    valid = np.abs(determinant) > 1e-12
    tangent, bitangent = np.zeros((len(world), 3), np.float32), np.zeros((len(world), 3), np.float32)
    tangent[valid] = (edge1[valid]*delta2[valid, 1, None]-edge2[valid]*delta1[valid, 1, None])/determinant[valid, None]
    bitangent[valid] = (edge2[valid]*delta1[valid, 0, None]-edge1[valid]*delta2[valid, 0, None])/determinant[valid, None]
    valid &= np.isfinite(tangent).all(axis=1)&np.isfinite(bitangent).all(axis=1)
    tangent[~valid] = 0; bitangent[~valid] = 0
    return np.ascontiguousarray(tangent), np.ascontiguousarray(bitangent), valid


@njit(cache=True)
def unit(vector):
    return vector / max(math.sqrt((vector * vector).sum()), 1e-10)


@njit(cache=True)
def decode_tangent_normal(data, convention, strength, y_sign):
    if convention == 1:
        nx, ny = data[0]*2-1, data[1]*2-1
    elif convention == 2:
        nx, ny = data[1]*2-1, data[3]*2-1
    else:
        nx, ny = data[3]*2-1, data[1]*2-1
    nz = math.sqrt(max(0., 1-nx*nx-ny*ny))
    result = np.array([nx*strength, ny*strength*y_sign, nz], np.float64)
    if (result*result).sum() < 1e-12:
        return np.array([0., 0., 1.], np.float64)
    return unit(result)


@njit(cache=True)
def mapped_normal(normal, tangent, bitangent, data, convention, strength, y_sign):
    normal = normal.astype(np.float64)
    if convention == 0 or strength == 0:
        return normal
    t = tangent-normal*float((normal*tangent).sum())
    if (t*t).sum() < 1e-16 or (bitangent*bitangent).sum() < 1e-16:
        return normal
    t = unit(t)
    b = unit(np.cross(normal, t))
    # Recover original UV handedness, including mirrored islands. The image
    # row flip occurs at sampling only; it must not flip the UV tangent frame.
    if (b*bitangent).sum() < 0:
        b = -b
    local = decode_tangent_normal(data, convention, strength, y_sign)
    return unit(t*local[0]+b*local[1]+normal*local[2])


@njit(cache=True)
def sample(texture, u, v, repeat):
    if repeat:
        u = u - math.floor(u)
        v = v - math.floor(v)
    x = max(0., min(texture.shape[1] - 1, u * (texture.shape[1] - 1)))
    y = max(0., min(texture.shape[0] - 1, (1 - v) * (texture.shape[0] - 1)))
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, texture.shape[1] - 1), min(y0 + 1, texture.shape[0] - 1)
    dx, dy = x - x0, y - y0
    result = np.empty(4, np.float64)
    for channel in range(4):
        result[channel] = ((texture[y0, x0, channel] * (1-dx) + texture[y0, x1, channel] * dx) * (1-dy)
                           + (texture[y1, x0, channel] * (1-dx) + texture[y1, x1, channel] * dx) * dy) / 255.
    return result


@njit(cache=True)
def ggx(base, normal, view, rough, metal, lights, intensities):
    n, v = unit(normal), unit(view)
    nv = max(.025, float((n * v).sum()))
    result = np.zeros(3, np.float64)
    f0 = .04 * (1-metal) + base * metal
    for index in range(len(lights)):
        light = lights[index]
        half = unit(light + v)
        nl, nh, vh = max(0., float((n*light).sum())), max(0., float((n*half).sum())), max(0., float((v*half).sum()))
        a2 = rough ** 4
        denominator = nh * nh * (a2-1) + 1
        distribution = a2 / (math.pi * denominator * denominator + 1e-7)
        k = (rough+1) ** 2 / 8
        geometry = (nv/(nv*(1-k)+k)) * (nl/(nl*(1-k)+k))
        fresnel = f0 + (1-f0) * (1-vh) ** 5
        specular = distribution * geometry * fresnel / (4*nv*max(nl, .001)+1e-7)
        diffuse = (1-fresnel) * (1-metal) * base/math.pi
        result += (diffuse+specular) * nl * intensities[index]
    reflected = 2*float((n*v).sum())*n-v
    strip = math.exp(-((reflected[1]-.55)/(.13+rough*.48))**2)
    side = math.exp(-((reflected[0]+.55)/(.09+rough*.42))**2)
    environment = .24 + strip*1.3 + side*.55
    result += (.31+.11*max(-.5, float(n[1]))) * base * (1-metal)
    result += (f0+(1-f0)*(1-nv)**5) * environment * (1-.45*rough)
    return result


@njit(cache=True)
def draw(screen, world, uvs, normals, tangents, bitangents, material_ids, colors, packed, has_packed,
         normal_textures, normal_codes, normal_strengths, normal_y_signs,
         roughness, metallicity, double_sided, repeats, basis, width, height,
         lights, intensities, material_mode):
    frame = np.empty((height, width, 3), np.uint8)
    frame[:] = 238
    depth = np.full((height, width), -np.inf, np.float32)
    owners = np.full((height, width), -1, np.int32)
    handedness = np.linalg.det(basis)
    for index in range(len(screen)):
        p = screen[index]
        mid = material_ids[index]
        denominator = (p[1,1]-p[2,1])*(p[0,0]-p[2,0])+(p[2,0]-p[1,0])*(p[0,1]-p[2,1])
        if abs(denominator) < 1e-8 or (not double_sided[mid] and denominator*handedness >= -1e-8):
            continue
        xmin, xmax = max(0, int(math.floor(p[:,0].min()))), min(width-1, int(math.ceil(p[:,0].max())))
        ymin, ymax = max(0, int(math.floor(p[:,1].min()))), min(height-1, int(math.ceil(p[:,1].max())))
        for y in range(ymin, ymax+1):
            for x in range(xmin, xmax+1):
                a = ((p[1,1]-p[2,1])*(x+.5-p[2,0])+(p[2,0]-p[1,0])*(y+.5-p[2,1]))/denominator
                b = ((p[2,1]-p[0,1])*(x+.5-p[2,0])+(p[0,0]-p[2,0])*(y+.5-p[2,1]))/denominator
                c = 1-a-b
                if a < -.0001 or b < -.0001 or c < -.0001:
                    continue
                z = a*p[0,2]+b*p[1,2]+c*p[2,2]
                if z <= depth[y,x]:
                    continue
                u = a*uvs[index,0,0]+b*uvs[index,1,0]+c*uvs[index,2,0]
                v = a*uvs[index,0,1]+b*uvs[index,1,1]+c*uvs[index,2,1]
                color = sample(colors[mid], u, v, repeats[mid])
                if material_mode:
                    n = unit(a*normals[index,0]+b*normals[index,1]+c*normals[index,2])
                    back_facing = double_sided[mid] and (n*basis[2]).sum() < 0
                    if normal_codes[mid] != 0 and normal_strengths[mid] != 0:
                        normal_data = sample(normal_textures[mid], u, v, repeats[mid])
                        n = mapped_normal(n, tangents[index], bitangents[index], normal_data,
                                          normal_codes[mid], normal_strengths[mid], normal_y_signs[mid])
                    if back_facing:
                        # Match the referenced shader's TBN-then-face-sign
                        # ordering. Flipping N before TBN would retain XY.
                        n = -n
                    rough, metal = roughness[mid], metallicity[mid]
                    if has_packed[mid]:
                        data = sample(packed[mid], u, v, repeats[mid])
                        rough, metal = max(.04, min(1., 1-data[0])), max(0., min(1., data[2]))
                    base = np.empty(3, np.float64)
                    for channel in range(3):
                        base[channel] = color[channel]/12.92 if color[channel] <= .04045 else ((color[channel]+.055)/1.055)**2.4
                    radiance = ggx(base, n, basis[2], rough, metal, lights, intensities)
                    for channel in range(3):
                        value = max(0., radiance[channel]*1.06)
                        value = max(0., min(1., value*(2.51*value+.03)/(value*(2.43*value+.59)+.14)))
                        srgb = value*12.92 if value <= .0031308 else 1.055*value**(1/2.4)-.055
                        frame[y,x,channel] = int(max(0., min(255., srgb*255)))
                else:
                    # Layout preserves RGB without speculative material lighting.
                    for channel in range(3):
                        frame[y,x,channel] = int(max(0., min(255., color[channel]*255)))
                depth[y,x], owners[y,x] = z, index
    return frame, depth, owners


def light_settings(raw: dict) -> tuple[np.ndarray, np.ndarray]:
    light = raw.get('lighting', {})
    vectors = np.asarray(light.get('directions', [[.22,.90,.37], [-.6,.45,-.6]]), np.float32)
    intensities = np.asarray(light.get('intensities', [2.25,.45]), np.float32)
    if vectors.ndim != 2 or vectors.shape[1] != 3 or not 1 <= len(vectors) <= 8 or intensities.shape != (len(vectors),):
        raise ValueError('lighting directions/intensities dimensions are invalid')
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(vectors).all() or not np.isfinite(intensities).all() or (lengths < 1e-8).any() or (intensities < 0).any() or (intensities > 20).any():
        raise ValueError('invalid light vector or intensity')
    return np.ascontiguousarray(vectors/lengths), intensities


def render(scene_path: Path, view: str, mode: str, output: Path, camera_path: Path | None = None) -> dict:
    if mode not in ('layout', 'material'):
        raise ValueError('mode must be layout or material')
    scene = load_scene(scene_path)
    screen, camera, camera_inputs = select_camera(scene, view, camera_path)
    lights, intensities = light_settings(scene['raw'])
    geometry = scene['geometry']
    normals = smooth_normals(geometry['triangles'], geometry['node_ids'], geometry['material_ids'])
    tangents, bitangents, tangent_valid = tangent_frames(geometry['triangles'], geometry['uvs'])
    output = output.expanduser().resolve()
    if output.suffix.lower() != '.png':
        raise ValueError('--out must name a new PNG file')
    mask_path = output.with_name(output.stem+'-mask.png')
    depth_path = output.with_name(output.stem+'-depth.npz')
    receipt_path = output.with_suffix('.json')
    outputs = [output, mask_path, depth_path, receipt_path]
    frozen_hashes = {**scene['input_hashes'], **camera_inputs}
    inputs = list(frozen_hashes)
    with ArtifactTransaction(outputs, inputs=inputs, label='scene-render', failure_directory=output.parent) as transaction:
        colors, packed, normal_textures = List(), List(), List()
        for color, data, normal_data in zip(scene['colors'], scene['packed'], scene['normal_textures']):
            colors.append(color)
            packed.append(data)
            normal_textures.append(normal_data)
        frame, depth, owners = draw(screen, geometry['triangles'], geometry['uvs'], normals, tangents, bitangents,
                                    geometry['material_ids'], colors, packed, scene['has_packed'],
                                    normal_textures, scene['normal_codes'], scene['normal_strengths'], scene['normal_y_signs'],
                                    scene['roughness'], scene['metallicity'], scene['double_sided'], scene['repeats'],
                                    np.asarray(camera['basis'], np.float32), camera['width'], camera['height'], lights, intensities, mode == 'material')
        if not np.any(owners >= 0):
            raise ValueError('camera produced no visible triangles')
        Image.fromarray(frame).save(transaction.stage(output))
        Image.fromarray(((owners >= 0)*255).astype(np.uint8)).save(transaction.stage(mask_path))
        staged_depth = transaction.stage(depth_path)
        np.savez_compressed(staged_depth, depth=depth, owners=owners,
                            geometry_sha256=np.asarray(geometry['_sha256']),
                            camera_sha256=np.asarray(surface.camera_fingerprint(camera)))
        coverage = np.bincount(geometry['material_ids'][owners[owners >= 0]], minlength=len(scene['colors']))
        report = dict(schema_version=2, geometry=str(scene['geometry_path']), geometry_sha256=geometry['_sha256'],
                      camera_sha256=surface.camera_fingerprint(camera), depth_file=str(depth_path), depth_sha256=file_hash(staged_depth),
                      view=view, mode=mode, **camera, layout_only=mode == 'layout', material_approximation=mode == 'material',
                      scene=str(scene['path']), scene_sha256=frozen_hashes[scene['path']], image=str(output),
                      image_sha256=file_hash(transaction.stage(output)), covered_pixels=int((owners >= 0).sum()),
                      material_names=geometry['material_names'].tolist(), display_state=scene['raw']['display_state'],
                      normal_mapping=dict(default='disabled', active_in_this_mode=mode == 'material' and bool(np.any((scene['normal_codes']>0)&(scene['normal_strengths']>0))),
                                          conventions={record['name']:record.get('normal_convention','none') for record in scene['raw']['materials']},
                                          strength={record['name']:record.get('normal_strength',1.) for record in scene['raw']['materials'] if record.get('normal_convention','none')!='none'},
                                          y_sign={record['name']:record.get('normal_y_sign',1.) for record in scene['raw']['materials'] if record.get('normal_convention','none')!='none'},
                                          degenerate_UV_triangles_geometric_normal_fallback={str(name):int(((geometry['material_ids']==index)&~tangent_valid).sum())
                                                                                            for index,name in enumerate(geometry['material_names']) if scene['normal_codes'][index]}),
                      source_inputs=[dict(path=str(path), sha256=frozen_hashes[path]) for path in inputs],
                      lighting=dict(directions=lights.tolist(), intensities=intensities.tolist()), limitations=LIMITATIONS,
                      material_coverage={str(name): int(coverage[index])
                                         for index, name in enumerate(geometry['material_names'])})
        transaction.stage(receipt_path).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if any(file_hash(path) != digest for path, digest in frozen_hashes.items()):
            raise ValueError('Scene input changed during rendering; stale outputs were not committed')
        transaction.commit()
    return report


def _export_file(root: Path, value: str, *, required=True) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Decoder-export paths must be nonempty relative paths")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Decoder-export path escapes asset root: {value}")
    if not path.is_file():
        if required:
            raise FileNotFoundError(path)
        return None
    return path


def _export_triangles(path: Path, material_lookup: dict[str, int], expected_faces: int):
    positions, texcoords, triangles, uvs, material_ids = [], [], [], [], []
    current = None
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            words = line.split()
            if not words:
                continue
            if words[0] in ("v", "vt"):
                width = 3 if words[0] == "v" else 2
                if len(words) < width + 1:
                    raise ValueError(f"Truncated coordinate {path}:{number}")
                values = [float(value) for value in words[1:width + 1]]
                if not np.isfinite(values).all():
                    raise ValueError(f"Nonfinite coordinate {path}:{number}")
                (positions if width == 3 else texcoords).append(values)
            elif words[0] == "usemtl":
                current = material_lookup.get(" ".join(words[1:]))
                if current is None:
                    raise ValueError(f"Unknown OBJ material {path}:{number}")
            elif words[0] == "f":
                if len(words) != 4 or current is None:
                    raise ValueError(f"Expected triangular face with material {path}:{number}")
                face, face_uv = [], []
                for token in words[1:]:
                    fields = token.split("/")
                    if len(fields) < 2 or not fields[0] or not fields[1]:
                        raise ValueError(f"Face missing vertex/UV {path}:{number}")
                    vi, ti = int(fields[0]), int(fields[1])
                    if vi == 0 or ti == 0:
                        raise ValueError(f"OBJ index zero {path}:{number}")
                    vi = vi - 1 if vi > 0 else len(positions) + vi
                    ti = ti - 1 if ti > 0 else len(texcoords) + ti
                    if not (0 <= vi < len(positions) and 0 <= ti < len(texcoords)):
                        raise ValueError(f"OBJ index outside available data {path}:{number}")
                    face.append(positions[vi]); face_uv.append(texcoords[ti])
                triangles.append(face); uvs.append(face_uv); material_ids.append(current)
    if not triangles or len(triangles) != expected_faces:
        raise ValueError(f"Source face count mismatch for {path}: {len(triangles)} != {expected_faces}")
    points, coords = np.asarray(triangles, np.float32), np.asarray(uvs, np.float32)
    if not np.isfinite(points).all() or not np.isfinite(coords).all():
        raise ValueError(f"Coordinates exceed float32 finite range: {path}")
    return points, coords, np.asarray(material_ids, np.int32)


def prepare(asset_root: Path, selection_path: Path, output: Path) -> dict:
    asset_root, selection_path, output = asset_root.resolve(strict=True), selection_path.resolve(strict=True), output.resolve()
    if not asset_root.is_dir():
        raise NotADirectoryError(asset_root)
    metadata = [asset_root / "parts.json", asset_root / "materials.json", selection_path]
    source_hashes = {path: file_hash(path) for path in metadata}
    selection = load_json(selection_path)
    if not isinstance(selection, dict) or selection.get("schema_version") != 1:
        raise ValueError("selection schema_version must be 1")
    included, description = selection.get("include_nodes"), selection.get("description")
    if not isinstance(included, list) or not included or any(not isinstance(n, str) or not n for n in included) or len(set(included)) != len(included):
        raise ValueError("include_nodes must be nonempty unique exact node names")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("selection must describe the static display state")
    parts, materials = load_json(metadata[0]).get("parts"), load_json(metadata[1]).get("materials")
    if not isinstance(parts, list) or not isinstance(materials, list) or not parts or not materials:
        raise ValueError("Decoder export requires nonempty parts and materials arrays")
    if any(not isinstance(item, dict) for item in parts + materials):
        raise ValueError("Decoder part/material entries must be objects")
    parts_by_name = {part.get("name"): part for part in parts}
    names = [material.get("name") for material in materials]
    obj_names = [material.get("obj_name", material.get("name")) for material in materials]
    if len(parts_by_name) != len(parts) or any(not isinstance(n, str) or not n for n in names + obj_names) or len(set(names)) != len(names) or len(set(obj_names)) != len(obj_names):
        raise ValueError("Export part/material names must be unique nonempty strings")
    missing = set(included) - set(parts_by_name)
    if missing:
        raise ValueError(f"include_nodes do not exist: {sorted(missing)}")
    overrides = selection.get("materials", {})
    if not isinstance(overrides, dict) or set(overrides) - set(names):
        raise ValueError("materials overrides must be keyed by existing canonical material names")
    selected = [parts_by_name[name] for name in included]
    obj_paths = [_export_file(asset_root, part.get("file")) for part in selected]
    if len(set(obj_paths)) != len(obj_paths):
        raise ValueError("Selected nodes alias the same OBJ file")
    for part in selected:
        if isinstance(part.get("faces"), bool) or not isinstance(part.get("faces"), int) or part["faces"] <= 0:
            raise ValueError("Source part faces must be a positive integer")
    sources = set(metadata + obj_paths)
    source_hashes.update({path: file_hash(path) for path in obj_paths})
    records, warnings = [], []
    for index, material in enumerate(materials):
        record = {"id": index, "name": names[index], "base_color": [.55, .58, .62, 1.], "roughness": .45, "metallic": 0., "double_sided": False, "uv_mode": "unit"}
        slots = material.get("texture_slots", [])
        if not isinstance(slots, list) or any(value is not None and not isinstance(value, str) for value in slots):
            raise ValueError("texture_slots must preserve ordered string/null entries")
        for field, slot in [("color", 0), ("packed", 2)]:
            resource = slots[slot].rstrip("*") if len(slots) > slot and slots[slot] else None
            if resource and (Path(resource).name != resource or "/" in resource or "\\" in resource or ":" in resource):
                raise ValueError(f"Unsafe texture resource name: {resource}")
            path = _export_file(asset_root, f"textures/{resource}.tga", required=False) if resource else None
            if path is None and field == "color" and material.get("albedo_proxy"):
                path = _export_file(asset_root, material["albedo_proxy"], required=False)
                if path:
                    warnings.append(f"{names[index]}: color uses retained albedo proxy; source alpha may be absent")
            if path:
                record[field] = {"path": str(path), "sha256": file_hash(path)}
                sources.add(path); source_hashes[path] = record[field]["sha256"]
        override = overrides.get(names[index], {})
        if not isinstance(override, dict) or set(override) - {"color", "packed", "normal_texture", "normal_convention", "normal_strength", "normal_y_sign", "base_color", "roughness", "metallic", "double_sided", "uv_mode"}:
            raise ValueError(f"Unsupported material override: {names[index]}")
        if "base_color" in override and "color" not in override:
            record.pop("color", None)
        for key, value in override.items():
            if key in ("color", "packed", "normal_texture"):
                if value is None:
                    record.pop(key, None); continue
                if not isinstance(value, dict) or set(value) != {"path", "sha256"} or not isinstance(value["path"], str):
                    raise ValueError(f"{key} override requires path and sha256")
                path = Path(value["path"]).expanduser()
                path = (path if path.is_absolute() else selection_path.parent / path).resolve(strict=True)
                if not path.is_file() or not isinstance(value["sha256"], str) or file_hash(path) != value["sha256"].lower():
                    raise ValueError(f"Material override source hash mismatch: {path}")
                record[key] = {"path": str(path), "sha256": file_hash(path)}
                sources.add(path); source_hashes[path] = record[key]["sha256"]
            else:
                record[key] = value
        constant = np.asarray(record["base_color"], dtype=float)
        if constant.shape != (4,) or not np.isfinite(constant).all() or (constant < 0).any() or (constant > 1).any():
            raise ValueError("base_color must contain four finite 0..1 values")
        for key, low, high in [("roughness", .04, 1.), ("metallic", 0., 1.)]:
            value = record[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key} outside {low}..{high}")
        if not isinstance(record["double_sided"], bool) or record["uv_mode"] not in ("unit", "repeat"):
            raise ValueError("double_sided/uv_mode invalid")
        if record.get('normal_convention', 'none') not in ('none', 'rg_xy', 'ga_xy', 'ag_xy'):
            raise ValueError('Invalid normal_convention')
        if record.get('normal_convention', 'none') != 'none' and 'packed' not in record and 'normal_texture' not in record:
            raise ValueError('normal_convention needs packed or normal_texture')
        scalar(record.get('normal_strength', 1.), 0., 4., 'normal_strength')
        if scalar(record.get('normal_y_sign', 1.), -1., 1., 'normal_y_sign') not in (-1., 1.):
            raise ValueError('normal_y_sign must be -1 or 1')
        for field in ("color", "packed", "normal_texture"):
            if field in record:
                with Image.open(record[field]["path"]) as image:
                    texture_dimensions(image.width, image.height)
                    image.load()
        if "color" not in record:
            warnings.append(f"{names[index]}: explicit neutral base_color proxy; original game surface is not reproduced")
        records.append(record)
    geometry_path, scene_path, receipt_path = output / "geometry.npz", output / "scene.json", output / "prepare-receipt.json"
    with ArtifactTransaction([geometry_path, scene_path, receipt_path], inputs=[asset_root, *sorted(sources)], label="scene-prepare", failure_directory=output.parent / ".artifact-failures") as transaction:
        batches = [_export_triangles(path, dict(zip(obj_names, range(len(materials)))), part["faces"]) for path, part in zip(obj_paths, selected)]
        triangles, uvs, material_ids = [np.concatenate([batch[i] for batch in batches]) for i in range(3)]
        node_ids = np.concatenate([np.full(len(batch[0]), index, np.int32) for index, batch in enumerate(batches)])
        repeated = []
        for index, record in enumerate(records):
            values = uvs[material_ids == index]
            if values.size and ((values < 0).any() or (values > 1).any()):
                if overrides.get(record["name"], {}).get("uv_mode") == "unit":
                    raise ValueError(f"Explicit unit sampler contradicts source UV: {record['name']}")
                record["uv_mode"] = "repeat"; repeated.append(record["name"])
        stage_geometry = transaction.stage(geometry_path)
        np.savez_compressed(stage_geometry, triangles=triangles, uvs=uvs, node_ids=node_ids, names=np.asarray(included), material_ids=material_ids,
                            material_names=np.asarray(names), material_resources=np.asarray([json.dumps(m.get("texture_slots", []), ensure_ascii=False, separators=(",", ":")) for m in materials]))
        scene = {"schema_version": 1, "geometry": {"path": str(geometry_path), "sha256": file_hash(stage_geometry)}, "materials": records,
                 "display_state": {"description": description, "include_nodes": included, "coordinates": "Decoded OBJ assembly coordinates, original UVs, no additional transform or re-unwrapping"}}
        stage_scene = transaction.stage(scene_path)
        stage_scene.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        if any(file_hash(path) != digest for path, digest in source_hashes.items()):
            raise ValueError("Source changed during preparation; outputs were not committed")
        receipt = {"schema_version": 1, "state": "complete", "transaction_id": transaction.transaction_id, "selected_nodes": included, "triangles": len(triangles),
                   "sources": [{"path": str(path), "sha256": source_hashes[path]} for path in sorted(sources)],
                   "outputs": [{"path": str(final), "sha256": file_hash(staged)} for final, staged in [(geometry_path, stage_geometry), (scene_path, stage_scene)]],
                   "repeat_uv_materials": repeated, "projection_compatible_unit_uv": not repeated, "warnings": warnings,
                   "limitations": ["Static decoder bind pose; selection explicitly owns which loadout/state nodes are present", "Approximate opaque preview; fallback constants and retained RGB proxies do not reproduce the game shader", "Repeated UV materials can be scene-rendered but must be excluded from unit-UV projection geometry"]}
        transaction.stage(receipt_path).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        transaction.commit()
    return {"scene": str(scene_path), "geometry": str(geometry_path), "receipt": str(receipt_path), "triangles": len(triangles), "nodes": len(included), "repeat_uv_materials": repeated}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('render')
    command.add_argument('--scene', required=True, type=Path)
    command.add_argument('--view', default='iso')
    command.add_argument('--camera', type=Path)
    command.add_argument('--mode', choices=['layout', 'material'], default='layout')
    command.add_argument('--out', required=True, type=Path)
    command = commands.add_parser('prepare', help='Prepare a hash-bound scene from a standard decoder OBJ export')
    command.add_argument('--asset', required=True, type=Path)
    command.add_argument('--selection', required=True, type=Path)
    command.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            report = prepare(args.asset, args.selection, args.out)
        else:
            report = render(args.scene, args.view, args.mode, args.out, args.camera)
    except (ValueError, OSError, KeyError, TypeError, ArtifactError) as error:
        parser.exit(1, f'scene preview failed: {error}\n')
    summary = report if args.command == 'prepare' else dict(image=report['image'], covered_pixels=report['covered_pixels'], mode=report['mode'])
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
