"""Continuous, masked neutral paint. Darkness alone never identifies a hole."""
import numpy as np
from scipy.ndimage import gaussian_filter
from skill_contract import policy


def neutral_basecoat(source, paint_mask, center=None, gain=.06, limits=None, sigma=3, *, role="A"):
    if role not in policy()["paint_roles"]:
        raise ValueError("Unknown paint role")
    center = policy()["paint_roles"][role]["rgb"][0] if center is None else center
    limits = (max(0, center-7), min(255, center+7)) if limits is None else limits
    a = np.asarray(source)
    mask = np.asarray(paint_mask, dtype=bool)
    if a.dtype != np.uint8 or a.ndim != 3 or a.shape[2] not in (3, 4) or mask.shape != a.shape[:2]:
        raise ValueError('Expected uint8 RGB/RGBA and an explicit matching paint mask')
    if not mask.any() or not 0 <= limits[0] <= center <= limits[1] <= 255 or not 0 <= gain <= 1 or sigma <= 0:
        raise ValueError('Invalid paint region or tonal parameters')
    lum = a[:, :, :3].astype(np.float32) @ np.array([.2126, .7152, .0722], np.float32)
    value = np.uint8(np.clip(np.rint(center + (lum - gaussian_filter(lum, sigma)) * gain), *limits))
    out = a.copy()
    out[mask, :3] = value[mask, None]
    if not np.array_equal(out[~mask], a[~mask]) or (a.shape[2] == 4 and not np.array_equal(out[:, :, 3], a[:, :, 3])):
        raise AssertionError('Paint escaped its RGB-only region')
    return out
