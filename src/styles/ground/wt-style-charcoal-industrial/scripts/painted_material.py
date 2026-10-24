"""Explicit material recipe for newly opaque-painted metal, not arbitrary N data."""
import numpy as np
from scipy.ndimage import gaussian_filter


def matte_coating(native, paint_mask, normal_strength=.55, roughness_center=64,
                 roughness_gain=.08, roughness_limits=(52, 72), metalness=0):
    a = np.asarray(native)
    mask = np.asarray(paint_mask, dtype=bool)
    if a.dtype != np.uint8 or a.ndim != 3 or a.shape[2] != 4 or mask.shape != a.shape[:2]:
        raise ValueError('Native packed uint8 RGBA and matching explicit paint mask required')
    if not mask.any() or not 0 <= normal_strength <= 1 or not 0 <= roughness_limits[0] <= roughness_center <= roughness_limits[1] <= 255 or not 0 <= metalness <= 255:
        raise ValueError('Invalid declared coating parameters')
    if not 0 <= roughness_gain <= 1:
        raise ValueError('Invalid roughness residual gain')
    out = a.copy()
    red = a[:, :, 0].astype(np.float32)
    rough = np.uint8(np.clip(np.rint(roughness_center + roughness_gain*(red-gaussian_filter(red, 3))), *roughness_limits))
    out[mask, 0] = rough[mask]
    out[mask, 2] = metalness
    for channel in (1, 3):
        scaled = np.uint8(np.clip(np.rint(127.5+(a[:, :, channel].astype(np.float32)-127.5)*normal_strength), 0, 255))
        out[mask, channel] = scaled[mask]
    if not np.array_equal(out[~mask], a[~mask]):
        raise AssertionError('Material patch escaped the approved paint region')
    return out
