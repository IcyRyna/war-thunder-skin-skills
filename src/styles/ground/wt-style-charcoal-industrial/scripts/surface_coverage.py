"""Audit every declared native face and every UV alias; never trim a failing mask."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from numba import njit
from skill_contract import binary, checked_file, load_mask, policy, read_json, require_text


@njit(cache=False)
def _raster(uv, paint, target, accepted, renderable=None):
    height, width = paint.shape
    occupied = np.zeros(paint.shape, np.bool_)
    requested = np.zeros(paint.shape, np.bool_)
    unsafe = np.zeros(paint.shape, np.bool_)
    samples = np.zeros(len(uv), np.int64)
    missing = np.zeros(len(uv), np.int64)
    for face in range(len(uv)):
        if renderable is not None and not renderable[face]:
            continue
        q = uv[face]
        for tile_u in range(int(np.floor(q[:, 0].min())), int(np.floor(q[:, 0].max())) + 1):
            for tile_v in range(int(np.floor(q[:, 1].min())), int(np.floor(q[:, 1].max())) + 1):
                px = (q[:, 0] - tile_u) * width - .5
                py = (1 - q[:, 1] + tile_v) * height - .5
                x0, x1 = max(0, int(np.ceil(px.min()))), min(width - 1, int(np.floor(px.max())))
                y0, y1 = max(0, int(np.ceil(py.min()))), min(height - 1, int(np.floor(py.max())))
                den = (py[1]-py[2])*(px[0]-px[2]) + (px[2]-px[1])*(py[0]-py[2])
                if abs(den) < 1e-12:
                    continue
                for y in range(y0, y1+1):
                    for x in range(x0, x1+1):
                        a = ((py[1]-py[2])*(x-px[2])+(px[2]-px[1])*(y-py[2]))/den
                        b = ((py[2]-py[0])*(x-px[2])+(px[0]-px[2])*(y-py[2]))/den
                        if min(a, b, 1-a-b) < -1e-7:
                            continue
                        occupied[y, x] = True
                        samples[face] += 1
                        if target[face]:
                            requested[y, x] = True
                            if not paint[y, x]:
                                missing[face] += 1
                        if paint[y, x] and not (target[face] or accepted[face]):
                            unsafe[y, x] = True
    return occupied, requested, unsafe, samples, missing


def audit(positions, uvs, paint, groups, target_groups, accepted_shared=None,
          *, layer_role="honeycomb", mode="full_surface"):
    positions, uvs = np.asarray(positions, float), np.asarray(uvs, float)
    mask = binary(paint, "actual layer coverage")
    if (positions.ndim != 3 or positions.shape[1:] != (3, 3)
            or uvs.shape != (len(positions), 3, 2) or not len(positions)
            or not np.isfinite(positions).all() or not np.isfinite(uvs).all()):
        raise ValueError("Finite native triangles and matching UVs required")
    if not mask.any() or min(mask.shape) < 1 or max(mask.shape) > 8192:
        raise ValueError("Nonempty 1..8192 coverage mask required")
    area = np.linalg.norm(np.cross(positions[:, 1]-positions[:, 0], positions[:, 2]-positions[:, 0]), axis=1)
    uv_area = ((uvs[:, 1, 0]-uvs[:, 0, 0])*(uvs[:, 2, 1]-uvs[:, 0, 1])
               -(uvs[:, 1, 1]-uvs[:, 0, 1])*(uvs[:, 2, 0]-uvs[:, 0, 0]))
    renderable = area >= 1e-12
    degenerate_uv = renderable & (np.abs(uv_area) < 1e-12)
    # Retain every original face ID. Non-rendering geometry is accounted for;
    # collapsed UV on a real 3D surface remains a possible texture sampler.
    if np.any(np.ptp(np.floor(uvs), axis=1) > 2) or np.any(np.abs(uvs) > 10000):
        raise ValueError("UV span exceeds supported tiled raster range")
    rules = policy()["coverage"]
    if layer_role not in rules["allowed_roles"] or mode not in {"full_surface", "partial"}:
        raise ValueError("Unknown layer role or coverage mode")
    by_id, owner = {}, np.full(len(positions), -1, dtype=int)
    for index, group in enumerate(groups):
        name = require_text(group.get("id"), "face group ID")
        if name in by_id or group.get("role") not in rules["face_roles"]:
            raise ValueError("Duplicate group or unknown face role")
        faces = group.get("faces")
        if (not isinstance(faces, list) or not faces or any(type(f) is not int or not 0 <= f < len(positions) for f in faces)
                or len(set(faces)) != len(faces) or np.any(owner[faces] != -1)):
            raise ValueError("Face groups must partition the complete geometry without overlap")
        require_text(group.get("evidence"), "face group classification evidence")
        owner[faces] = index
        by_id[name] = group
    if np.any(owner < 0):
        raise ValueError("Unclassified native faces; include preserved and shared users")
    if not isinstance(target_groups, list) or not target_groups or len(set(target_groups)) != len(target_groups):
        raise ValueError("Explicit nonempty unique target groups required")
    accepted_shared = accepted_shared or {}
    if not isinstance(accepted_shared, dict) or set(target_groups) & set(accepted_shared):
        raise ValueError("Shared peers need distinct IDs and individual reasons")
    target, accepted = np.zeros(len(positions), bool), np.zeros(len(positions), bool)
    for name in target_groups + list(accepted_shared):
        if name not in by_id:
            raise ValueError("Unknown selected/shared face group: " + str(name))
        group = by_id[name]
        if group["role"] not in rules["allowed_roles"][layer_role]:
            raise ValueError(layer_role + " is forbidden on " + group["role"])
        if name in accepted_shared:
            require_text(accepted_shared[name], "shared peer appearance reason")
            accepted[group["faces"]] = True
        else:
            target[group["faces"]] = True
    if np.any(target & degenerate_uv):
        raise ValueError("Paint target has collapsed UV; resolve its constant/line sampling explicitly")
    occupied, requested, unsafe, samples, missing = _raster(uvs, mask, target, accepted, renderable)
    unmapped = mask & ~occupied
    outside = mask & ~requested
    counts = {"paint_texels": int(mask.sum()), "target_texels": int(requested.sum()),
              "missing_target_texels": int((requested & ~mask).sum()),
              "unauthorized_alias_texels": int(unsafe.sum()),
              "unmapped_texels": int(unmapped.sum()), "outside_target_texels": int(outside.sum())}
    zero = np.flatnonzero(target & renderable & (samples == 0)).tolist()
    # A subpixel alias can sample painted texels even when its triangle contains
    # no texel center. Conservatively check its bounding footprint, including a
    # one-texel linear-filter margin; uncertainty is not a clean bill of health.
    uncertain_aliases = []
    height, width = mask.shape
    for face in np.flatnonzero((~target) & renderable & (samples == 0)):
        q = uvs[face]
        overlap = False
        for tu in range(int(np.floor(q[:,0].min())), int(np.floor(q[:,0].max()))+1):
            for tv in range(int(np.floor(q[:,1].min())), int(np.floor(q[:,1].max()))+1):
                px = (q[:,0]-tu)*width-.5
                py = (1-q[:,1]+tv)*height-.5
                x0,x1 = max(0,int(np.floor(px.min()))-1), min(width,int(np.ceil(px.max()))+2)
                y0,y1 = max(0,int(np.floor(py.min()))-1), min(height,int(np.ceil(py.max()))+2)
                if x1>x0 and y1>y0 and mask[y0:y1,x0:x1].any():
                    overlap = True
        if overlap:
            uncertain_aliases.append(int(face))
    errors = []
    if uncertain_aliases:
        errors.append("Undersampled shared users intersect paint/filter footprint: " + str(uncertain_aliases[:20]))

    if zero:
        errors.append("Target faces have no sampled texels: " + str(zero[:20]))
    for field in ("unauthorized_alias_texels", "unmapped_texels", "outside_target_texels"):
        if counts[field]:
            errors.append(f"{field}: {counts[field]}")
    if mode == "full_surface" and counts["missing_target_texels"]:
        errors.append("Incomplete target surface: " + str(counts["missing_target_texels"]))
    details = []
    for name in target_groups:
        faces = by_id[name]["faces"]
        details.append({"id": name, "role": by_id[name]["role"],
                        "sample_hits": int(samples[faces].sum()),
                        "missing_hits": int(missing[faces].sum()),
                        "zero_sample_faces": [f for f in faces if samples[f] == 0 and renderable[f]]})
    return {"technical_pass": not errors, "mode": mode, "layer_role": layer_role,
            "counts": counts, "target_groups": details, "accepted_shared": accepted_shared,
            "errors": errors, "undersampled_alias_faces": uncertain_aliases,
            "non_rendering_native_faces": np.flatnonzero(~renderable).tolist(),
            "collapsed_uv_native_faces": np.flatnonzero(degenerate_uv).tolist(),
            "degenerate_policy": "all source IDs retained; collapsed UV intersecting paint/filter footprint is unresolved", "visual_review": "not inferred",
            "geometry_scope": "all supplied native users; completeness requires binding evidence"}


def audit_record(root, record):
    geometry_path = checked_file(root, record.get("geometry"), "all-user native geometry")
    checked_file(root, record.get("binding_evidence"), "native material/user binding")
    if record.get("all_texture_users_included") is not True:
        raise ValueError("Inventory every native user of this texture before coverage checks")
    mask = load_mask(root, record.get("paint_mask"), "actual/planned layer coverage")
    with np.load(geometry_path, allow_pickle=False) as geometry:
        result = audit(geometry["positions"], geometry["uvs"], mask, record.get("face_groups", []),
                       record.get("target_groups"), record.get("accepted_shared"),
                       layer_role=record.get("layer_role"), mode=record.get("mode"))
    result["geometry_sha256"] = record["geometry"]["sha256"]
    result["paint_mask_sha256"] = record["paint_mask"]["sha256"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = audit_record(args.record.resolve().parent, read_json(args.record))
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["technical_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
