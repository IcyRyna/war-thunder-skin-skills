"""Bind functional labels to one unit, true capabilities, source pixels and hashed evidence."""
from skill_contract import checked_file, require_text
import re


def normalize_label(text):
    return re.sub(r"[\s_\u2010-\u2015]+","-",str(text).strip()).casefold()


def check_label(asset,target_profile):
    text=asset.get("label_text");claims=asset.get("requires_capabilities",[])
    if text and asset.get("contains_text") is not True:
        raise ValueError("An equipment label cannot claim contains_text=False")
    if not text and not claims:return {"semantic_check":"no equipment assertion"}
    if not isinstance(target_profile,dict):raise ValueError("Functional label needs actual target profile")
    root=target_profile.get("_evidence_root")
    if not root:raise ValueError("Functional label requires resolved evidence root")
    capabilities=target_profile.get("capabilities",{})
    if not isinstance(capabilities,dict) or any(type(v) is not bool for v in capabilities.values()):
        raise ValueError("Capabilities must map names to actual booleans")
    if normalize_label(text or "") in {"blow-out","blowout"} and "ammunition_blowout_panels" not in claims:
        claims=[*claims,"ammunition_blowout_panels"]
    for claim in claims:
        if capabilities.get(claim) is not True:raise ValueError("Target does not confirm required equipment: "+claim)
        checked_file(root,target_profile.get("capability_evidence",{}).get(claim),"capability evidence")
    units=asset.get("approved_for_units",[])
    if units and target_profile.get("unit_id") not in units:raise ValueError("Equipment label belongs to another unit")
    if text:
        normalized=normalize_label(text)
        approved={normalize_label(v) for v in target_profile.get("approved_labels",[])}
        if normalized not in approved:raise ValueError("Target-specific label not approved")
        records=target_profile.get("label_evidence",{})
        proof=records.get(normalized)
        if not isinstance(proof,dict) or proof.get("unit_id")!=target_profile.get("unit_id") or proof.get("asset_sha256")!=asset.get("sha256") or normalize_label(proof.get("text",""))!=normalized:
            raise ValueError("Label proof must bind unit, text and the actual asset hash")
        require_text(proof.get("carrier"),"label carrier")
        checked_file(root,proof.get("evidence"),"label function/user selection evidence")
    return {"semantic_check":"target/asset/evidence matched","text":text,"required_capabilities":claims,"unit_id":target_profile.get("unit_id")}
