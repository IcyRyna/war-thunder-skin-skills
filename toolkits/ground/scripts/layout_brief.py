#!/usr/bin/env python3
"""Create/check editable ENDFIELD part briefs; this does not paint a vehicle.

The assembled Skill is self-contained. For development only, --package-root
may point at an assembled test tree. All resource references in a brief remain
relative to that Skill, rather than binding the output to a local installation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import sys

from artifact_io import ArtifactTransaction

SKILL_ID = "wt-style-endfield"
FAMILIES = ("leopard-2", "t-80", "t-90", "type-99", "leclerc")
PARTS = ("H", "T", "G", "M", "A", "R")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return result


def package_file(root: Path, relative: str) -> Path:
    """Resolve a package reference without traversal or symlink escapes."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Invalid package-relative resource")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or any(x in {"", ".", ".."} or ":" in x for x in relative.split("/")):
        raise ValueError(f"Unsafe package reference: {relative}")
    target = root.joinpath(*parsed.parts).resolve(strict=True)
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"Package resource is not a contained file: {relative}")
    return target


def text_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError(f"{field} must contain 1–4000 characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{field} contains control characters")
    return value.strip()


def resources(root: Path, family: str) -> tuple[dict, dict, dict, dict]:
    if family not in FAMILIES:
        raise ValueError(f"Unknown family: {family}")
    index = load_json(package_file(root, "references/vehicles/index.json"))
    matches = [x for x in index["families"] if x["family"] == family]
    if len(matches) != 1:
        raise ValueError("Family index is inconsistent")
    item = matches[0]
    profile = load_json(package_file(root, item["profile"]))
    if profile["family"] != family or profile["unit"] != item["unit"]:
        raise ValueError("Family/model identity mismatch")
    zones = load_json(package_file(root, "references/layout/zone-tree.json"))
    fallbacks = load_json(package_file(root, "references/layout/fallbacks.json"))
    return item, profile, zones, fallbacks


def zone_selection(tree: dict, selected: list[str] | None) -> list[str]:
    known = {z["id"] for p in tree["major_parts"] for z in p["zones"]}
    aliases = tree.get("zone_aliases", {})
    # H07 refines H04; it is an alternative work granularity, not a second pass.
    candidates = selected if selected is not None else sorted(known - {"H07"})
    result: list[str] = []
    for value in candidates:
        expanded = aliases.get(value, [value])
        for zone in expanded:
            if zone not in known:
                raise ValueError(f"Unknown semantic zone: {zone}")
            if zone in result:
                raise ValueError(f"Duplicate or overlapping zone alias: {zone}")
            result.append(zone)
    if not result:
        raise ValueError("Select at least one semantic work region")
    if "H07" in result and any(x in result for x in ("H04L", "H04R")):
        raise ValueError("H07 refines H04: select a single editing granularity")
    return result


def make_brief(root: Path, family: str, theme: str = "ENDFIELD", number: str = "EF10",
               auxiliary_text: str = "FIELD OPERATIONS", variant: str | None = None,
               weathering: str = "none", surface_grain: str = "none",
               preset: str | None = None, selected_zones: list[str] | None = None) -> dict:
    item, profile, tree, fallbacks = resources(root, family)
    if weathering not in ("none", "light") or surface_grain not in ("none", "subtle"):
        raise ValueError("Unsupported weathering/surface_grain option")
    preset_record = None
    if preset is not None:
        found = [p for p in fallbacks["presets"] if p["id"] == preset]
        if len(found) != 1:
            raise ValueError(f"Unknown optional preset: {preset}")
        preset_record = found[0]
    active = zone_selection(tree, selected_zones)
    part_briefs = []
    for part in tree["major_parts"]:
        regions = [z for z in part["zones"] if z["id"] in active]
        if not regions:
            continue
        part_briefs.append({
            "part_id": part["id"], "part_name": part["name"],
            "region_ids": [z["id"] for z in regions],
            "role_in_global_composition": part["purpose"],
            "composition_intent": part["freedom"],
            "coordination": part.get("coordination", "Coordinate with the global hierarchy and actual material/structure."),
            "optional_start": preset_record[part["id"]] if preset_record else None,
            "surface_checks": [{"zone": z["id"], "check": z["inspect"]} for z in regions],
            "actual_uv_mapping": "not_run", "editing_owner": "single_executor",
            "assembly_evidence": [], "execution_state": "needs_actual_surface_and_layout_design",
        })
    result = {
        "schema_version": 1, "skill": SKILL_ID, "candidate_version": "0.1.0",
        "state": "planning", "target_vehicle": {
            "family": family, "requested_variant": text_value(variant or profile["representative"], "variant"),
            "reference_unit": profile["unit"], "reference_profile": item["profile"],
            "attachment_constraints": deepcopy(item["constraints"]),
            "actual_model_and_attachments_checked": False,
            "subvariant_adaptation": item["subvariant_adaptation"],
        },
        "inputs": {"theme": text_value(theme, "theme"), "number": text_value(number, "number"),
                   "auxiliary_text": text_value(auxiliary_text, "auxiliary_text"),
                   "weathering": weathering, "surface_grain": surface_grain},
        "composition_mode": "independent" if preset is None else "optional_fallback",
        "preset": preset, "preset_is_mandatory": False,
        "global_brief": {
            "reference": "references/a7v-analysis.md", "reference_relationships_read": False,
            "focal_hierarchy": "Choose the actual primary hull reading surface, secondary parts and quiet areas as one whole composition.",
            "palette_roles": "Choose black/white massing, yellow direction roles and optional sparse accents on actual views; no fixed percentages.",
            "yellow_and_density_intent": "Select planes, routes, short rhythm or quiet space for each actual carrier; do not repeat one stamp on every part.",
            "optional_start": preset_record["global"] if preset_record else None,
        },
        "parts": part_briefs,
        "references": {"family_direction": item["reference"], "views": deepcopy(item["views"]),
                       "zone_tree": "references/layout/zone-tree.json",
                       "whole_transparent_mark": "assets/legacy/decals/endfield-industries-en-native.png",
                       "editable_components": "references/optional-components.json",
                       "ps_workflow": "references/ps-production.md"},
        "identity_policy": {"whole_lockup": True, "uniform_scale": True, "crop": False,
                            "split_lettering": False, "separate_opaque_logo_backing": False},
        "checks": {"technical": "not_run", "visual": "not_run", "game": "not_run",
                   "independent_cold_start": "not_run", "user_review": "awaiting_review"},
        "scope": "An editable task brief, not a finished layout, UV map or game package.",
    }
    validate_brief(root, result)
    return result


