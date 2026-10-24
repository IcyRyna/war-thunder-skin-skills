"""Measure actual selected surface texels, never atlas padding as paint evidence."""
import numpy as np
from PIL import Image, ImageDraw
from reference_contract import check_base_color


def carrier_mask(geometry, triangle_ids, size):
    ids = np.asarray(triangle_ids, dtype=np.int64)
    width, height = map(int, size)
    if ids.ndim != 1 or not len(ids) or len(set(ids.tolist())) != len(ids) or min(width, height) < 1 or max(width, height) > 16384:
        raise ValueError('Explicit unique triangle IDs and bounded image size required')
    positions, uvs = geometry['positions'], geometry['uvs']
    if ids.min() < 0 or ids.max() >= len(positions) or len(positions) != len(uvs):
        raise ValueError('Triangle IDs do not belong to this geometry')
    image = Image.new('1', (width, height))
    draw = ImageDraw.Draw(image)
    for index in ids:
        p, uv = positions[index], uvs[index]
        if not np.isfinite(p).all() or not np.isfinite(uv).all():
            raise ValueError('Nonfinite carrier data')
        if np.linalg.norm(np.cross(p[1]-p[0], p[2]-p[0])) < 1e-12:
            raise ValueError('Degenerate geometric carrier')
        if abs(np.linalg.det(np.stack([uv[1]-uv[0], uv[2]-uv[0]]))) < 1e-12:
            raise ValueError('Degenerate UV carrier')
        lo, hi = np.floor(uv.min(0)).astype(int), np.floor(uv.max(0)).astype(int)
        if np.any(hi-lo > 2):
            raise ValueError('Unexpected UV wrapping extent')
        for u in range(lo[0], hi[0]+1):
            for v in range(lo[1], hi[1]+1):
                points = [((float(q[0])-u)*width-.5, (1-float(q[1])+v)*height-.5) for q in uv]
                draw.polygon(points, fill=1)
    mask = np.asarray(image, dtype=bool)
    if mask.sum() < 32:
        raise ValueError('Selected surface has insufficient actual texels')
    return mask


def audit_basecoat(image, geometry, triangle_ids, name, protected_mask=None):
    a = np.asarray(image)
    if not isinstance(name, str) or not name.strip() or a.ndim != 3:
        raise ValueError('A named physical paint carrier and RGB image are required')
    mask = carrier_mask(geometry, triangle_ids, (a.shape[1], a.shape[0]))
    if protected_mask is not None:
        protect = np.asarray(protected_mask, dtype=bool)
        if protect.shape != mask.shape:
            raise ValueError('Protection mask size mismatch')
        mask &= ~protect
    report = check_base_color(a, mask)
    rgb = a[:, :, :3][mask]
    dark_fraction = float(np.mean(np.max(rgb, axis=1) < 20))
    if dark_fraction > .02:
        raise ValueError(f'Native dark pixels leaked into painted carrier {name}: {dark_fraction:.1%}')
    return {**report, 'carrier': name, 'triangle_ids': list(map(int, triangle_ids)), 'dark_fraction_below_20': dark_fraction, 'atlas_padding_excluded': True}
