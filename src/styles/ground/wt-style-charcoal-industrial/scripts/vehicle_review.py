"""Check a vehicle's composition, materials, and complete native-face coverage."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from reference_contract import check_base_color, check_roles
from skill_contract import (checked_file, identity, load_mask, material_parameters,
                            policy, read_json, require_text, sha, number)
from surface_coverage import audit_record


def _unique(rows, key, label):
    result = {}
    if not isinstance(rows, list):
        raise ValueError(label + " must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(label + " entries must be objects")
        name = require_text(row.get(key), label + " ID")
        if name in result:
            raise ValueError("Duplicate " + label + ": " + name)
        result[name] = row
    return result


def review_evidence(root, record, name, data=None):
    if not isinstance(record, dict) or record.get("state") != "checked_local":
        raise ValueError("Local observation still required: " + name)
    require_text(record.get("observation"), name + " observation")
    require_text(record.get("lighting_id"), name + " lighting/view transform")
    require_text(record.get("view"), name + " view")
    if not record.get("evidence"):
        raise ValueError(name + " requires frozen local evidence")
    for item in record["evidence"]:
        checked_file(root, item, name + " evidence")
    from visual_evidence import audit_visual_record
    visual=audit_visual_record(root,record,name,data,base_only=name=="base_only")
    if name == "base_only" and record.get("hidden_layers") != ["honeycomb", "decals", "micro_accents"]:
        raise ValueError("Base-only observation must hide decoration layers")
    if name == "whole_vehicle":
        if set(record.get("distances", [])) != {"far", "medium", "near"}:
            raise ValueError("Whole vehicle requires far/medium/near observations")
    if name == "surface_finish" and record.get("rotating_light_checked") is not True:
        raise ValueError("Finish review requires a changing light/view observation")
    if name == "final_dds" and record.get("all_mips_rebound") is not True:
        raise ValueError("Final DDS and all mip levels must be checked on the actual target")
    return {"state": "checked_local", "evidence_count": len(record["evidence"]), "visual_evidence":visual,
            "user_approval": "not inferred"}


def checked_dds_pair(root, png_spec, dds_spec, label):
    png = checked_file(root, png_spec, label + " decoded pixels")
    dds = checked_file(root, dds_spec, label + " actual DDS")
    with dds.open("rb") as stream:
        if stream.read(4) != b"DDS ":
            raise ValueError(label + " source is not a DDS")
    with Image.open(dds) as image:
        decoded = np.array(image.convert("RGBA"))
    with Image.open(png) as image:
        if image.mode != "RGBA":
            raise ValueError(label + " decoded PNG must preserve RGBA")
        supplied = np.array(image)
    if not np.array_equal(decoded, supplied):
        raise ValueError(label + " PNG does not match the actual DDS top mip")
    return supplied


def validate_manifest(path, stage="base"):
    path = Path(path).resolve()
    root, data, rules = path.parent, read_json(path), policy()
    from azur_reference import validate_reference_policy
    reference_report = validate_reference_policy(rules)
    if stage not in {"design", "base", "final"}:
        raise ValueError("Unknown vehicle validation stage")
    if data.get("schema_version") != 3 or data.get("policy_version") != identity()["version"]:
        raise ValueError("Vehicle design must target schema 3 and this candidate's policy version")
    if data.get("migration",{}).get("status")=="requires_evidence":
        raise ValueError("Schema migration still requires real evidence")
    for field in ("vehicle", "unit_id", "attachment_state"):
        require_text(data.get(field), field)
    capabilities=data.get("capabilities",{})
    if not isinstance(capabilities,dict) or any(type(v) is not bool for v in capabilities.values()):
        raise ValueError("One capability schema: name -> strict boolean")
    for claim,value in capabilities.items():
        if value:checked_file(root,data.get("capability_evidence",{}).get(claim),"capability evidence")
    checked_file(root, data.get("model"), "target model")
    checked_file(root, data.get("bindings"), "target material bindings")
    textures = _unique(data.get("textures"), "id", "texture")
    coverage = _unique(data.get("coverage"), "id", "coverage")
    if not textures or not coverage:
        raise ValueError("Actual textures and native surface coverage are required")
    for name, record in coverage.items():
        if record.get("texture") not in textures:
            raise ValueError("Coverage points to an unknown texture: " + name)
    from native_inventory import NativeContext
    native=NativeContext(root,data)
    native_report=native.validate_claims(coverage)
    zones = data.get("zones", {})
    if set(zones) != set(rules["composition"]["zones"]):
        raise ValueError("All six zones must have explicit decisions")
    from production_checks import validate_sensitive_equipment
    equipment_checks=validate_sensitive_equipment(root,data,coverage,native)
    used_coverage = set()
    for zone, decision in zones.items():
        if decision.get("state") == "not_applicable":
            require_text(decision.get("reason"), zone + " physical exception")
            continue
        if decision.get("state") != "designed":
            raise ValueError(zone + " remains unresolved")
        for field in ("large_geometry", "quiet_area", "focal_point", "pattern_scale", "material_contrast"):
            require_text(decision.get(field), zone + " " + field)
        carriers = decision.get("coverage_ids")
        if not isinstance(carriers, list) or not carriers or not set(carriers) <= set(coverage):
            raise ValueError(zone + " must name actual reviewed carriers")
        used_coverage.update(carriers)
    if used_coverage != set(coverage):
        raise ValueError("Coverage contains carriers with no six-zone design role")
    native_layouts = {}
    parts = data.get("part_layouts", {})
    if set(parts) != set(rules["part_recipes"]):
        raise ValueError("Every default part recipe needs an explicit applied/adapted/absent decision")
    for name, recipe in rules["part_recipes"].items():
        choice = parts[name]
        state = choice.get("state")
        if state not in {"apply_default", "adapted", "not_applicable"}:
            raise ValueError("Unresolved part recipe: " + name)
        require_text(choice.get("reason"), name + " design decision")
        if state == "not_applicable":
            checked_file(root, choice.get("evidence"), name + " absence/user-override evidence")
            continue
        carriers = choice.get("coverage_ids")
        if not isinstance(carriers, list) or not carriers or not set(carriers) <= set(coverage):
            raise ValueError(name + " needs concrete native carriers")
        elements = choice.get("elements")
        if not isinstance(elements, list) or not elements or any(not isinstance(v,str) or not v for v in elements):
            raise ValueError(name + " needs actual design elements")
        missing = set(recipe["default_elements"]) - set(elements)
        if state == "apply_default" and missing:
            raise ValueError(name + " omits default elements: " + ", ".join(sorted(missing)))
        if state == "adapted":
            overrides = choice.get("replacements", {})
            if set(overrides) != missing:
                raise ValueError(name + " must explain each replaced/removed default element")
            for reason in overrides.values():
                require_text(reason, name + " replacement")
        if name == "lower_glacis" and "vehicle_wordmark" in elements:
            require_text(choice.get("identity_text"), "front vehicle wordmark")
            if choice.get("identity_unit_id") != data["unit_id"]:
                raise ValueError("Front wordmark belongs to a different vehicle")
        if name == "roof_warning":
            require_text(choice.get("layout"), "roof text/stripe fit and orientation")
            if "BLOW-OUT" in choice.get("label_texts", []):
                if data.get("capabilities",{}).get("ammunition_blowout_panels") is not True:
                    raise ValueError("BLOW-OUT needs confirmed target ammunition blowout panels")
                checked_file(root, choice.get("function_evidence"), "roof warning function")
        if name == "roof_warning":
            if not isinstance(choice.get("required_instances"),list) or not choice["required_instances"]:
                raise ValueError("Decide every actual roof warning instance before base painting")
            if stage in {"base","final"}:
                from layout_fit import validate_layout_checks
                native_layouts[name]=validate_layout_checks(root,choice,data["model"]["sha256"],native)
        if name == "machine_gun":
            components = choice.get("components", {})
            if set(components) != {"housing","gun_body","stock","ammunition"}:
                raise ValueError("Locate gun housing, body, stock/grip and ammunition separately")
            seen = set()
            for component, selected in components.items():
                if selected.get("state") == "not_applicable":
                    require_text(selected.get("reason"), component + " absence reason")
                    checked_file(root,selected.get("evidence"),component + " absence")
                    continue
                if selected.get("state") not in {"paint","preserve"} or selected.get("coverage_id") not in coverage:
                    raise ValueError("Each gun component needs its actual scope or preservation decision")
                claim = coverage[selected["coverage_id"]]
                group_ids = selected.get("face_group_ids", [])
                available = {g["id"] for g in claim["face_groups"]}
                if not group_ids or not set(group_ids) <= available:
                    raise ValueError("Gun component needs classified native face groups")
                for gid in group_ids:
                    token=(selected["coverage_id"],gid)
                    if token in seen:
                        raise ValueError("One native gun group cannot stand in for several distinct components")
                    seen.add(token)
            if choice.get("accent_component") != "housing":
                require_text(choice.get("accent_override_reason"),"non-housing gun accent")
        if stage in {"base", "final"}:
            if choice.get("visibility_checked") is not True:
                raise ValueError(name + " needs occlusion/handedness/edge-fit observation")
            checked_file(root, choice.get("evidence"), name + " placement evidence")
    graphics = list(_unique(data.get("graphics", []), "id", "graphic").values())
    for item in graphics:
        if item.get("coverage_id") not in coverage:
            raise ValueError("Graphic needs a named physical carrier")
        require_text(item.get("purpose"), "graphic purpose")
        role=item.get("layer_role")
        if role not in {"decal","honeycomb","antislip"} or coverage[item["coverage_id"]]["layer_role"]!=role:
            raise ValueError("Graphic must bind the same actual decoration role as native coverage")
    graphic_report = check_roles([{"role": item["role"], "pixels": 1, "user_request": item.get("user_request")} for item in graphics],
                                 data.get("graphic_omissions"))
    materials = _unique(data.get("materials"), "role", "material")
    if set(materials) != set(rules["materials"]["roles"]):
        raise ValueError("Every material role needs paint/preserve/not_applicable")
    material_report = {}
    for name, record in materials.items():
        if record.get("state") == "paint":
            checked_file(root, record.get("evidence"), "target material parameters")
        material_report[name] = material_parameters(record)
    result = {"schema_version": 1, "policy_version": identity()["version"], "stage": stage,
              "vehicle": data["vehicle"], "manifest_sha256": sha(path),
              "graphics": graphic_report, "materials": material_report, "reference_hierarchy": reference_report,
              "coverage": {}, "paint": {}, "reviews": {}, "part_recipes_checked": len(parts), "native_layouts":native_layouts,
              "visual_approval": "not inferred", "game_validation": "not_run",
              "production_tools": "not audited here; delivery_validate requires real execution evidence",
              "sensitive_equipment":equipment_checks, "area_policy": "no 60/30/10 gate; UV counts are not visible body area"}
    if stage == "design":
        result["scope_contracts"]=native.validate_scope_contracts(coverage)
        result["technical_pass"] = True
        result["coverage_state"] = "not_run_at_design_stage"
        return result
    observed_roles = set()
    for name, texture in textures.items():
        source = checked_file(root, texture.get("base_c"), "unadorned base C")
        with Image.open(source) as image:
            if image.mode != "RGBA":
                raise ValueError("Base C must retain its explicit RGBA channels")
            color = np.array(image)
        paint = load_mask(root, texture.get("base_paint_mask"), "base paint mask", color.shape[:2])
        union = np.zeros(paint.shape, bool)
        stats = []
        for region in texture.get("paint_regions", []):
            mask = load_mask(root, region.get("mask"), "paint role mask", paint.shape)
            if np.any(mask & union):
                raise ValueError("Paint role masks overlap")
            union |= mask
            role = region.get("role")
            stats.append(check_base_color(color, mask, role=role, reference=region.get("rgb"),
                                          override_reason=region.get("override_reason")))
            observed_roles.add(role)
        if not np.array_equal(union, paint):
            raise ValueError("Declared base paint has unclassified/outside role pixels")
        if not paint.any():
            require_text(texture.get("no_neutral_paint_reason"), "texture without neutral armor")
        result["paint"][name] = stats
    omissions = data.get("paint_role_omissions", {})
    if not isinstance(omissions, dict) or set(omissions) - {"B", "C"}:
        raise ValueError("Only B/C may be omitted with an explicit target composition decision")
    for role, reason in omissions.items():
        require_text(reason, "paint role omission")
        if role in observed_roles:
            raise ValueError("Contradictory paint role omission")
    if {"A", "B", "C"} - observed_roles - set(omissions):
        raise ValueError("Three large paint roles need actual masks or explicit B/C exceptions")
    for name, record in coverage.items():
        report = audit_record(root, record)
        if not report["technical_pass"]:
            raise ValueError("Coverage failed for " + name + ": " + "; ".join(report["errors"]))
        result["coverage"][name] = report
    names = rules["composition"]["final_reviews"] if stage == "final" else rules["composition"]["base_review"]
    for name in names:
        result["reviews"][name] = review_evidence(root, data.get("reviews", {}).get(name), name, data)
    if stage == "final":
        from final_review import validate_final
        result.update(validate_final(root,data,textures,coverage,materials,native))
    result["scope_contracts"]=native.validate_scope_contracts(coverage)
    result["technical_pass"] = True
    return result


def validate_for_composer(profile_path, profile, plan_path, plan):
    path = checked_file(Path(plan_path).resolve().parent, plan.get("vehicle_design"), "vehicle design")
    report = validate_manifest(path, "base")
    design = read_json(path)
    if design["vehicle"] != profile.get("vehicle") or design["unit_id"] != profile.get("unit_id"):
        raise ValueError("Composer and design refer to different vehicles")
    for field in ("capabilities","capability_evidence","approved_labels","label_evidence"):
        left=design.get(field,{} if field!="approved_labels" else [])
        right=profile.get(field,{} if field!="approved_labels" else [])
        if left!=right:
            raise ValueError("Composer/profile and vehicle design disagree on "+field)
    textures = {t["id"]: t for t in design["textures"]}
    if set(textures) != set(profile["textures"]):
        raise ValueError("Composer and design texture inventory differs")
    for key, texture in profile["textures"].items():
        if texture["sha256"] != textures[key]["base_c"]["sha256"]:
            raise ValueError("Compose input differs from the reviewed base paint")
    claims = {c["id"]: c for c in design["coverage"]}
    for surface in profile["surfaces"]:
        claim = claims.get(surface.get("coverage_id"))
        if claim is None or claim["texture"] != surface["texture"]:
            raise ValueError("Composer surface needs a matching native coverage ID")
        surface["_reviewed_coverage"] = load_mask(path.parent, claim["paint_mask"], "composer scope")
        surface["_coverage_mode"] = claim["mode"]
    graphics={g["id"]:g for g in design["graphics"]}
    surfaces={s["id"]:s for s in profile["surfaces"]}
    for placement in plan["placements"]:
        graphic=graphics.get(placement.get("graphic_id"))
        surface=surfaces[placement["surface"]]
        if not graphic or graphic["coverage_id"]!=surface["coverage_id"] or placement.get("layer_role")!=graphic["layer_role"]:
            raise ValueError("Each placement must bind actual graphic ID, carrier and layer role")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--stage", choices=("design", "base", "final"), default="base")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = validate_manifest(args.manifest, args.stage)
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
