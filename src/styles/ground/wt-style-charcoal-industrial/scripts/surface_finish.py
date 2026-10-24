"""Give explicit packed-normal regions a smoother reflective finish."""
import numpy as np
from scipy.ndimage import gaussian_filter


def polished_finish(normal, mask, inverted_roughness=180, metalness=220, normal_smoothing=2.):
    source, region = np.asarray(normal), np.asarray(mask, bool)
    if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 4 or region.shape != source.shape[:2] or not region.any():
        raise ValueError('Packed RGBA normal data and a nonempty explicit region are required')
    if not 0 <= inverted_roughness <= 255 or not 0 <= metalness <= 255 or not 0 <= normal_smoothing <= 4:
        raise ValueError('Finish values are outside declared ranges')
    result = source.copy()
    result[region, 0] = inverted_roughness
    result[region, 2] = metalness
    if normal_smoothing:
        weight = gaussian_filter(region.astype(np.float32), normal_smoothing)
        for channel in [1, 3]:
            smoothed = gaussian_filter(source[:, :, channel].astype(np.float32)*region, normal_smoothing)/np.maximum(weight, 1e-8)
            result[region, channel] = np.uint8(np.clip(np.rint(smoothed[region]), 0, 255))
    assert np.array_equal(result[~region], source[~region])
    return result
