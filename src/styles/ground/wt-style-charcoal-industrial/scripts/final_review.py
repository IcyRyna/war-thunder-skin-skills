"""Final production audit: exact canonical edits, then measured encoding, then native binding."""
from __future__ import annotations
import numpy as np
from PIL import Image
from dds_variant import decode_mips
from skill_contract import checked_file, load_mask, material_parameters, require_text, read_json
from runtime_validation import audit_runtime, read_rgba
from decoration_proof import audit_layers
from reference_contract import check_base_color, check_roles
from material_parameters import audit_parameters
from uv_coverage import check as check_uv
from surface_coverage import audit_record
from production_checks import validate_observations, audit_channel_repair


def validate_final(root,data,textures,coverage,materials,native):
    runtime=audit_runtime(root,data)
    rows={str(checked_file(root,row["dds"],"runtime DDS")):row for row in data["runtime_textures"]}
    def resolve(dds_spec,decoded_spec,role):
        path=checked_file(root,dds_spec,"actual runtime DDS")
        row=rows.get(str(path))
        if row is None or row["role"]!=role:raise ValueError("C/N/AO reference not in matching runtime role")
        _,mips=decode_mips(path)
        decoded=read_rgba(root,decoded_spec,"actual final DDS decoded PNG")
        if not np.array_equal(mips[0],decoded):raise ValueError("Final decoded pixels differ from actual DDS")
        return row,read_rgba(root,row["canonical"],"post-edit canonical"),str(path)
    result={"runtime":runtime,"final_paint":{},"final_protection":{},"final_materials":[]}
    canonical_colors={};used_colors=set();graphic_receipts=[]
    for name,texture in textures.items():
        row,canonical,key=resolve(texture["final_dds"],texture["final_c"],"color")
        used_colors.add(key);canonical_colors[name]=canonical
        before=read_rgba(root,texture["before_c"],"before C")
        if row.get("baseline",{}).get("sha256")!=texture["before_c"]["sha256"]:
            raise ValueError("Runtime C baseline differs from canonical edit baseline")
        if before.shape!=canonical.shape:raise ValueError("C dimensions/channels differ")
        shape=before.shape[:2]
        decoration,expected,receipts=audit_layers(root,data,texture,coverage)
        graphic_receipts.extend(receipts)
        from compositing_contract import audit_composite
        result.setdefault("compositing",{})[name]=audit_composite(root,texture,expected,canonical,row["canonical"])
        base_scope=load_mask(root,texture["base_paint_mask"],"base scope",shape)
        base_regions={}
        for region in texture["paint_regions"]:
            ident=require_text(region.get("id"),"base region ID")
            if ident in base_regions:raise ValueError("Duplicate base paint region ID")
            base_regions[ident]=region
        union=np.zeros(shape,bool);seen=set();stats=[]
        for region in texture.get("final_paint_regions",[]):
            ident=region.get("base_region_id")
            if ident not in base_regions or ident in seen:raise ValueError("Final paint must reference each actual base region once")
            seen.add(ident);base=base_regions[ident]
            mask=load_mask(root,region["mask"],"final paint",shape)
            inherited=load_mask(root,base["mask"],"original paint region",shape)&~decoration
            if not np.array_equal(mask,inherited):raise ValueError("Final paint region changed identity or discarded undeclared pixels")
            if region.get("role")!=base["role"]:raise ValueError("Final paint role differs from original geometry role")
            if np.any(union&mask):raise ValueError("Final paint role overlap")
            union|=mask
            if mask.any():
                stats.append(check_base_color(canonical,mask,role=base["role"],reference=base.get("rgb"),override_reason=base.get("override_reason")))
        if seen!=set(base_regions) or not np.array_equal(union,base_scope&~decoration):
            raise ValueError("Final paint regions omit actual A/B/C/F regions")
        result["final_paint"][name]=stats
        masks=[load_mask(root,texture[field],field,shape) for field in ("occupied_mask","edit_mask","protected_mask","shared_mask")]
        allowed=np.zeros(shape,bool)
        for claim in coverage.values():
            if claim["texture"]==name:allowed|=load_mask(root,claim["paint_mask"],"native scope",shape)
        if np.any(masks[1]&~allowed):raise ValueError("Canonical edits exceed audited native carriers")
        report,_=check_uv(*masks[:3],before,canonical,shared=masks[3],shared_allowed=masks[3]&allowed)
        if not report["technical_pass"]:raise ValueError("Canonical C protection failed: "+name)
        result["final_protection"][name]=report
    actual_colors={p for p,row in rows.items() if row["role"]=="color"}
    if used_colors!=actual_colors:raise ValueError("Runtime color DDS has no complete final color audit")
    result["final_graphics"]=check_roles([{"role":r["role"],"pixels":r["pixels"],"user_request":r.get("user_request")} for r in graphic_receipts],data.get("graphic_omissions"))
    groups={};reviewed_normal=set()
    for role,material in materials.items():
        state=material["state"]
        if state=="not_applicable":
            if material.get("final_samples") or material.get("color_samples") or material.get("preserve_samples"):
                raise ValueError("Absent material cannot carry real output samples")
            checked_file(root,material.get("evidence"),"absent material basis")
            continue
        if state=="preserve":
            if material.get("final_samples") or material.get("color_samples"):
                raise ValueError("Preserve cannot silently skip modified material samples")
            preserved=material.get("preserve_runtime_ids",[])
            selected=[row for row in rows.values() if row["id"] in preserved]
            samples=material.get("preserve_samples",[])
            if (not selected and not samples) or len(selected)!=len(set(preserved)) or any(row["state"]!="preserve" for row in selected):
                raise ValueError("Preserved material needs unchanged runtime IDs or explicit region samples")
            for sample in samples:
                match=[r for r in rows.values() if r["id"]==sample.get("runtime_texture_id")]
                if len(match)!=1:raise ValueError("Unknown preserved material runtime resource")
                row=match[0]
                before=read_rgba(root,row.get("baseline"),"preserved region baseline")
                after=read_rgba(root,row["canonical"],"preserved region canonical")
                mask=load_mask(root,sample["mask"],"preserved material region",after.shape[:2])
                faces=native.selected(sample.get("coverage_id"),sample.get("group_ids"))
                resource=sample.get("native_resource")
                if resource not in row.get("native_resources",[]):raise ValueError("Preserved material resource differs from native runtime")
                expected_mask=native.mask(faces,resource,after.shape[:2])
                if not np.array_equal(mask,expected_mask):raise ValueError("Preserved material sample omits its complete physical surface")
                if not mask.any() or before.shape!=after.shape or not np.array_equal(before[mask],after[mask]):
                    raise ValueError("Preserve material region changed")
            continue
        params=material_parameters(material)
        color_samples=material.get("color_samples")
        if not isinstance(color_samples,list) or not color_samples:raise ValueError("Paint material needs actual C color scopes")
        for sample in color_samples:
            texture=sample.get("texture")
            if texture not in canonical_colors:raise ValueError("Material C sample refers to unknown color texture")
            c=canonical_colors[texture];mask=load_mask(root,sample["mask"],"material C mask",c.shape[:2])
            if not mask.any():raise ValueError("Empty material C sample")
            if params["color_mode"]=="paint_roles":
                allowed=np.zeros(mask.shape,bool)
                for region in textures[texture]["paint_regions"]:
                    if region["role"] in params["paint_roles"]:allowed|=load_mask(root,region["mask"],"material paint role",mask.shape)
                decoration=load_mask(root,textures[texture]["decoration_mask"],"decoration exclusion",mask.shape)
                if np.any(mask&~(allowed&~decoration)):raise ValueError("Material color scope exceeds its declared A/B/C/F roles")
            else:
                values=c[mask,:3].astype(float);target=np.array(params["color_srgb"])
                if np.any(np.max(np.abs(values-target),axis=1)>12) or np.max(np.abs(np.median(values,axis=0)-target))>5:
                    raise ValueError("Material color_srgb disagrees with canonical C")
        samples=material.get("final_samples")
        if not isinstance(samples,list) or not samples:raise ValueError("Painted material needs actual packed N samples")
        for sample in samples:
            claim_id=sample.get("coverage_id")
            if claim_id not in coverage:raise ValueError("Material N needs native coverage")
            row,after,key=resolve(sample["final_n_dds"],sample["final_n"],"normal")
            if row["state"]!="modified":raise ValueError("Painted N cannot claim preserve")
            reviewed_normal.add(key)
            before=read_rgba(root,sample["before_n"],"before material N")
            if sample["before_n"]["sha256"]!=row.get("baseline",{}).get("sha256") or before.shape!=after.shape:
                raise ValueError("Material N baseline/grid mismatch")
            mask=load_mask(root,sample["mask"],"material N mask",before.shape[:2])
            micro=load_mask(root,sample["micro_mask"],"micro-normal region",mask.shape) if "micro_mask" in sample else np.zeros(mask.shape,bool)
            mapping=sample.get("uv_mapping",{})
            if mapping.get("mode") not in {"same_native_uv","independent_uv"} or mapping.get("color_texture") not in canonical_colors:
                raise ValueError("Explicit C/N UV mapping and color resource required")
            checked_file(root,mapping.get("evidence"),"native C/N UV/texel-density correspondence")
            if mapping["mode"]=="independent_uv":
                claim=read_json(checked_file(root,mapping.get("normal_coverage"),"independent N native coverage"))
            else:
                claim=dict(coverage[claim_id])
                if claim["texture"]!=mapping["color_texture"]:
                    raise ValueError("Same-UV N mapping points to a different C resource")
            claim["paint_mask"]=sample["mask"]
            claim["layer_role"]="antislip" if role=="antislip" else "base_paint"
            if not audit_record(root,claim)["technical_pass"]:raise ValueError("Material N native coverage failed")
            group=groups.setdefault(key,{"before":before,"after":after,"baseline":sample["before_n"]["sha256"],
                                        "mask":np.zeros(mask.shape,bool),"micro":np.zeros(mask.shape,bool),"roles":[]})
            if group["baseline"]!=sample["before_n"]["sha256"] or group["mask"].shape!=mask.shape or np.any(group["mask"]&mask):
                raise ValueError("Material N scopes overlap or disagree on baseline")
            local=before.copy();local[mask]=after[mask]
            report=audit_parameters(before,local,mask,material,micro)
            if not report["technical_pass"]:raise ValueError("Canonical material R/B/G/A failed: "+role)
            group["mask"]|=mask;group["micro"]|=micro;group["roles"].append({"role":role,"audit":report,"uv_mapping":mapping["mode"],"C_size":[canonical_colors[mapping["color_texture"]].shape[1],canonical_colors[mapping["color_texture"]].shape[0]],"N_size":[after.shape[1],after.shape[0]]})
    for key,group in groups.items():
        b,a=group["before"],group["after"]
        if not np.array_equal(b[~group["mask"]],a[~group["mask"]]):raise ValueError("Canonical N changed outside all material scopes")
        if not np.array_equal(b[~group["micro"]][:,[1,3]],a[~group["micro"]][:,[1,3]]):raise ValueError("Canonical G/A changed outside actual microstructure")
        result["final_materials"].append({"runtime_dds":key,"roles":group["roles"],"outside_exact":True,"structural_xy_exact":True})
    for key,row in rows.items():
        if row["role"]=="normal" and row["state"]=="modified" and key not in reviewed_normal:
            raise ValueError("Modified runtime N was not covered by any material audit")
    from repair_binding import audit_bound_repairs
    from material_surfaces import audit_material_surfaces,audit_equipment_pixels
    result["channel_repairs"]=audit_bound_repairs(root,data)
    result["physical_material_scopes"]=audit_material_surfaces(root,data,native)
    result["equipment_pixel_protection"]=audit_equipment_pixels(root,data,native)
    result["observations"]=validate_observations(root,data,coverage)
    result["runtime_files_checked"]=len(data["final_runtime_files"])
    result["dds_decode_binding"]="all actual mips decoded, checked against pre-encoding semantic mips and native BLK slots"
    return result
