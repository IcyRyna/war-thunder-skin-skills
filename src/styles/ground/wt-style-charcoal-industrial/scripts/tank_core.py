"""Independent image and OBJ helpers for ground vehicle skins."""
from __future__ import annotations
import json
import hashlib
import struct
from pathlib import Path
import numpy as np
from PIL import Image

MAX_TEXTURE_SIZE = 16384
# Ground colour maps may legitimately be 16k. Keep Pillow's bomb protection at
# that documented ceiling; every opened image is dimension-checked as well.
Image.MAX_IMAGE_PIXELS = MAX_TEXTURE_SIZE * MAX_TEXTURE_SIZE


def _texture_dimensions(width: int, height: int) -> None:
    if not (0 < width <= MAX_TEXTURE_SIZE and 0 < height <= MAX_TEXTURE_SIZE):
        raise ValueError(f'Texture dimensions must be in 1..{MAX_TEXTURE_SIZE}: {width} x {height}')

def load_image(path: Path | str) -> Image.Image:
    path = Path(path)
    if path.suffix.lower() == '.dds':
        with path.open('rb') as stream:
            header = stream.read(128)
            if len(header) != 128 or header[:4] != b'DDS ':
                raise ValueError(f'Invalid DDS header: {path}')
            height, width, pitch = struct.unpack_from('<III', header, 12)
            _texture_dimensions(width, height)
            pf = struct.unpack_from('<8I', header, 76)
            if pf[1] & 64 and pf[3:] == (32, 0xff0000, 0xff00, 0xff, 0xff000000):
                pitch = pitch or width * 4
                if pitch < width * 4 or pitch > width * 4 + 65536:
                    raise ValueError(f'Invalid DDS row pitch: {path}')
                data = stream.read(pitch * height)
                if len(data) != pitch * height:
                    raise ValueError(f'Truncated DDS pixels: {path}')
                return Image.frombytes('RGBA', (width, height), data, 'raw', 'BGRA', pitch)
    with Image.open(path) as image:
        _texture_dimensions(*image.size)
        image.load()
        return image.convert('RGBA')

def resize_data_image(image: Image.Image, size: tuple[int, int], resample=Image.Resampling.BILINEAR) -> Image.Image:
    """Resample RGBA data bands independently; A can be a normal or paint component."""
    if len(size) != 2 or any(type(n) is not int or n < 1 for n in size):
        raise ValueError('Output dimensions must be positive integers')
    rgba = image.convert('RGBA')
    return Image.merge('RGBA', tuple(band.resize(size, resample) for band in rgba.split()))


def save_dds(image: Image.Image, path: Path | str) -> None:
    """Lossless legacy BGRA DDS top level; mip policy belongs to the caller."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = image.convert('RGBA')
    width, height = image.size
    _texture_dimensions(width, height)
    h = [0] * 31
    h[:7] = [124, 0x100f, height, width, width * 4, 0, 1]
    h[18:26] = [32, 0x41, 0, 32, 0xff0000, 0xff00, 0xff, 0xff000000]
    h[26] = 0x1000
    with path.open('wb') as output:
        output.write(b'DDS ' + struct.pack('<31I', *h))
        output.write(image.tobytes('raw', 'BGRA'))

def load_obj(path: Path | str, cache: Path | None = None) -> dict:
    path = Path(path)
    def source_digest():
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    digest=source_digest()
    if cache is not None and cache.resolve()==path.resolve():raise ValueError('OBJ cache must not overwrite its input')
    if cache is not None and cache.exists():
        with np.load(cache, allow_pickle=False) as data:
            if {'source_sha256','source_face_ids','source_triangle_count','skipped_source_face_ids'}<=set(data.files) and str(data['source_sha256'])==digest:
                return {name: data[name] for name in data.files}
    vertices, texcoords, normals = [], [], []
    triangles, uvtri, normtri, material_ids, node_ids = [], [], [], [], []
    source_ids,skipped_ids,source_count=[],[],0
    material_names, node_names = [], []
    material_lookup, node_lookup = {}, {}
    def key_id(name: str, lookup: dict, names: list) -> int:
        if name not in lookup:
            lookup[name] = len(names)
            names.append(name)
        return lookup[name]
    node = key_id('default', node_lookup, node_names)
    material = key_id('default', material_lookup, material_names)
    def index(token: str, size: int) -> int:
        value = int(token)
        result = value - 1 if value > 0 else size + value
        if not 0 <= result < size:
            raise ValueError(f'OBJ index out of range in {path}')
        return result
    with path.open('r', encoding='utf-8-sig') as stream:
        for line in stream:
            row = line.split('#', 1)[0].split()
            if not row: continue
            if row[0] == 'v':
                vertices.append(tuple(map(float, row[1:4])))
            elif row[0] == 'vt':
                texcoords.append(tuple(map(float, row[1:3])))
            elif row[0] == 'vn':
                normals.append(tuple(map(float, row[1:4])))
            elif row[0] in ('o', 'g'):
                node = key_id(' '.join(row[1:]), node_lookup, node_names)
            elif row[0] == 'usemtl':
                material = key_id(' '.join(row[1:]), material_lookup, material_names)
            elif row[0] == 'f':
                corners = [token.split('/') for token in row[1:]]
                for k in range(1, len(corners) - 1):
                    source_id=source_count;source_count+=1
                    face = [corners[0], corners[k], corners[k + 1]]
                    p = np.asarray([vertices[index(f[0], len(vertices))] for f in face])
                    n = np.cross(p[1] - p[0], p[2] - p[0])
                    length = np.linalg.norm(n)
                    if not np.isfinite(p).all():raise ValueError(f'OBJ has non-finite positions: {path}')
                    if length < 1e-12:
                        skipped_ids.append(source_id);continue
                    triangles.append(p)
                    source_ids.append(source_id)
                    face_uvs = [texcoords[index(f[1], len(texcoords))] if len(f) > 1 and f[1] else (0., 0.) for f in face]
                    face_normals = [normals[index(f[2], len(normals))] if len(f) > 2 and f[2] else n / length for f in face]
                    if np.asarray(face_uvs).shape != (3, 2) or not np.isfinite(face_uvs).all():
                        raise ValueError(f'OBJ has malformed or non-finite UV coordinates: {path}')
                    if np.asarray(face_normals).shape != (3, 3) or not np.isfinite(face_normals).all():
                        raise ValueError(f'OBJ has malformed or non-finite normals: {path}')
                    uvtri.append(face_uvs)
                    normtri.append(face_normals)
                    material_ids.append(material)
                    node_ids.append(node)
    if not triangles: raise ValueError(f'OBJ contains no renderable faces: {path}')
    result = dict(positions=np.asarray(triangles, dtype='f4'), uvs=np.asarray(uvtri, dtype='f4'),
                  normals=np.asarray(normtri, dtype='f4'), material_ids=np.asarray(material_ids, dtype='i4'),
                  node_ids=np.asarray(node_ids, dtype='i4'), material_names=np.asarray(material_names),
                  node_names=np.asarray(node_names),source_face_ids=np.asarray(source_ids,dtype='i8'),
                  skipped_source_face_ids=np.asarray(skipped_ids,dtype='i8'),
                  source_triangle_count=np.asarray(source_count,dtype='i8'),source_sha256=np.asarray(digest))
    if source_digest()!=digest:raise ValueError('OBJ changed during parsing')
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, **result)
    return result

def unit(value: np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype='f4')
    return value / np.maximum(np.linalg.norm(value, axis=-1, keepdims=True), 1e-12)

def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