def validate_brief(root: Path, brief: dict) -> dict:
    if type(brief.get("schema_version")) is not int or brief["schema_version"] != 1 or brief.get("skill") != SKILL_ID:
        raise ValueError("Unsupported brief identity/schema")
    vehicle = brief.get("target_vehicle")
    if not isinstance(vehicle, dict):
        raise ValueError("target_vehicle must be an object")
    item, profile, tree, fallbacks = resources(root, vehicle.get("family"))
    if vehicle.get("reference_unit") != profile["unit"] or vehicle.get("reference_profile") != item["profile"]:
        raise ValueError("Brief family/model reference identity mismatch")
    text_value(vehicle.get("requested_variant"), "requested_variant")
    inputs = brief.get("inputs", {})
    for key in ("theme", "number", "auxiliary_text"):
        text_value(inputs.get(key), key)
    if inputs.get("weathering") not in ("none", "light") or inputs.get("surface_grain") not in ("none", "subtle"):
        raise ValueError("Unsupported independent surface settings")
    if brief.get("preset_is_mandatory") is not False:
        raise ValueError("A preset cannot become mandatory")
    preset = brief.get("preset")
    if preset is None:
        if brief.get("composition_mode") != "independent":
            raise ValueError("No preset requires independent composition mode")
    elif preset not in {p["id"] for p in fallbacks["presets"]} or brief.get("composition_mode") != "optional_fallback":
        raise ValueError("Invalid optional fallback selection")
    parts = brief.get("parts")
    if not isinstance(parts, list) or not parts or any(not isinstance(p, dict) for p in parts):
        raise ValueError("parts must be a nonempty array of part objects")
    seen = set()
    ids = []
    expected = {p["id"]: {z["id"] for z in p["zones"]} for p in tree["major_parts"]}
    for part in parts:
        identifier = part.get("part_id")
        if identifier not in PARTS or identifier in seen:
            raise ValueError("Unknown or duplicated major part")
        seen.add(identifier)
        regions = part.get("region_ids")
        if not isinstance(regions, list) or not regions or any(not isinstance(z, str) or z not in expected[identifier] for z in regions):
            raise ValueError("Region belongs to a different or unknown physical part")
        ids.extend(regions)
        for field in ("role_in_global_composition", "composition_intent"):
            text_value(part.get(field), field)
    zone_selection(tree, ids)
    policy = brief.get("identity_policy", {})
    if (policy.get("whole_lockup") is not True or policy.get("uniform_scale") is not True
            or any(policy.get(k) is not False for k in ("crop", "split_lettering", "separate_opaque_logo_backing"))):
        raise ValueError("Industrial identity must remain whole, transparent and uniformly scaled")
    refs = brief.get("references", {})
    if not isinstance(refs.get("views"), dict) or set(refs["views"]) != {"side", "front", "rear", "top"}:
        raise ValueError("All four source views must remain reachable")
    if refs["views"] != item["views"] or refs.get("family_direction") != item["reference"]:
        raise ValueError("Direction/view references belong to a different family")
    paths = list(refs["views"].values()) + [v for k, v in refs.items() if k != "views"]
    for path in paths:
        package_file(root, path)
    return {"status": "valid_input_contract", "parts": len(parts), "active_semantic_regions": len(ids),
            "composition_mode": brief["composition_mode"], "artwork_acceptance": "not_assessed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--family", choices=FAMILIES, required=True)
    create.add_argument("--variant")
    create.add_argument("--theme", default="ENDFIELD")
    create.add_argument("--number", default="EF10")
    create.add_argument("--auxiliary-text", default="FIELD OPERATIONS")
    create.add_argument("--weathering", choices=("none", "light"), default="none")
    create.add_argument("--surface-grain", choices=("none", "subtle"), default="none")
    create.add_argument("--preset", choices=("F01", "F02", "F03"))
    create.add_argument("--zones", nargs="+")
    create.add_argument("--out", type=Path, required=True)
    check = sub.add_parser("check")
    check.add_argument("brief", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.package_root.resolve(strict=True)
        if args.command == "check":
            result = validate_brief(root, load_json(args.brief))
        else:
            result_brief = make_brief(root, args.family, args.theme, args.number,
                                      args.auxiliary_text, args.variant, args.weathering,
                                      args.surface_grain, args.preset, args.zones)
            with ArtifactTransaction([args.out], [root], label="layout-brief") as transaction:
                transaction.stage(args.out).write_text(json.dumps(result_brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                transaction.commit()
            result = {"status": "planning_brief_created", "out": str(args.out), "preset": args.preset,
                      "production_completed": False}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
