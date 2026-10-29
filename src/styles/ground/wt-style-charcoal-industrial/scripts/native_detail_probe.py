"""Measure declared native-detail samples on the same normalized UV grid.

This is a local pixel diagnostic, not automatic component classification,
whole-surface coverage, semantic approval, or a substitute for the model view.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from skill_contract import checked_file, load_mask, number, read_json, require_text


def rgba(path, channels="RGB"):
    with Image.open(path) as image:
        if image.mode not in {"RGB", "RGBA"}:
            raise ValueError("Native detail sources must be RGB or RGBA images")
        if "A" in channels and image.mode != "RGBA":
            raise ValueError("Alpha comparison requires actual RGBA source data")
        return np.array(image.convert("RGBA"))


def measure(reference, current, mask, channels, tolerance=0):
    """Sample current pixels at reference texel centers; never invent new UVs."""
    if (reference.ndim != 3 or current.ndim != 3 or reference.shape[2] != 4
            or current.shape[2] != 4 or reference.dtype != np.uint8 or current.dtype != np.uint8):
        raise ValueError("RGBA uint8 pixels required")
    if mask.shape != reference.shape[:2] or mask.dtype != np.bool_ or not mask.any():
        raise ValueError("A nonempty binary mask on the reference grid is required")
    if (not isinstance(channels, str) or not channels or len(set(channels)) != len(channels)
            or not set(channels) <= set("RGBA")):
        raise ValueError("Declare unique RGBA channel letters explicitly")
    tolerance = number(tolerance, "max_abs_error", 0, 255, integer=True)
    y, x = np.nonzero(mask)
    yy = ((2 * y + 1) * current.shape[0]) // (2 * reference.shape[0])
    xx = ((2 * x + 1) * current.shape[1]) // (2 * reference.shape[1])
    a, b = reference[y, x], current[yy, xx]
    indices = ["RGBA".index(c) for c in channels]
    delta = np.abs(a[:, indices].astype(np.int16) - b[:, indices].astype(np.int16))
    return {"reference_size": list(reference.shape[1::-1]), "current_size": list(current.shape[1::-1]),
            "sampled_reference_pixels": len(x), "unique_current_pixels": int(len(np.unique(np.c_[yy, xx], axis=0))),
            "mapping": "same_normalized_uv_texel_centers", "channels": channels,
            "max_abs_error": {c: int(delta[:, i].max()) for i, c in enumerate(channels)},
            "mean_abs_error": {c: float(delta[:, i].mean()) for i, c in enumerate(channels)},
            "changed_pixels": int(np.any(delta != 0, axis=1).sum()),
            "outside_tolerance_pixels": int(np.any(delta > tolerance, axis=1).sum()),
            "declared_tolerance": tolerance, "within_tolerance": bool(np.all(delta <= tolerance)),
            "reference_mean_rgb": a[:, :3].mean(axis=0).tolist(), "current_mean_rgb": b[:, :3].mean(axis=0).tolist(),
            "reference_mean_chroma": float(np.ptp(a[:, :3].astype(np.int16), axis=1).mean()),
            "current_mean_chroma": float(np.ptp(b[:, :3].astype(np.int16), axis=1).mean())}


def probe(root, data):
    if data.get("schema_version") != 1 or not isinstance(data.get("samples"), list) or not data["samples"]:
        raise ValueError("Native detail probe requires schema_version 1 and nonempty samples")
    rows, ids = [], set()
    for row in data["samples"]:
        identifier = require_text(row.get("id"), "native detail sample id")
        if identifier in ids:
            raise ValueError("Duplicate native detail sample id")
        ids.add(identifier)
        if row.get("mapping") != "same_normalized_uv_texel_centers":
            raise ValueError("This probe only supports verified same-normalized-UV samples")
        require_text(row.get("physical_location"), "observed physical location")
        action = row.get("action")
        if action not in {"retain", "recolor", "extract_recompose", "replace", "remove", "inspect"}:
            raise ValueError("Unknown native detail action")
        channels = row.get("channels")
        if not isinstance(channels, str):
            raise ValueError("Declare the sampled channels")
        reference = rgba(checked_file(root, row.get("reference"), "native detail reference"), channels)
        current = rgba(checked_file(root, row.get("current"), "native detail current"), channels)
        mask = load_mask(root, row.get("mask"), "native detail sample mask", reference.shape[:2])
        stats = measure(reference, current, mask, row.get("channels"), row.get("max_abs_error", 0))
        rows.append({"id": identifier, "action": action, "physical_location": row["physical_location"], **stats,
                     "retention_claim": ("supported_for_sample" if stats["within_tolerance"] else "contradicted")
                     if action == "retain" else "not_asserted"})
    return {"samples": rows, "retention_failures": [r["id"] for r in rows if r["retention_claim"] == "contradicted"],
            "scope": "declared samples and channels only; no automatic classification, full-surface, artwork or game approval"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.manifest.resolve().parent, read_json(args.manifest))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"samples": len(result["samples"]), "retention_failures": result["retention_failures"]}, ensure_ascii=False))
    return 2 if result["retention_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
