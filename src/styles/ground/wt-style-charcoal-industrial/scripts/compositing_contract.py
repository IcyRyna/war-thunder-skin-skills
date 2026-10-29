"""Explicit C-only rounding contract for verified normal editor compositing."""
from __future__ import annotations
import numpy as np
from PIL import Image
from skill_contract import checked_file,read_json
from runtime_validation import read_rgba

def audit_composite(root,texture,expected,canonical,canonical_spec):
    if np.array_equal(expected,canonical):return {"mode":"exact","different_pixels":0}
    contract=texture.get("compositing",{})
    if contract.get("mode")!="composa_normal_u8":raise ValueError("Canonical final C is not the reviewed base plus actual qualified layers")
    proof=read_json(checked_file(root,contract.get("receipt"),"actual editor compositing receipt"))
    if proof.get("engine")!="Composa" or proof.get("version")!="1.4.0":
        raise ValueError("Unverified editor compositing implementation")
    expected_layers=[r["rgba"]["sha256"] for r in texture.get("layers",[])]
    if proof.get("layer_sha256")!=expected_layers or proof.get("canonical_sha256")!=canonical_spec["sha256"]:
        raise ValueError("Editor rounding receipt does not bind actual layers/canonical")
    for field in ("saved_export","reopened_export"):
        pixels=read_rgba(root,proof.get(field),"verified editor "+field)
        if not np.array_equal(pixels,canonical):raise ValueError("Editor save/reopen proof changed actual pixels")
    uncertain=np.zeros(expected.shape[:2],bool)
    for layer in texture.get("layers",[]):
        with Image.open(checked_file(root,layer["rgba"],"actual layer")) as image:a=np.array(image)[...,3]
        uncertain=(uncertain&(a<255))|((a>0)&(a<255))
    diff=np.abs(expected.astype(np.int16)-canonical.astype(np.int16))
    if np.any(diff[...,3]) or np.any(diff[~uncertain]) or np.any(diff[...,:3]>1):
        raise ValueError("Editor difference exceeds one RGB rounding step on actual fractional-Alpha composites")
    return {"mode":"composa_normal_u8","different_pixels":int(np.any(diff,axis=-1).sum()),
            "maximum_RGB_error":int(diff[...,:3].max()),"alpha_exact":True,
            "scope":"C compositing only; native protected pixels and N/AO remain exact"}
