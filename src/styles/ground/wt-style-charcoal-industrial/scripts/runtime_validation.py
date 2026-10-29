"""Validate every delivered DDS, semantic mip chain, model slot and BLK target."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
import zipfile
import numpy as np
from PIL import Image
from dds_variant import decode_mips
from ground_dds import rewrite_blk
from texture_semantics import iter_mipmaps, validate_alpha_semantics, validate_color_space
from skill_contract import checked_file, read_json, require_text, number, sha
from package_budget import require_budget


def read_rgba(root, spec, label):
    path=checked_file(root,spec,label)
    with Image.open(path) as im:
        if im.mode!="RGBA":raise ValueError(label+" must be explicit RGBA8")
        return np.array(im)


def package_path(value):
    require_text(value,"package path")
    posix=PurePosixPath(value.replace("\\","/"));win=PureWindowsPath(value)
    if posix.is_absolute() or win.drive or win.root or any(p in {"",".",".."} or ":" in p or p.endswith((" ",".")) for p in value.replace("\\","/").split("/")):
        raise ValueError("Unsafe package path")
    return posix.as_posix()


def _normal_vectors(rgba):
    xy=rgba[:,:,[1,3]].astype(float)/127.5-1
    z=np.sqrt(np.maximum(1-np.sum(xy*xy,axis=-1),0))
    out=np.concatenate((xy,z[...,None]),axis=-1)
    return out/np.maximum(np.linalg.norm(out,axis=-1,keepdims=True),1e-12)


def encoding_limits(root,row):
    contract=row.get("encoding")
    if not isinstance(contract,dict) or contract.get("mode") not in {"exact","bounded"}:
        raise ValueError("Every DDS needs exact or bounded encoding contract")
    if contract["mode"]=="exact":return np.zeros(4),np.zeros(4),0.
    checked_file(root,contract.get("evidence"),"target encoding acceptance evidence")
    absolute,mean=contract.get("max_abs"),contract.get("max_mean")
    if not isinstance(absolute,list) or len(absolute)!=4 or not isinstance(mean,list) or len(mean)!=4:
        raise ValueError("Per-channel encoding bounds required")
    for value in absolute:number(value,"encoding maximum byte error",0,32)
    for value in mean:number(value,"encoding mean byte error",0,8)
    if np.any(np.asarray(mean)>absolute):raise ValueError("Mean error bound exceeds maximum")
    angle=number(contract.get("max_normal_angle_deg",0),"normal angle error",0,5)
    return np.array(absolute),np.array(mean),angle


def audit_encoding(root,row):
    path=checked_file(root,row.get("dds"),"runtime DDS")
    role=row.get("role")
    semantics=validate_alpha_semantics(row.get("alpha_semantics"),role)
    space=validate_color_space(row.get("color_space"),semantics)
    meta,mips=decode_mips(path)
    expected_srgb=space=="srgb"
    if (meta["dxgi"] in {29,78,99})!=expected_srgb:
        raise ValueError("DDS color-space tag differs from declared role: "+path.name)
    allowed_alpha={4} if role in {"normal","ao"} else ({1,3,4} if semantics=="fixed_rgb" else {1,4})
    if meta["alpha_mode"] not in allowed_alpha:
        raise ValueError("Unsupported alpha-mode for declared data/color semantics")
    if meta["alpha_mode"]==3 and any(np.any(m[...,3]!=255) for m in mips):
        raise ValueError("Opaque DDS alpha-mode has nonopaque decoded pixels")
    canonical=read_rgba(root,row.get("canonical"),"post-edit pre-encoding canonical pixels")
    limits,means,angle_limit=encoding_limits(root,row)
    if canonical.shape!=mips[0].shape:raise ValueError("Canonical and DDS dimensions differ")
    reports=[]
    expected=list(iter_mipmaps(Image.fromarray(canonical),semantics,space))
    if len(expected)!=len(mips):raise ValueError("Semantic and decoded mip inventories differ")
    for level,(im,actual) in enumerate(zip(expected,mips)):
        source=np.asarray(im)
        delta=np.abs(actual.astype(np.int16)-source.astype(np.int16))
        maximum,average=delta.max(axis=(0,1)),delta.mean(axis=(0,1))
        if np.any(maximum>limits) or np.any(average>means):
            raise ValueError(f"{path.name} mip {level}: encoding error exceeds per-channel contract")
        angle=0.
        if role=="normal":
            a,b=_normal_vectors(source),_normal_vectors(actual)
            angle=float(np.degrees(np.arccos(np.clip(np.sum(a*b,axis=-1),-1,1))).max())
            if angle>angle_limit+1e-5:
                raise ValueError(f"{path.name} mip {level}: normal direction error exceeds contract")
        reports.append({"level":level,"size":[actual.shape[1],actual.shape[0]],
            "max_abs":maximum.tolist(),"mean_abs":average.tolist(),"normal_angle_max_deg":angle,
            "decoded_rgba_sha256":hashlib.sha256(actual.tobytes()).hexdigest(),
            "canonical_mip_sha256":hashlib.sha256(source.tobytes()).hexdigest()})
    state=row.get("state")
    if state not in {"preserve","modified"}:raise ValueError("DDS state must be preserve or modified")
    if state=="preserve":
        baseline=read_rgba(root,row.get("baseline"),"preserved source pixels")
        if not np.array_equal(baseline,canonical):
            raise ValueError("Preserve DDS has changed canonical pixels")
    return {"id":row["id"],"path":str(path),"role":role,"state":state,"metadata":meta,
            "mips":reports,"canonical_sha256":row["canonical"]["sha256"],"dds_sha256":row["dds"]["sha256"]}


def audit_runtime(root,data):
    outputs=data.get("final_runtime_files")
    if not isinstance(outputs,list) or not outputs:raise ValueError("Explicit final runtime list required")
    packaged,by_path={},{}
    for spec in outputs:
        path=checked_file(root,spec,"final runtime file")
        target=package_path(spec.get("package_path"))
        if path.suffix.lower() not in {".dds",".blk"}:
            if spec.get("kind")!="native_model_dependency" or path.suffix.lower() not in {".bin",".grp"}:
                raise ValueError("Runtime list cannot contain source projects, images, logs or arbitrary text")
            checked_file(root,spec.get("dependency_evidence"),"actual native model dependency")
        if target.casefold() in {p.casefold() for p in packaged} or str(path) in by_path:
            raise ValueError("Duplicate runtime file or case-insensitive package path")
        packaged[target]=spec;by_path[str(path)]=target
    blks=[(name,spec) for name,spec in packaged.items() if PurePosixPath(name).suffix.lower()==".blk"]
    if len(blks)!=1:raise ValueError("Exactly one vehicle BLK per audited skin")
    blk_name,blk_spec=blks[0];blk_dir=PurePosixPath(blk_name).parent
    rows=data.get("runtime_textures")
    if not isinstance(rows,list) or not rows:raise ValueError("Every delivered DDS needs a role/encoding/state declaration")
    seen,declared,textures,reports=set(),set(),{},[]
    bindings=read_json(checked_file(root,data["bindings"],"native model slots"))
    if bindings.get("unit_id")!=data["unit_id"] or bindings.get("model_sha256")!=data["model"]["sha256"]:
        raise ValueError("Native slot inventory belongs to a different model/unit")
    slots={}
    for slot in bindings.get("resources",[]):
        name=require_text(slot.get("resource"),"native resource").rstrip("*").casefold()
        if name in slots or slot.get("role") not in {"color","normal","ao"} or not slot.get("users"):
            raise ValueError("Duplicate/incomplete native resource and user inventory")
        require_text(slot.get("shader"),"native resource shader")
        slots[name]=slot
    for row in rows:
        identifier=require_text(row.get("id"),"runtime texture ID")
        path=checked_file(root,row.get("dds"),"declared DDS")
        if identifier in seen or str(path) in declared:raise ValueError("Duplicate runtime texture declaration")
        seen.add(identifier);declared.add(str(path))
        if str(path) not in by_path:raise ValueError("Declared DDS missing from final runtime list")
        pkg=PurePosixPath(by_path[str(path)])
        try:rel=pkg.relative_to(blk_dir)
        except ValueError as exc:raise ValueError("BLK texture package target escapes skin directory") from exc
        textures[rel.as_posix().casefold()]={"file":rel,"output":rel,"role":row["role"],"record":row}
        reports.append(audit_encoding(root,row))
    actual_dds={str(checked_file(root,spec,"packaged DDS")) for name,spec in packaged.items() if PurePosixPath(name).suffix.lower()==".dds"}
    if actual_dds!=declared:raise ValueError("Unreviewed/missing runtime DDS")
    text=checked_file(root,blk_spec,"final BLK").read_text(encoding="utf-8-sig")
    _,mappings=rewrite_blk(text,textures)
    for mapping in mappings:
        slot=slots.get(mapping["resource"].rstrip("*").casefold())
        row=textures[mapping["target"].casefold()]["record"]
        if slot is None or slot["role"]!=row["role"]:
            raise ValueError("BLK source missing from native model or C/N/AO slot role mismatch")
        for field in ("alpha_semantics","color_space"):
            if slot.get(field)!=row.get(field):
                raise ValueError("DDS declaration disagrees with native slot "+field)
    if data.get("schema_version")==3:
        for target,info in textures.items():
            actual=sorted({m["resource"].rstrip("*").casefold() for m in mappings if m["target"].casefold()==target})
            if sorted(info["record"].get("native_resources",[]))!=actual:
                raise ValueError("Runtime native_resources differ from actual BLK mapping")
    return {"dds_semantics_pass":True,"runtime_identity_pass":True,"mappings":mappings,"textures":reports,
            "runtime_file_count":len(outputs),"package_paths":sorted(packaged)}


def audit_delivery(root,data,archive):
    runtime=audit_runtime(root,data)
    budget=require_budget(archive)
    expected={package_path(spec["package_path"]):spec for spec in data["final_runtime_files"]}
    with zipfile.ZipFile(archive) as z:
        members=[m for m in z.infolist() if not m.is_dir()]
        if {m.filename for m in members}!=set(expected) or len(members)!=len(expected):
            raise ValueError("Delivered ZIP has extra, missing or differently located runtime members")
        for member in members:
            digest=hashlib.sha256()
            with z.open(member) as stream:
                for chunk in iter(lambda:stream.read(1048576),b""):digest.update(chunk)
            if digest.hexdigest()!=expected[member.filename]["sha256"]:
                raise ValueError("Delivered ZIP member differs from reviewed runtime: "+member.filename)
        # The streamed BLK is now byte-identical to the strictly parsed native-slot mapping above.
    return {"technical_pass":True,"budget_pass":True,"runtime_identity_pass":True,"dds_semantics_pass":True,
            "zip_sha256":sha(archive),"members_checked":len(expected),
            "zip_bytes":budget["zip_bytes"],"expanded_bytes":budget["expanded_bytes"],
            "native_mappings":runtime["mappings"],"game_validation":"not inferred"}
