#!/usr/bin/env python3
"""War Thunder asset extraction: containers, model nodes, UVs and texture links."""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import traceback

from archives import DxpArchive, FormatError, GrpArchive, VromfsArchive, read_archive, safe_target
from mesh_export import AssemblyWriter, decode_parts, filename, write_part


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def output_dir(source: Path, output: Path, overwrite: bool):
    source, output = source.resolve(), output.resolve()
    protected = source if source.is_dir() else source.parent
    if output == protected or protected in output.parents:
        raise FormatError("Output must be outside the input/game directory")
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FormatError(f"Output is not empty: {output}; use a new directory or --overwrite")
    output.mkdir(parents=True, exist_ok=True)
    return output


def inspect(path: Path, match: str):
    archive = read_archive(path)
    entries = [e for e in archive.entries if fnmatch.fnmatchcase(e.name, match)]
    return archive, {"source": str(path.resolve()), "metadata": archive.metadata,
                     "matched_count": len(entries), "entries": [e.json() for e in entries]}


def extract(path: Path, output: Path, match: str):
    archive, manifest = inspect(path, match)
    written = []
    for entry in archive.entries:
        if not fnmatch.fnmatchcase(entry.name, match):
            continue
        if isinstance(archive, VromfsArchive):
            relative = entry.name
        elif isinstance(archive, DxpArchive):
            if not entry.size:
                continue
            relative = "textures/" + filename(entry.name.rstrip("*")) + ".ddsx"
        else:
            kind = {0xB4B7D9C4: "dynmodel", 0x56F81B6D: "skeleton", 0xACE50000: "collision"}.get(entry.class_id, "resource")
            relative = f"resources/{filename(entry.name)}.{kind}.bin"
        target = safe_target(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = archive.read(entry)
        target.write_bytes(data)
        written.append({"resource": entry.name, "file": target.relative_to(output).as_posix(),
                        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest["written"] = written
    manifest["representation"] = "Container decoded; entries preserve their inner binary formats."
    save_json(output / "manifest.json", manifest)
    return manifest


def game_packs(root: Path):
    files = [p for folder in (root / "patch", root / "content", root / "content.hq")
             if folder.is_dir() for p in folder.rglob("*.grp")]
    return sorted(files, key=lambda p: (0 if "patch" in p.relative_to(root).parts else 1,
                                       p.relative_to(root).as_posix().casefold()))


def locate(root: Path, name: str):
    matches, errors = [], []
    for path in game_packs(root):
        try:
            archive = GrpArchive(path)
            for entry in archive.entries:
                if name.casefold() in entry.name.casefold():
                    matches.append({"pack": str(path), **entry.json()})
        except (OSError, ValueError) as exc:
            errors.append({"pack": str(path), "error": str(exc)})
    return {"game": str(root.resolve()), "query": name, "matches": matches, "errors": errors}


def template_images(template: Path | None, output: Path):
    if template is None:
        return {}, []
    from PIL import Image
    blks = list(template.glob("*.blk"))
    if len(blks) != 1:
        raise FormatError("Template directory must contain exactly one BLK")
    text = blks[0].read_text(encoding="utf-8-sig")
    mapping_pattern = re.compile(r'(?:replace_tex|set_tex)\s*\{\s*from:t\s*=\s*"([^"\r\n]+)"\s*to:t\s*=\s*"([^"\r\n]+)"(?:\s*param:t\s*=\s*"[^"\r\n]+")?\s*\}')
    matches = list(mapping_pattern.finditer(text))
    residue = mapping_pattern.sub("", text)
    residue = re.sub(r'name:t\s*=\s*"user"', "", residue).strip()
    if residue or not matches:
        raise FormatError("Template BLK is outside the supported simple mapping syntax; use an exported game template")
    textures = output / "textures"
    textures.mkdir(exist_ok=True)
    originals = output / "template"
    originals.mkdir(exist_ok=True)
    links, records = {}, []
    for match in matches:
        source, target_name = match.groups()
        target = safe_target(template.resolve(), target_name)
        if target.suffix.lower() not in {".dds", ".tga"} or not target.is_file():
            raise FormatError(f"Template target missing or unsupported: {target_name}")
        basename = filename(source.rstrip("*"))
        copied = safe_target(originals, target_name)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, copied)
        with Image.open(target) as image:
            image.load()
            rgba = image.convert("RGBA")
        rgb = rgba.convert("RGB")
        rgb_path = textures / (basename + "_rgb.png")
        rgb.save(rgb_path)
        alpha_path = textures / (basename + "_alpha.png")
        alpha = rgba.getchannel("A")
        alpha.save(alpha_path)
        records.append({"resource": source, "source": str(target), "width": rgba.width,
                        "height": rgba.height, "original": copied.relative_to(output).as_posix(),
                        "rgb_proxy": rgb_path.relative_to(output).as_posix(),
                        "alpha_data": alpha_path.relative_to(output).as_posix(),
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        links[source] = rgb_path.relative_to(output).as_posix()
        for bitmap in (alpha, rgb, rgba):
            bitmap.close()
    shutil.copy2(blks[0], originals / blks[0].name)
    return links, records


def material_table(model, links):
    table = []
    for index, material in enumerate(model.materials or []):
        slots = material.getTextureSlots()
        texture = slots[0] if slots else None
        proxy = next((value for pattern, value in links.items()
                      if texture and fnmatch.fnmatchcase(texture.rstrip("*"), pattern)), None)
        table.append({"index": index, "name": str(material.getName()),
                      "obj_name": filename(str(material.getName())), "shader": material.cls,
                      "texture_slots": slots, "parameters": material.par, "albedo_proxy": proxy})
    return table


def write_mtl(output: Path, materials: list[dict]):
    emitted = set()
    with (output / "materials.mtl").open("w", encoding="utf-8", newline="\n") as stream:
        for material in materials:
            name = material["obj_name"]
            if name in emitted:
                continue
            emitted.add(name)
            stream.write(f"newmtl {name}\nKa 0.2 0.2 0.2\nKd 0.8 0.8 0.8\nKs 0 0 0\nd 1\n")
            if material["albedo_proxy"]:
                stream.write("map_Kd " + material["albedo_proxy"] + "\n")
            stream.write("\n")


def export_model(source: Path, name: str, lod: int, output: Path, part_match: str, template: Path | None):
    from dae_backend import load_model, PINNED_DAE
    source = source.resolve()
    if source.is_dir():
        found = locate(source, name)
        save_json(output / "resource-index.json", found)
        exact = [e for e in found["matches"] if e["name"] == name and e["class_id"] == 0xB4B7D9C4]
        if not exact:
            raise FormatError(f"No DynModel named {name!r} in this installation")
        pack = Path(exact[0]["pack"])
        candidates = [source / "patch/content/base/res/dynModelDesc.bin", source / "content/base/res/dynModelDesc.bin"]
    else:
        pack, candidates = source, []
        for parent in source.parents:
            if (parent / "content/base/res/dynModelDesc.bin").is_file():
                candidates = [parent / "patch/content/base/res/dynModelDesc.bin", parent / "content/base/res/dynModelDesc.bin"]
                break
    links, templates = template_images(template, output)
    with (output / "decoder.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        model, runtime = load_model(pack, name, lod, candidates)
    materials = material_table(model, links)
    write_mtl(output, materials)
    parts_dir = output / "parts"
    parts_dir.mkdir(exist_ok=True)
    assembly = AssemblyWriter(output / "assembly.obj")
    parts = []
    try:
        for mesh, node, skinned in decode_parts(model):
            if not fnmatch.fnmatchcase(mesh.name, part_match):
                continue
            part_file = f"{len(parts) + 1:03d}_{filename(mesh.name)}.obj"
            write_part(parts_dir / part_file, mesh, "../materials.mtl")
            assembly.append(mesh)
            parts.append({"name": mesh.name, "file": "parts/" + part_file,
                          "vertices": len(mesh.vertices), "faces": len(mesh.faces),
                          "materials": sorted(set(mesh.materials)), "bounds": mesh.bounds,
                          "uv_bounds": {"min": [min(v[i] for v in mesh.uvs) for i in range(2)],
                                        "max": [max(v[i] for v in mesh.uvs) for i in range(2)]},
                          "skinned_bind_pose": bool(skinned),
                          "source_node_world_transform": node.wtm if node is not None else None})
    finally:
        assembly.close()
    if not parts:
        raise FormatError("No nonempty parts match the requested pattern")
    summary = {"model": name, "lod": lod, "source_pack": str(pack), "decoder_revision": PINNED_DAE,
               "parts": len(parts), "exported_vertices": sum(p["vertices"] for p in parts),
               "triangles": sum(p["faces"] for p in parts), "materials": len(materials),
               "coordinates": "DAE OBJ convention: native X/Y, reflected Z; assembly transforms applied; no scale multiplier.",
               "uv": "Original decoded UVs, no re-unwrapping, no clamping, no V flip; 10 significant digits.",
               "normals": "Area-weighted normals regenerated from decoded triangle topology.",
               "representation": "Static bind pose; OBJ does not retain animation or skin weights."}
    save_json(output / "parts.json", {"summary": summary, "parts": parts})
    save_json(output / "materials.json", {"materials": materials, "template_textures": templates})
    save_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("list", "unpack"):
        p = commands.add_parser(command)
        p.add_argument("input", type=Path)
        p.add_argument("--match", default="*")
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--overwrite", action="store_true")
    find = commands.add_parser("find")
    find.add_argument("game", type=Path)
    find.add_argument("--name", required=True)
    find.add_argument("--out", type=Path, required=True)
    find.add_argument("--overwrite", action="store_true")
    model = commands.add_parser("model")
    model.add_argument("input", type=Path, help="Game root or exact GRP file")
    model.add_argument("--name", required=True)
    model.add_argument("--lod", type=int, default=0)
    model.add_argument("--part", default="*", help="Node-name glob; default exports all parts")
    model.add_argument("--template", type=Path, help="A simple game-generated UserSkins template")
    model.add_argument("--out", type=Path, required=True)
    model.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output = None
    try:
        source = args.game if args.command == "find" else args.input
        if not source.exists():
            raise FormatError(f"Input not found: {source}")
        output = output_dir(source, args.out, args.overwrite)
        if args.command == "list":
            _, result = inspect(source, args.match)
            save_json(output / "manifest.json", result)
            result = {"metadata": result["metadata"], "matched_count": result["matched_count"]}
        elif args.command == "unpack":
            manifest = extract(source, output, args.match)
            result = {"metadata": manifest["metadata"], "written": len(manifest["written"])}
        elif args.command == "find":
            result = locate(source.resolve(), args.name)
            save_json(output / "resource-index.json", result)
            result = {"matches": len(result["matches"]), "errors": len(result["errors"])}
        else:
            if args.lod < 0:
                raise FormatError("--lod cannot be negative")
            result = export_model(source, args.name, args.lod, output, args.part, args.template)
        print(json.dumps({"output": str(output), **result}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        if output is not None:
            (output / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"Asset extraction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
