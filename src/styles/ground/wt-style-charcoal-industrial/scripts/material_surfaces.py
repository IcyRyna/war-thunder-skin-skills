"""Tie material sampling and preserved equipment to complete physical surfaces."""
from __future__ import annotations
import numpy as np
from skill_contract import checked_file,load_mask,read_json,require_text
from runtime_validation import read_rgba

def audit_material_surfaces(root,data,native):
    textures={t["id"]:t for t in data["textures"]}
    runtime={r["id"]:r for r in data["runtime_textures"]}
    occupied=set();reports=[]
    for material in data["materials"]:
        if material["state"]!="paint":continue
        surfaces=material.get("surfaces")
        if not isinstance(surfaces,list) or not surfaces:raise ValueError("Paint material needs physical surface identities")
        seen=set()
        for surface in surfaces:
            sid=require_text(surface.get("id"),"material surface ID")
            if sid in seen:raise ValueError("Duplicate material surface ID")
            seen.add(sid)
            ids=native.selected(surface["coverage_id"],surface.get("group_ids"))
            tokens=set(map(int,ids))
            if occupied&tokens:raise ValueError("Physical faces assigned to overlapping painted materials")
            occupied|=tokens
            cs=[s for s in material["color_samples"] if s.get("surface_id")==sid]
            ns=[s for s in material["final_samples"] if s.get("surface_id")==sid]
            if len(cs)!=1 or len(ns)!=1:raise ValueError("Each material surface needs exactly one complete C/N pair")
            c,n=cs[0],ns[0];texture=textures[c["texture"]]
            cr=next((r for r in runtime.values() if r["dds"]["sha256"]==texture["final_dds"]["sha256"] and r["role"]=="color"),None)
            nr=runtime.get(n.get("runtime_texture_id"))
            if cr is None or nr is None or nr["role"]!="normal" or nr["dds"]["sha256"]!=n["final_n_dds"]["sha256"]:
                raise ValueError("Material surface points to wrong runtime C/N")
            cresource=surface.get("color_resource");nresource=surface.get("normal_resource")
            if cresource not in cr.get("native_resources",[]) or nresource not in nr.get("native_resources",[]):
                raise ValueError("Material physical resource differs from actual BLK mapping")
            ca=read_rgba(root,cr["canonical"],"material canonical C")
            na=read_rgba(root,nr["canonical"],"material canonical N")
            cm=native.mask(ids,cresource,ca.shape[:2]);nm=native.mask(ids,nresource,na.shape[:2])
            decoration=load_mask(root,texture["decoration_mask"],"actual decoration",cm.shape)
            actual_c=load_mask(root,c["mask"],"material C scope",cm.shape)
            actual_n=load_mask(root,n["mask"],"material N scope",nm.shape)
            if not np.array_equal(actual_c,cm&~decoration):raise ValueError("Material C samples omit or exceed the complete physical surface")
            if not np.array_equal(actual_n,nm):raise ValueError("Material N samples omit or exceed the complete physical surface")
            mapping=n.get("uv_mapping",{})
            if mapping.get("color_texture")!=c["texture"]:raise ValueError("Material UV correspondence uses another C resource")
            same=np.array_equal(native.source["uvs"][ids],native.source["uvs_normal"][ids])
            if mapping.get("mode")=="same_native_uv" and not same:raise ValueError("Independent native UV cannot claim same_native_uv")
            if mapping.get("mode")=="independent_uv":
                claim=read_json(checked_file(root,mapping["normal_coverage"],"independent N coverage"))
                native.geometry(claim,"normal")
                if n["coverage_id"]!=surface["coverage_id"]:raise ValueError("Independent N maps a different physical surface")
            reports.append({"material":material["role"],"surface":sid,"native_faces":len(ids),"C_pixels":int(actual_c.sum()),"N_pixels":int(nm.sum())})
        if any(s.get("surface_id") not in seen for s in material["color_samples"]+material["final_samples"]):
            raise ValueError("Orphan material sample")
    return reports

def audit_equipment_pixels(root,data,native):
    reports=[]
    for equipment in data.get("sensitive_equipment",[]):
        evidence=read_json(checked_file(root,equipment["classification_evidence"],"component classification"))
        whole=native.selected(equipment["coverage_id"],equipment["equipment_group_ids"])
        if evidence.get("unit_id")!=data["unit_id"] or evidence.get("model_sha256")!=data["model"]["sha256"] or sorted(evidence.get("equipment_source_faces",[]))!=sorted(whole.tolist()):
            raise ValueError("Equipment classification does not bind current native faces/model/unit")
        for name,component in equipment["components"].items():
            if component["state"]=="not_present":continue
            ids=native.selected(equipment["coverage_id"],component["group_ids"])
            if sorted(evidence.get("components",{}).get(name,[]))!=sorted(ids.tolist()):
                raise ValueError("Equipment component classification differs from native face assignment")
            if component["state"]!="preserve":continue
            checked=0;bound_regions=0;pixel_count=0
            for row in data["runtime_textures"]:
                a=read_rgba(root,row["canonical"],"protected equipment canonical")
                b=read_rgba(root,row["baseline"],"protected equipment baseline")
                for resource in row["native_resources"]:
                    native_ids=native.resources[resource]["face_ids"]
                    shared=np.intersect1d(ids,native_ids)
                    if not len(shared):continue
                    bound_regions+=1
                    mask=native.mask(shared,resource,a.shape[:2])
                    if not mask.any():continue
                    if a.shape!=b.shape or not np.array_equal(a[mask],b[mask]):
                        raise ValueError("Preserved equipment component changed canonical pixels: "+equipment["id"]+"/"+name)
                    if row["role"]=="color":
                        for texture in data["textures"]:
                            if texture["final_dds"]["sha256"]==row["dds"]["sha256"] and np.any(mask&load_mask(root,texture["decoration_mask"],"equipment decoration",mask.shape)):
                                raise ValueError("Decoration intrudes on preserved equipment")
                    checked+=1;pixel_count+=int(mask.sum())
            if bound_regions and not checked:raise ValueError('Protected equipment has a runtime override but zero native pixel samples')
            reports.append({"equipment":equipment["id"],"component":name,"native_faces":len(ids),"runtime_regions_checked":checked,
                            "pixels_checked":pixel_count,"status":"pixels_verified" if checked else ("no_native_samples" if bound_regions else "no_runtime_override"),
                            "unchanged":True if checked else None,
                            "scope":"actual runtime pixels" if checked else ("runtime override exists but no native samples were compared" if bound_regions else "native resource inherited; no pixel comparison was performed")})
    return reports
