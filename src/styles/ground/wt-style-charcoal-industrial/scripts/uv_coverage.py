"""Check complete UV classification and immutable pixels outside explicit edits."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from skill_contract import binary, load_mask, read_json
from surface_coverage import audit_record


def check(occupied, paint, protected, before, after, shared=None, shared_allowed=None):
    occupied = binary(occupied, "occupied")
    paint = binary(paint, "paint", occupied.shape)
    protected = binary(protected, "protected", occupied.shape)
    before, after = np.asarray(before), np.asarray(after)
    if (before.shape != after.shape or before.shape != occupied.shape+(4,)
            or before.dtype != np.uint8 or after.dtype != np.uint8):
        raise ValueError("Matching RGBA8 originals and outputs required")
    if not occupied.any():
        raise ValueError("Occupied mask is empty")
    sharing_checked = shared is not None
    shared = np.zeros(occupied.shape, bool) if shared is None else binary(shared, "shared", occupied.shape)
    allowed = np.zeros(occupied.shape, bool) if shared_allowed is None else binary(shared_allowed, "reviewed shared", occupied.shape)
    if np.any(allowed & ~shared):
        raise ValueError("Reviewed aliases must be a subset of actual shared pixels")
    changed = np.any(after != before, axis=2)
    diagnostics = {
        "unclassified": occupied & ~(paint | protected),
        "overlap": paint & protected,
        "outside-occupied": (paint | protected) & ~occupied,
        "protected-changed": protected & changed,
        "outside-paint-changed": ~paint & changed,
        "alpha-changed": before[..., 3] != after[..., 3],
        "shared-paint": shared & paint & ~allowed,
        "unchanged-paint": paint & ~changed,
    }
    failures = [value.any() for key, value in diagnostics.items() if key != "unchanged-paint"]
    counts = {key.replace("-", "_"): int(value.sum()) for key, value in diagnostics.items()}
    counts.update(occupied=int(occupied.sum()), paint=int(paint.sum()), protected=int(protected.sum()))
    return {"counts": counts, "sharing_checked": sharing_checked,
            "technical_pass": sharing_checked and not any(failures),
            "shared_proof": "caller must supply allowed aliases only from a successful native face audit",
            "visual_review": "pending; unchanged paint is diagnostic, not an automatic failure"}, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("occupied", "paint", "protected", "before", "after", "shared", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--scope-record", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    arrays = {}
    for name in ("occupied", "paint", "protected", "shared", "before", "after"):
        with Image.open(getattr(args, name)) as image:
            expected = "RGBA" if name in {"before", "after"} else "L"
            if image.mode != expected:
                raise ValueError(name + " must have mode " + expected)
            arrays[name] = np.array(image)
    allowed = None
    if args.scope_record:
        record = read_json(args.scope_record)
        result = audit_record(args.scope_record.resolve().parent, record)
        measured = load_mask(args.scope_record.resolve().parent, record["paint_mask"], "audited scope")
        if not result["technical_pass"] or not np.array_equal(measured, arrays["paint"] > 0):
            raise ValueError("Scope proof does not cover this exact paint mask")
        allowed = measured & (arrays["shared"] > 0)
    report, diagnostics = check(*(arrays[n] for n in ("occupied", "paint", "protected", "before", "after")),
                                shared=arrays["shared"], shared_allowed=allowed)
    args.out.mkdir(parents=True)
    for name, mask in diagnostics.items():
        Image.fromarray(np.uint8(mask)*255).save(args.out/(name+".png"))
    (args.out/"report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["technical_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
