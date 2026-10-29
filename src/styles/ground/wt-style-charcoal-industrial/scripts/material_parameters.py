"""Apply explicit R/B with optional RNM microstructure; preserve outside pixels exactly."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from skill_contract import binary, checked_file, load_mask, material_parameters, read_json


def _normal_xy(packed):
    x = packed[..., 1].astype(float)/127.5-1
    y = packed[..., 3].astype(float)/127.5-1
    z = np.sqrt(np.maximum(1-x*x-y*y, 0))
    vector = np.stack((x,y,z), axis=-1)
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-12)


def apply_parameters(native, mask, record, *, detail_normal=None, detail_coverage=None):
    params = material_parameters(record)
    if params["state"] != "paint":
        raise ValueError("Only explicit paint materials may be applied")
    native = np.asarray(native)
    if native.dtype != np.uint8 or native.ndim != 3 or native.shape[2] != 4:
        raise ValueError("Native packed N must be RGBA8")
    mask = binary(mask, "material mask", native.shape[:2])
    if not mask.any():
        raise ValueError("Empty material selection")
    output = native.copy()
    output[mask, 0] = params["inverse_roughness_center"]
    output[mask, 2] = params["metallic"]
    if (detail_normal is None) != (detail_coverage is None):
        raise ValueError("Micro-normal needs a separate coverage map")
    if detail_normal is not None:
        detail = np.asarray(detail_normal)
        coverage = np.asarray(detail_coverage)
        if (detail.dtype != np.uint8 or detail.shape != native.shape[:2]+(3,)
                or coverage.dtype != np.uint8 or coverage.shape != mask.shape):
            raise ValueError("Micro-normal RGB8 and coverage L8 must match native N dimensions")
        if np.any((coverage > 0) & ~mask):
            raise ValueError("Micro-normal coverage escapes declared material")
        d = detail.astype(float)/127.5-1
        lengths = np.linalg.norm(d, axis=-1)
        selected = coverage > 0
        if not selected.any() or np.max(np.abs(lengths[selected]-1)) > .02 or np.any(d[selected,2] < 0):
            raise ValueError("Micro-normal must contain valid unit tangent vectors")
        d /= np.maximum(lengths[...,None], 1e-12)
        strength = coverage[...,None].astype(float)/255
        flat = np.zeros_like(d);flat[...,2] = 1
        d = flat*(1-strength)+d*strength
        d /= np.maximum(np.linalg.norm(d,axis=-1,keepdims=True), 1e-12)
        # Reoriented normal mapping composes microdetail without replacing structural normals.
        t = _normal_xy(native);t[...,2] += 1
        u = d * np.array([-1.,-1.,1.])
        result = t * (np.sum(t*u,axis=-1)/t[...,2])[...,None] - u
        result /= np.maximum(np.linalg.norm(result,axis=-1,keepdims=True), 1e-12)
        output[selected,1] = np.rint(np.clip(result[selected,0]*127.5+127.5,0,255)).astype("uint8")
        output[selected,3] = np.rint(np.clip(result[selected,1]*127.5+127.5,0,255)).astype("uint8")
    if not np.array_equal(output[~mask], native[~mask]):
        raise AssertionError("Material escaped its declared region")
    return output


def audit_parameters(before, after, mask, record, micro_mask=None, tolerance=5):
    params = material_parameters(record)
    before, after = np.asarray(before), np.asarray(after)
    if (before.dtype != np.uint8 or after.dtype != np.uint8 or before.shape != after.shape
            or before.ndim != 3 or before.shape[2] != 4):
        raise ValueError("Matching native RGBA8 packed N required")
    mask = binary(mask, "material mask", before.shape[:2])
    if not mask.any() or params["state"] != "paint":
        raise ValueError("Audit requires a nonempty painted material")
    micro = np.zeros(mask.shape,bool) if micro_mask is None else binary(micro_mask,"micro-normal mask",mask.shape)
    if np.any(micro & ~mask):
        raise ValueError("Micro-normal mask escapes material")
    if type(tolerance) not in (int,float) or not np.isfinite(tolerance) or not 0 <= tolerance <= 5:
        raise ValueError("R/B audit tolerance must be 0..5")
    variation = record.get("variation", {})
    if variation:
        from skill_contract import require_text, number
        require_text(record.get("variation_reason"), "declared material variation")
        if set(variation) - {"R_max_delta", "B_max_delta"}:
            raise ValueError("Unknown material variation parameter")
        for value in variation.values():
            number(value, "material variation", 0, 64)
    r_limit = variation.get("R_max_delta", tolerance)
    b_limit = variation.get("B_max_delta", tolerance)
    r_outliers = int((np.abs(after[mask,0].astype(float)-params["inverse_roughness_center"]) > r_limit).sum())
    b_outliers = int((np.abs(after[mask,2].astype(float)-params["metallic"]) > b_limit).sum())
    r, b = float(np.median(after[mask,0])), float(np.median(after[mask,2]))
    checks = {"R_local_range": r_outliers == 0, "B_local_range": b_outliers == 0, "outside_exact": np.array_equal(before[~mask],after[~mask]),
              "structural_xy_exact": np.array_equal(before[~micro][:,[1,3]],after[~micro][:,[1,3]]),
              "R_matches": abs(r-params["inverse_roughness_center"]) <= tolerance,
              "B_matches": abs(b-params["metallic"]) <= tolerance}
    return {"technical_pass": bool(all(checks.values())), "checks": {k:bool(v) for k,v in checks.items()},
            "median_R": r, "median_B": b, "R_outlier_pixels": r_outliers, "B_outlier_pixels": b_outliers, "normal_changed_texels": int(np.any(before[:,:,[1,3]]!=after[:,:,[1,3]],axis=-1).sum()),
            "visual_review": "pending; final DDS compression and lighting separately checked"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args=parser.parse_args()
    data=read_json(args.record);root=args.record.resolve().parent
    with Image.open(checked_file(root,data["native_n"],"native N")) as im:
        if im.mode!="RGBA":raise ValueError("Do not convert packed N through display alpha")
        native=np.array(im)
    mask=load_mask(root,data["mask"],"material mask",native.shape[:2])
    extra={}
    if "detail_normal" in data:
        for field in ("detail_normal","detail_coverage"):
            with Image.open(checked_file(root,data[field],field)) as im:extra[field]=np.array(im)
    result=apply_parameters(native,mask,data["material"],**extra)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("xb") as stream:Image.fromarray(result).save(stream,format="PNG")
    print(json.dumps({"output":str(args.out),"outside_exact":True,"normal_method":"RNM" if extra else "G/A preserved"}))


if __name__=="__main__":
    main()
