"""Recoat explicit metal texels without changing cutout or normal directions."""
import numpy as np
from scipy.ndimage import gaussian_filter


def coat_cutout_metal(color, normal, metal_mask, protected_mask):
    c, n = np.asarray(color), np.asarray(normal)
    m, protected = np.asarray(metal_mask, dtype=bool), np.asarray(protected_mask, dtype=bool)
    if c.dtype != np.uint8 or n.dtype != np.uint8 or c.shape != n.shape or c.ndim != 3 or c.shape[2] != 4:
        raise ValueError('Matching native uint8 RGBA color and normal inputs are required')
    if m.shape != c.shape[:2] or protected.shape != m.shape or not m.any() or (m & protected).any():
        raise ValueError('Explicit nonempty coating and disjoint protection masks are required')
    result_c, result_n = c.copy(), n.copy()
    luma = c[:, :, :3].astype(np.float32).mean(2)
    neutral = np.uint8(np.clip(np.rint(35+.10*(luma-gaussian_filter(luma, 3))), 28, 48))
    result_c[m, :3] = neutral[m, None]
    red = n[:, :, 0].astype(np.float32)
    roughness = np.uint8(np.clip(np.rint(72+.08*(red-gaussian_filter(red, 3))), 56, 85))
    result_n[m, 0] = roughness[m]
    result_n[m, 2] = 40
    assert np.array_equal(result_c[:, :, 3], c[:, :, 3])
    assert np.array_equal(result_n[:, :, [1, 3]], n[:, :, [1, 3]])
    assert np.array_equal(result_c[~m], c[~m]) and np.array_equal(result_n[~m], n[~m])
    return result_c, result_n


def coat_cutout_parts(color, normal, metal_mask, polymer_mask, protected_mask):
    """Apply distinct declared metal/polymer finishes; preserve native coverage."""
    c, n = np.asarray(color), np.asarray(normal)
    metal = np.asarray(metal_mask, dtype=bool)
    polymer = np.asarray(polymer_mask, dtype=bool)
    protected = np.asarray(protected_mask, dtype=bool)
    if polymer.shape != metal.shape or protected.shape != metal.shape or (polymer & metal).any() or (polymer & protected).any():
        raise ValueError('Part roles must use explicit disjoint masks')
    result_c, result_n = coat_cutout_metal(c, n, metal, protected | polymer)
    if polymer.any():
        luma = c[:, :, :3].astype(np.float32).mean(2)
        value = np.uint8(np.clip(np.rint(24+.08*(luma-gaussian_filter(luma, 3))), 18, 36))
        result_c[polymer, :3] = value[polymer, None]
        result_n[polymer, 0] = 48
        result_n[polymer, 2] = 0
    assert np.array_equal(result_c[:, :, 3], c[:, :, 3])
    assert np.array_equal(result_n[:, :, [1, 3]], n[:, :, [1, 3]])
    outside = ~(metal | polymer)
    assert np.array_equal(result_c[outside], c[outside]) and np.array_equal(result_n[outside], n[outside])
    return result_c, result_n
