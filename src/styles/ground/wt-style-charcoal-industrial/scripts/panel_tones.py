"""Apply declared neutral panel levels while retaining target-native fine grain."""
import numpy as np


def tonal_overlay(base_rgba, regions, reference=31, allowed_range=(23, 52)):
    base = np.asarray(base_rgba)
    if base.dtype != np.uint8 or base.ndim != 3 or base.shape[2] != 4 or not regions:
        raise ValueError('A neutral native base and named surface regions are required')
    overlay = np.zeros_like(base)
    owner = np.full(base.shape[:2], -1, np.int16)
    reports = []
    for index, (name, mask, tone) in enumerate(regions):
        m = np.asarray(mask, bool)
        if not name or m.shape != owner.shape or not m.any() or not isinstance(tone, int) or not allowed_range[0] <= tone <= allowed_range[1]:
            raise ValueError('Each panel needs an explicit nonempty native mask and bounded neutral tone')
        rgb = np.clip(base[m, :3].astype(np.int16)+(tone-reference), 0, 255).astype(np.uint8)
        overlay[m, :3], overlay[m, 3], owner[m] = rgb, 255, index
        reports.append({'region': name, 'target_rgb': [tone]*3, 'requested_texels': int(m.sum())})
    for index, report in enumerate(reports):
        visible = owner == index
        report['effective_texels'] = int(visible.sum())
        if visible.any():
            report['median_rgb'] = np.median(overlay[visible, :3], axis=0).tolist()
    return overlay, reports
