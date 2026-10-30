"""Keep AZUR as the primary reference and audit retained runtime bytes read-only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from dds_snapshot import inspect_stream, parse_header, decode_mip
from input_snapshot import _mappings
from runtime_validation import package_path
from skill_contract import ROOT, checked_file, policy, read_json, require_text, sha


def validate_reference_policy(rules=None, root=ROOT):
    rules = policy() if rules is None else rules
    hierarchy = rules.get("reference_hierarchy", {})
    if hierarchy.get("primary_template") != "fr_leclerc_azur":
        raise ValueError("Leclerc AZUR must remain the primary style template")
    if hierarchy.get("target_user_override") is not True:
        raise ValueError("Current target-specific user decisions must remain authoritative")
    if hierarchy.get("adaptation_cases") != ["type_10", "il_merkava_mk_4m", "germ_leopard_2a7hu"]:
        raise ValueError("Known-vehicle regressions must remain adaptation cases")
    if hierarchy.get("adaptation_replaces_primary") is not False:
        raise ValueError("Adaptation regression cannot replace primary reference validation")
    checked_file(root, hierarchy.get("evidence"), "AZUR retained evidence")
    paths = set()
    for name, recipe in rules["part_recipes"].items():
        anchor = recipe.get("primary_basis", {})
        if anchor.get("template") != "fr_leclerc_azur":
            raise ValueError("Part has lost the AZUR anchor: " + name)
        if anchor.get("scope") not in {"observed_composition", "retained_method", "target_extension"}:
            raise ValueError("Part must distinguish observation, retained method and target extension: " + name)
        require_text(anchor.get("relationship"), name + " AZUR relationship")
        evidence = checked_file(root, anchor.get("evidence"), name + " source evidence")
        paths.add(str(evidence))
        require_text(recipe.get("adaptation_basis"), name + " adaptation scope")
    return {"primary_template": "fr_leclerc_azur", "part_relations_checked": len(rules["part_recipes"]),
            "source_documents_checked": len(paths), "adaptation_cases": hierarchy["adaptation_cases"],
            "reference_scope": "retained evidence; no recovered source/model or artwork approval"}


def audit_archive(archive, evidence, fixtures_dir=None):
    archive = Path(archive).resolve(strict=True)
    before = sha(archive)
    if before != evidence["archive_sha256"]:
        raise ValueError("Archive is not the retained AZUR revision")
    expected = evidence["files"]
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Frozen AZUR member inventory is required")
    if fixtures_dir is not None:
        fixtures_dir = Path(fixtures_dir)
        if fixtures_dir.exists():
            raise ValueError("Fixture destination must be new")
    reports, fixture_rows = [], []
    with zipfile.ZipFile(archive) as z:
        names = [i.filename for i in z.infolist()]
        if len(names) != len(set(n.casefold() for n in names)):
            raise ValueError("Duplicate/case-colliding archive member")
        for name in names:
            if package_path(name) != name:
                raise ValueError("Noncanonical archive member")
        if set(names) != set(expected):
            raise ValueError("AZUR member set differs from frozen deployment")
        blks = [n for n in names if n.endswith(".blk")]
        if len(blks) != 1:
            raise ValueError("Exactly one retained BLK is required")
        blk = blks[0]
        raw = z.read(blk)
        if hashlib.sha256(raw).hexdigest() != expected[blk]:
            raise ValueError("AZUR BLK differs from deployment")
        mappings = _mappings(raw.decode("utf-8-sig"))
        base = PurePosixPath(blk).parent
        targets = {(base / m["target"]).as_posix() for m in mappings}
        if targets != set(names) - {blk}:
            raise ValueError("BLK does not bind the exact retained DDS inventory")
        mapped = {m["target"]: m["resource"] for m in mappings}
        for name in sorted(targets):
            info = z.getinfo(name)
            with z.open(info) as stream:
                result = inspect_stream(stream, info.file_size)
            if result["actual_file_sha256"] != expected[name]:
                raise ValueError("AZUR DDS differs from deployment: " + name)
            result["member"] = name
            resource = mapped[PurePosixPath(name).relative_to(base).as_posix()]
            result["native_resource"] = resource
            result["role"] = "ao" if resource.rstrip("*").endswith("_ao") else (
                "normal" if resource.rstrip("*").endswith("_n") else "color")
            reports.append(result)
            if fixtures_dir is not None:
                # Keep original header and one exact encoded tail payload, never
                # fabricate a new DDS container or repack the source header.
                level = next(i for i, size in enumerate(result["mip_sizes"]) if max(size) <= 8)
                offset = result["header_bytes"] + sum(result["mip_bytes"][:level])
                with z.open(info) as stream:
                    header = stream.read(result["header_bytes"])
                    stream.seek(offset)
                    payload = stream.read(result["mip_bytes"][level])
                width, height = result["mip_sizes"][level]
                pixels = decode_mip(payload, width, height, result)
                stem = PurePosixPath(name).stem
                fixtures_dir.mkdir(parents=True, exist_ok=True)
                header_name, payload_name = stem + ".header.bin", stem + ".mip.bin"
                (fixtures_dir / header_name).write_bytes(header)
                (fixtures_dir / payload_name).write_bytes(payload)
                fixture_rows.append({"member": name, "source_sha256": expected[name], "source_bytes": info.file_size,
                    "header": header_name, "header_sha256": hashlib.sha256(header).hexdigest(),
                    "payload": payload_name, "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "level": level, "size": [width, height], "role": result["role"],
                    "decoded_rgba_sha256": hashlib.sha256(pixels.tobytes()).hexdigest()})
    if sha(archive) != before:
        raise ValueError("Source archive changed during audit")
    if fixtures_dir is not None:
        (fixtures_dir / "index.json").write_text(json.dumps({"archive_sha256": before, "samples": fixture_rows,
            "scope": "exact historical tail bytes for decoder regression; not full vehicle or material approval"},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"schema_version": 1, "primary_template": "fr_leclerc_azur", "archive_sha256": before,
            "archive_bytes": archive.stat().st_size, "unpacked_bytes": sum(i.file_size for i in z.infolist()),
            "members_verified": len(expected), "dds_count": len(reports),
            "mips_decoded": sum(r["mip_count"] for r in reports), "source_unchanged": True,
            "deployment_hashes_match": True, "textures": reports,
            "historical_masked_measurements": "retained only; source masks unavailable, not remeasured",
            "whole_vehicle_style_validation": "not_run", "game_visual": "pending existing user feedback",
            "current_delivery_budget": "not applied to historical input; validate new output separately"}


def check_fixtures(folder):
    folder = Path(folder)
    index = read_json(folder / "index.json")
    samples = index.get("samples", [])
    if not samples or len({r["member"] for r in samples}) != len(samples):
        raise ValueError("Unique actual reference samples are required")
    for row in samples:
        header_path = checked_file(folder, {"file": row["header"], "sha256": row["header_sha256"]}, "original DDS header")
        payload_path = checked_file(folder, {"file": row["payload"], "sha256": row["payload_sha256"]}, "original mip payload")
        meta = parse_header(header_path.read_bytes(), row["source_bytes"])
        level = row["level"]
        if type(level) is not int or not 0 <= level < meta["mip_count"]:
            raise ValueError("Reference mip level is invalid")
        if list(meta["mip_sizes"][level]) != row["size"]:
            raise ValueError("Reference mip dimensions differ")
        raw = payload_path.read_bytes()
        if len(raw) != meta["mip_bytes"][level]:
            raise ValueError("Reference mip payload length differs")
        pixels = decode_mip(raw, *row["size"], meta)
        if hashlib.sha256(pixels.tobytes()).hexdigest() != row["decoded_rgba_sha256"]:
            raise ValueError("Historical RGBA decode changed: " + row["member"])
    return {"samples_checked": len(samples), "roles": sorted({r["role"] for r in samples})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixtures-dir", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Audit output must be new")
    validate_reference_policy()
    evidence = read_json(ROOT / "references/data/azur-retained-evidence.json")
    report = audit_archive(args.archive, evidence, args.fixtures_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "textures"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
