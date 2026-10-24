"""Read supported native color DDSx resources with the existing pinned decoder."""
from __future__ import annotations
import argparse
import contextlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extractor", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.extractor.resolve().parent))
    from archives import DxpArchive
    from dae_backend import backend
    from ddsx_preview import top_mip
    out = args.out.resolve()
    if out.exists():
        raise FileExistsError("纹理缓存必须使用新目录")
    out.mkdir(parents=True)
    materials = json.loads((args.model_dir / "materials.json").read_text(encoding="utf-8-sig"))["materials"]
    with (args.model_dir / "assembly.obj").open(encoding="utf-8-sig") as stream:
        used = {line[7:].strip() for line in stream if line.startswith("usemtl ")}
    targets, camo_targets, normal_targets = {}, {}, {}
    for material in materials:
        if material["obj_name"] not in used:
            continue
        slots = material.get("texture_slots", [])
        resource = slots[0].rstrip("*") if slots and slots[0] else None
        if resource:
            targets.setdefault(resource, []).append(material["obj_name"])
        if material.get("shader") == "dynamic_masked_tank" and len(slots)>1 and slots[1] and slots[1]!=slots[0]:
            camo_targets.setdefault(slots[1].rstrip("*"), []).append(material["obj_name"])
        if len(slots)>2 and slots[2] and "_n" in slots[2].lower():
            normal_targets.setdefault(slots[2].rstrip("*"), []).append(material["obj_name"])
    color_names=set(targets)
    for resource in normal_targets:targets.setdefault(resource, [])
    for resource in camo_targets:
        targets.setdefault(resource, [])
    candidates = {name: [] for name in targets}
    errors = []
    roots = [args.client / folder for folder in ("patch", "content", "content.hq")]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.dxp.bin")):
            try:
                archive = DxpArchive(path)
                for entry in archive.entries:
                    resource = entry.name.rstrip("*").split("$", 1)[0]
                    if resource in targets and entry.size:
                        candidates[resource].append((path, entry))
            except (OSError, ValueError) as exc:
                errors.append({"pack": str(path.relative_to(args.client)), "error": str(exc)})
    for entries in candidates.values():
        entries.sort(key=lambda pair: (0 if "patch" in pair[0].relative_to(args.client).parts else 1,
                                      -pair[1].extra["width"] * pair[1].extra["height"]))
    bindings, records, qualities, camo_bindings, surface_bindings = {}, [], {}, {}, {}
    with (out / "decode.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        runtime = backend()
        for number, (resource, names) in enumerate(targets.items()):
            attempts = []
            for pack, entry in candidates[resource]:
                try:
                    meta = entry.extra
                    if meta["uncompressed_bytes"] > 128 * 1024 * 1024:
                        raise ValueError("DDSx preview exceeds 128 MiB")
                    header = runtime.material.DDSx.Header(runtime.material.BinFile(bytes.fromhex(meta["header_hex"])))
                    texture = runtime.material.DDSx(str(pack), entry.name, header.memSz, entry.offset, header)
                    data = texture.getData()
                    if len(data) != meta["uncompressed_bytes"]:
                        raise ValueError("DDSx decompressed byte count mismatch")
                    dds, note = top_mip(data, meta)
                    filename = f"color-{number:03d}.dds"
                    (out / filename).write_bytes(dds)
                    for name in names:
                        bindings[name] = filename
                        qualities[name] = "thumbnail-only" if "$tq" in entry.name else "native-top"
                    for name in normal_targets.get(resource, []):surface_bindings[name]=filename
                    for name in camo_targets.get(resource, []):
                        camo_bindings[name]=filename
                    records.append({"resource": resource, "materials": names, "state": "decoded", "file": filename,
                                    "pack": str(pack.relative_to(args.client)), "format": meta["fourcc"],
                                    "source_entry": entry.name, "quality": "thumbnail-only" if "$tq" in entry.name else "native-top", **note})
                    break
                except (OSError, ValueError) as exc:
                    attempts.append({"pack": str(pack.relative_to(args.client)), "error": str(exc)})
            else:
                records.append({"resource": resource, "materials": names, "state": "unresolved", "attempts": attempts})
    (out / "bindings.json").write_text(json.dumps({"materials": bindings, "source_quality": qualities,
        "surface_materials":surface_bindings, "camo_materials":camo_bindings, "camo_approximation":"mean slot-1 RGB blended by original C alpha; not UV2 tile rendering"}, indent=2), encoding="utf-8")
    (out / "texture-discovery.json").write_text(json.dumps({"resources": records, "index_errors": errors}, indent=2), encoding="utf-8")
    print(json.dumps({"bound_materials": len(bindings), "unresolved": [r["resource"] for r in records if r["state"] == "unresolved"]}))


if __name__ == "__main__":
    main()
