"""Check named charcoal roles; UV counts are never visible body area."""
from __future__ import annotations
import numpy as np
from skill_contract import binary, number, policy, require_text, rgb

REQUIRED_ROLES = frozenset(policy()["graphic_roles"]["required"])


def check_roles(placements, omissions=None):
    rules = policy()["graphic_roles"]
    known = set(rules["required"] + rules["optional"])
    observed, raw = set(), set()
    for placement in placements:
        role = placement.get("role")
        normalized = rules["aliases"].get(role, role)
        if normalized not in known:
            raise ValueError("Unknown graphic role: " + str(role))
        pixels = number(placement.get("pixels", 0), "role pixels", 0, 2**53, True)
        if pixels:
            raw.add(role)
            observed.add(normalized)
    omissions = omissions or {}
    if not isinstance(omissions, dict):
        raise ValueError("Omissions must map roles to target-specific reasons")
    for role, reason in omissions.items():
        if role not in known or role in observed:
            raise ValueError("Unknown or contradictory omission: " + str(role))
        require_text(reason, "omission reason")
    missing = REQUIRED_ROLES - observed - set(omissions)
    if missing:
        raise ValueError("Missing graphic role or target decision: " + ", ".join(sorted(missing)))
    return {"observed_roles": sorted(observed), "source_role_names": sorted(raw),
            "optional_roles": rules["optional"], "explicit_omissions": omissions,
            "visual_acceptance": "not inferred"}


def check_base_color(rgba, base_mask, reference=None, max_median_delta=None,
                     max_neutral_chroma=None, *, role="A", override_reason=None):
    rules = policy()
    if role not in rules["paint_roles"]:
        raise ValueError("Paint role must be A, B, C or F")
    expected = rules["paint_roles"][role]["rgb"]
    if reference is not None:
        reference = rgb(reference, "target paint RGB")
        if reference != expected:
            require_text(override_reason, "target paint override reason")
        expected = reference
    if max(expected) != min(expected):
        raise ValueError("A/B/C/F are neutral; declare tinted material separately")
    limits = rules["color_tolerances"]
    delta = limits["max_median_delta"] if max_median_delta is None else number(max_median_delta, "median tolerance", 0, limits["max_median_delta"])
    chroma_limit = limits["max_p95_chroma"] if max_neutral_chroma is None else number(max_neutral_chroma, "chroma tolerance", 0, limits["max_p95_chroma"])
    image = np.asarray(rgba)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("Expected uint8 RGB/RGBA")
    mask = binary(base_mask, "named paint mask", image.shape[:2])
    if mask.sum() < limits["minimum_sample_pixels"]:
        raise ValueError("Paint role has too few actual UV samples")
    pixels = image[:, :, :3][mask].astype(float)
    median = np.median(pixels, axis=0)
    chroma = float(np.percentile(np.ptp(pixels, axis=1), 95))
    blue_red = float(np.mean(pixels[:, 2] - pixels[:, 0]))
    outliers = np.max(np.abs(pixels - expected), axis=1) > limits["max_pixel_delta"]
    if float(outliers.mean()) > limits["max_outlier_fraction"]:
        raise ValueError("Local paint outliers exceed declared role tolerance")

    if np.max(np.abs(median - expected)) > delta:
        raise ValueError("Paint drifts from declared role " + role)
    if chroma > chroma_limit or abs(blue_red) > limits["max_abs_mean_blue_minus_red"]:
        raise ValueError("Named neutral paint retains a color cast")
    return {"role": role, "target_rgb": expected, "masked_UV_pixels": int(mask.sum()),
            "median_rgb": median.tolist(), "chroma_p95": chroma,
            "mean_blue_minus_red": blue_red, "outlier_pixels": int(outliers.sum()),
            "denominator": "named UV paint samples, not visible vehicle area"}


def masked_gloss(native, mask, *, factor, ceiling):
    """Apply an explicitly chosen target-local R adjustment; no style-wide filter."""
    array = np.asarray(native)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("Packed N needs uint8 RGBA")
    selected = binary(mask, "gloss mask", array.shape[:2])
    number(factor, "gloss factor", .000001, 1)
    number(ceiling, "gloss ceiling", 0, 255, True)
    result = array.copy()
    result[selected, 0] = np.uint8(np.minimum(np.rint(array[selected, 0].astype(float) * factor), ceiling))
    return result
