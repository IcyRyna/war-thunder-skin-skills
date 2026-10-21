#!/usr/bin/env python3
"""Build a complete ground skin DDS package with explicit channel semantics.

The manifest declares a BLK and every texture's file, role, alpha_semantics and
color_space. Profiles declare texture_counts (default: 4 color, 4 normal, 3 AO).
The tool config declares texconv.path and texconv.sha256. Relative tool paths are
resolved against that config. Output must be a fresh directory outside input.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image

from artifact_io import ArtifactTransaction
from dds_variant import (DXGI, FORMAT_NAMES, MAX_PIXELS, TEXCONV_SHA256, _run,
                         decode_mips, mip_sizes, sha256, validate_tool,
                         write_rgba8_mips)
from texture_semantics import resize_texture, validate_alpha_semantics


DEFAULT_COUNTS = {"color": 4, "normal": 4, "ao": 3}
# A supported RGBA8 DDS source may already contain the complete square chain.
MAX_TEXTURE_BYTES = MAX_PIXELS * 16 // 3 + 4 * 1024 * 1024
_TOKEN = re.compile(r'\s+|//[^\r\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}=;]|[^\s{}=;"/]+', re.S)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return result


def _relative(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} must be a nonempty relative file path")
    # Check both path syntaxes even when tests run on another host.
    windows = PureWindowsPath(value)
    path = Path(value.replace("\\", "/"))
    if windows.drive or windows.root or path.is_absolute() or any(p in {"", ".", ".."} for p in path.parts):
        raise ValueError(f"{label} escapes its input directory: {value}")
    if ":" in value or any(c in value for c in "*?\r\n"):
        raise ValueError(f"{label} contains an unsupported path character: {value}")
    return path


def _source_path(source: Path, relative: Path) -> Path:
    path = (source / relative).resolve(strict=True)
    if not path.is_relative_to(source) or not path.is_file():
        raise ValueError(f"Texture/BLK is outside input or not a regular file: {relative}")
    return path


def _lex(text: str) -> list[str]:
    result, offset = [], 0
    for match in _TOKEN.finditer(text):
        if match.start() != offset:
            raise ValueError("Unsupported or malformed BLK syntax")
        value, offset = match.group(), match.end()
        if not value.isspace() and not value.startswith(("//", "/*")) and value != ";":
            result.append(value)
    if offset != len(text):
        raise ValueError("Unterminated string/comment or malformed BLK")
    return result


def _string(token: str) -> str:
    if not token.startswith('"') or not token.endswith('"'):
        raise ValueError("BLK texture fields require quoted strings")
    raw = token[1:-1]
    # BLK uses quoted resource paths, not arbitrary JSON escapes. Restrict
    # escapes so target resolution and rewritten game references agree.
    if re.search(r'\\[^\\"]', raw):
        raise ValueError("Unsupported escape in BLK string")
    return re.sub(r'\\([\\"])', r'\1', raw)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rewrite_blk(text: str, textures: dict[str, dict]) -> tuple[str, list[dict]]:
    """Validate the narrow game mapping grammar and rewrite all mapped targets.

    Unsupported blocks/fields are rejected instead of being silently discarded.
    The original resource wildcard and optional set_tex parameter are preserved.
    """
    tokens, cursor, mappings, blocks, sources, used = _lex(text), 0, [], [], set(), set()
    name_seen = False
    while cursor < len(tokens):
        kind = tokens[cursor]
        cursor += 1
        if kind == "name:t":
            if name_seen or tokens[cursor:cursor + 1] != ["="] or cursor + 1 >= len(tokens):
                raise ValueError("Malformed or duplicate BLK name")
            blocks.append("name:t=" + _quote(_string(tokens[cursor + 1])))
            cursor += 2
            name_seen = True
            continue
        if kind not in {"replace_tex", "set_tex"} or tokens[cursor:cursor + 1] != ["{"]:
            raise ValueError(f"Unsupported BLK block or global field: {kind}")
        cursor += 1
        fields = {}
        while cursor < len(tokens) and tokens[cursor] != "}":
            key = tokens[cursor]
            if (key not in {"from:t", "to:t", "param:t"} or key in fields
                    or tokens[cursor + 1:cursor + 2] != ["="] or cursor + 2 >= len(tokens)):
                raise ValueError("Malformed, duplicate or unsupported BLK mapping field")
            fields[key] = _string(tokens[cursor + 2])
            cursor += 3
        if cursor >= len(tokens):
            raise ValueError("Unclosed BLK mapping")
        cursor += 1
        if not fields.get("from:t") or not fields.get("to:t"):
            raise ValueError("Each BLK mapping needs from:t and to:t")
        if kind == "set_tex" and fields.get("param:t") != "camo_skin_tex":
            raise ValueError("set_tex requires param:t=\"camo_skin_tex\"")
        if kind == "replace_tex" and "param:t" in fields:
            raise ValueError("replace_tex does not support param:t")
        resource = fields["from:t"]
        if resource.casefold() in sources:
            raise ValueError(f"Duplicate/conflicting BLK source resource: {resource}")
        sources.add(resource.casefold())
        target = _relative(fields["to:t"], "BLK target").as_posix().casefold()
        if target not in textures:
            raise ValueError(f"BLK target is absent in texture manifest: {fields['to:t']}")
        item = textures[target]
        used.add(target)
        fields["to:t"] = item["output"].as_posix()
        lines = [kind + "{", "  from:t=" + _quote(resource), "  to:t=" + _quote(fields["to:t"])]
        if "param:t" in fields:
            lines.append("  param:t=" + _quote(fields["param:t"]))
        blocks.append("\n".join([*lines, "}"]))
        mappings.append({"kind": kind, "resource": resource, "source": item["file"].as_posix(),
                         "target": item["output"].as_posix(), "role": item["role"]})
    if not mappings or used != set(textures):
        raise ValueError("Every manifest texture must be mapped by the BLK")
    if not name_seen:
        blocks.insert(0, 'name:t="user"')
    return "\n\n".join(blocks) + "\n", mappings


def semantic_mips(image: Image.Image, semantics: str, color_space: str) -> list[np.ndarray]:
    """Filter each level explicitly, including rectangular tails down to 1x1."""
    current = image.convert("RGBA")
    result = [np.asarray(current).copy()]
    for size in mip_sizes(current.width, current.height)[1:]:
        current = resize_texture(current, size, semantics, color_space=color_space,
                                 resample=Image.Resampling.BOX)
        result.append(np.asarray(current).copy())
    return result


def _load_texture(path: Path, expected_sha256: str | None = None) -> Image.Image:
    encoded_size = path.stat().st_size
    if encoded_size > MAX_TEXTURE_BYTES:
        raise ValueError(f"Texture exceeds the supported byte limit: {path.name}")
    with path.open("rb") as source:
        # File.read(n) may reserve n bytes before reading. The 16k safety cap is
        # over a gigabyte, even when the source is a small RLE-compressed TGA.
        # Reserve only the validated actual size plus one growth-detection byte.
        encoded = source.read(encoded_size + 1)
    if len(encoded) != encoded_size:
        raise ValueError(f"Texture size changed while decoding was planned: {path.name}")
    if expected_sha256 is not None and hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise ValueError(f"Texture bytes changed while decoding was planned: {path.name}")
    # Pillow's generic bomb threshold is smaller than the supported 16k atlas.
    # Check the declared dimensions before decoding this explicitly bounded file.
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(BytesIO(encoded)) as bitmap:
            if bitmap.format not in {"TGA", "PNG", "DDS"}:
                raise ValueError("Manifest textures must be TGA, PNG or DDS")
            mip_sizes(bitmap.width, bitmap.height)
            bitmap.load()
            return bitmap.convert("RGBA")
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _plan(source: Path, manifest: dict, profile: dict) -> tuple[Path, list[dict], str, list[dict]]:
    blk = _relative(manifest.get("blk"), "manifest.blk")
    if blk.suffix.lower() != ".blk" or len(blk.parts) != 1:
        raise ValueError("manifest.blk must name one BLK at the skin directory root")
    _source_path(source, blk)
    entries = manifest.get("textures")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest.textures must be a nonempty list")
    counts = profile.get("texture_counts", DEFAULT_COUNTS)
    if (not isinstance(counts, dict) or set(counts) != set(DEFAULT_COUNTS)
            or any(type(v) is not int or v < 1 for v in counts.values())):
        raise ValueError("profile.texture_counts requires positive color, normal and ao counts")
    textures, outputs = {}, set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each manifest texture must be an object")
        role, semantics, space = entry.get("role"), entry.get("alpha_semantics"), entry.get("color_space")
        validate_alpha_semantics(semantics, role)
        if space not in {"srgb", "linear"} or (role != "color" and space != "linear"):
            raise ValueError("Color space must be explicit; normal and AO data must be linear")
        relative = _relative(entry.get("file"), "texture.file")
        if relative.suffix.lower() not in {".tga", ".png", ".dds"}:
            raise ValueError("Manifest textures must use .tga, .png or .dds")
        path = _source_path(source, relative)
        key, output = relative.as_posix().casefold(), relative.with_suffix(".dds")
        if key in textures or output.as_posix().casefold() in outputs:
            raise ValueError("Manifest texture files or DDS output names collide")
        outputs.add(output.as_posix().casefold())
        textures[key] = {"file": relative, "output": output, "role": role,
                         "alpha_semantics": semantics, "color_space": space,
                         "input_sha256": sha256(path)}
    actual_counts = Counter(item["role"] for item in textures.values())
    if dict(actual_counts) != counts:
        raise ValueError(f"Incomplete texture set: expected {counts}, received {dict(actual_counts)}")
    # Unlisted game textures are easy to mistake for delivered damage/AO maps.
    present = {p.relative_to(source).as_posix().casefold() for p in source.rglob("*")
               if p.is_file() and p.suffix.lower() in {".tga", ".png", ".dds"}}
    if present != set(textures):
        raise ValueError(f"Texture manifest does not match input files: {sorted(present ^ set(textures))}")
    blks = [p for p in source.rglob("*.blk") if p.is_file()]
    if len(blks) != 1 or blks[0].resolve() != (source / blk).resolve():
        raise ValueError("Input must contain exactly the declared BLK")
    text, mappings = rewrite_blk((source / blk).read_text(encoding="utf-8-sig"), textures)
    return blk, list(textures.values()), text, mappings


def _input_hashes(source: Path) -> dict[str, str]:
    return {p.relative_to(source).as_posix(): sha256(p) for p in source.rglob("*") if p.is_file()}


def convert(input_directory: Path, manifest_path: Path, profile_path: Path, config_path: Path,
            output: Path, output_format: str = "rgba8") -> dict:
    source = input_directory.resolve(strict=True)
    declared_output = output.absolute()
    if os.path.lexists(declared_output):
        raise ValueError("--out must be a fresh directory outside the input skin directory")
    output = declared_output.resolve()
    manifest_path, profile_path, config_path = (p.resolve(strict=True) for p in
                                               (manifest_path, profile_path, config_path))
    if not source.is_dir():
        raise ValueError("--input must be a skin directory")
    if output_format not in DXGI:
        raise ValueError("DDS format must be rgba8 or bc3")
    if os.path.lexists(output) or output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("--out must be a fresh directory outside the input skin directory")
    manifest, profile, config = (read_json(p) for p in (manifest_path, profile_path, config_path))
    config_hashes = {str(p): sha256(p) for p in (manifest_path, profile_path, config_path)}
    tool_config = config.get("texconv")
    if (not isinstance(tool_config, dict) or not isinstance(tool_config.get("path"), str)
            or not isinstance(tool_config.get("sha256"), str)
            or tool_config["sha256"].lower() != TEXCONV_SHA256):
        raise ValueError("config.texconv requires path and the pinned May 2026 SHA-256")
    texconv = Path(tool_config["path"])
    texconv = (config_path.parent / texconv).resolve() if not texconv.is_absolute() else texconv.resolve()
    tool = validate_tool(texconv)
    source_hashes = _input_hashes(source)
    blk, textures, blk_text, mappings = _plan(source, manifest, profile)
    if source_hashes != _input_hashes(source):
        raise ValueError("Input changed while the conversion plan was read")
    package_files = [blk, *(item["output"] for item in textures)]
    archive, mips_archive, report_path = output / "package.zip", output / "mips.zip", output / "report.json"
    outputs = [output / "skin" / relative for relative in package_files] + [archive, mips_archive, report_path]
    inputs = [source, manifest_path, profile_path, config_path, texconv]
    with ArtifactTransaction(outputs, inputs, label="ground-dds",
                             failure_directory=output.parent / ".artifact-failures") as transaction:
        staged_report = transaction.stage(report_path)
        with tempfile.TemporaryDirectory(prefix="ground-dds-", dir=staged_report.parent) as temporary:
            work, records = Path(temporary), []
            package = work / "skin"
            package.mkdir()
            with zipfile.ZipFile(transaction.stage(mips_archive), "w", zipfile.ZIP_DEFLATED) as mip_zip:
                for item in textures:
                    path = source / item["file"]
                    if sha256(path) != item["input_sha256"]:
                        raise ValueError(f"Texture changed before decoding: {item['file']}")
                    image = _load_texture(path, item["input_sha256"])
                    reference = semantic_mips(image, item["alpha_semantics"], item["color_space"])
                    image.close()
                    semantic = "color" if item["color_space"] == "srgb" else "data"
                    baseline = work / "baseline" / item["output"]
                    baseline.parent.mkdir(parents=True, exist_ok=True)
                    write_rgba8_mips(baseline, reference, semantic)
                    destination = package / item["output"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    command = [str(texconv), "-nologo", "-dx10", "-m", "0", "-if", "BOX",
                               "-nowic", "-sepalpha", "-f", FORMAT_NAMES[DXGI[output_format][semantic]],
                               "-o", str(destination.parent)]
                    if output_format == "bc3" and semantic == "data":
                        command.extend(["-bc", "u"])
                    command.append(str(baseline))
                    invocation = _run(command)
                    if not destination.is_file():
                        raise ValueError("texconv returned success without its expected DDS")
                    header, decoded = decode_mips(destination)
                    if header["dxgi"] != DXGI[output_format][semantic] or len(decoded) != len(reference):
                        raise ValueError("DDS format or complete mip chain changed")
                    mip_records = []
                    for level, (actual, expected) in enumerate(zip(decoded, reference)):
                        if actual.shape != expected.shape:
                            raise ValueError("DDS dimensions changed")
                        delta = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
                        if output_format == "rgba8" and np.any(delta):
                            raise ValueError("RGBA8 conversion changed an explicit semantic mip")
                        if not np.any(reference[0][:, :, 3]) and np.any(actual[:, :, 3]):
                            raise ValueError("All-zero source alpha changed")
                        buffer = BytesIO()
                        Image.fromarray(actual).save(buffer, format="PNG")
                        png = buffer.getvalue()
                        member = item["output"].with_suffix("").as_posix() + f"/mip-{level:02d}.png"
                        mip_zip.writestr(member, png)
                        mip_records.append({"level": level, "width": actual.shape[1], "height": actual.shape[0],
                            "decoded_rgba_sha256": hashlib.sha256(actual.tobytes()).hexdigest(),
                            "decoded_png": member, "png_sha256": hashlib.sha256(png).hexdigest(),
                            "channel_min": actual.min(axis=(0, 1)).tolist(),
                            "channel_max": actual.max(axis=(0, 1)).tolist(),
                            "mae_vs_semantic_mip": delta.mean(axis=(0, 1)).tolist(),
                            "max_abs_vs_semantic_mip": delta.max(axis=(0, 1)).tolist()})
                    top_delta = np.abs(decoded[0].astype(np.int16) - reference[0].astype(np.int16))
                    records.append({"source": item["file"].as_posix(), "target": item["output"].as_posix(),
                        "role": item["role"], "alpha_semantics": item["alpha_semantics"],
                        "color_space": item["color_space"], "input_sha256": item["input_sha256"],
                        "dds_sha256": sha256(destination), "bytes": destination.stat().st_size,
                        "header": header, "commands": [invocation], "top_rgba_exact": not bool(np.any(top_delta)),
                        "top_channel_mae": top_delta.mean(axis=(0, 1)).tolist(),
                        "top_channel_max_abs": top_delta.max(axis=(0, 1)).tolist(), "mips": mip_records})
                    # Release full-resolution arrays before decoding the next atlas.
                    del reference, decoded, top_delta, actual, expected, delta
            (package / blk).write_text(blk_text, encoding="utf-8")
            if source_hashes != _input_hashes(source) or any(sha256(Path(p)) != digest for p, digest in config_hashes.items()):
                raise ValueError("Input/configuration changed during conversion")
            if sha256(texconv) != tool["sha256"]:
                raise ValueError("texconv changed during conversion")
            with zipfile.ZipFile(transaction.stage(archive), "w", zipfile.ZIP_DEFLATED) as zipped:
                for relative in sorted(package_files):
                    path = package / relative
                    shutil.copyfile(path, transaction.stage(output / "skin" / relative))
                    zipped.write(path, (Path("skin") / relative).as_posix())
            report = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                "status": "complete_offline", "input": str(source), "output": str(output),
                "zip": str(archive), "mips_zip": str(mips_archive), "report": str(report_path),
                "format": output_format, "experimental_compression": output_format == "bc3",
                "tool": tool, "source_files_unchanged": True, "textures": records, "mappings": mappings,
                "profile_id": profile.get("id", profile.get("profile_id")),
                "texture_counts": dict(Counter(item["role"] for item in textures)),
                "input_file_hashes": source_hashes, "configuration_hashes": config_hashes,
                "zip_sha256": sha256(transaction.stage(archive)),
                "mips_zip_sha256": sha256(transaction.stage(mips_archive)),
                "semantics": {"mip_generator": "explicit per-level BOX to 1x1; texconv preserves existing mips",
                    "fixed_rgb": "linear-light RGB; alpha filtered independently, including zero alpha",
                    "opacity": "linear-light premultiplied coverage filtering, returned as straight RGBA",
                    "packed_data": "independent linear numeric channels, no normal reconstruction",
                    "scalar_data": "independent linear numeric channels, no gamma conversion"},
                "limitations": ["Runtime game shader/mip selection is not verified by offline conversion.",
                    "BC3 is a lossy experimental option; RGBA8 is the default exact pixel baseline.",
                    "Packed normal channels are numeric data; mip filtering does not normalize vectors."]}
            staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        transaction.commit()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", dest="input_directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--format", choices=["rgba8", "bc3"], default="rgba8")
    args = parser.parse_args()
    try:
        report = convert(args.input_directory, args.manifest, args.profile, args.config, args.out, args.format)
        print(json.dumps({"status": report["status"], "report": report["report"],
                          "zip": report["zip"], "mips_zip": report["mips_zip"]}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, struct.error,
            zipfile.BadZipFile, Image.DecompressionBombError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
