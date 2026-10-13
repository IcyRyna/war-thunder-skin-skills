#!/usr/bin/env python3
"""Read-only War Thunder skin inventory, BLK lint, and DDS/TGA previews.

Python 3.10+. Scanning headers needs only the standard library. Previewing and
sampling RGBA channels additionally requires Pillow: python -m pip install Pillow.
All output is written outside the scanned package; source assets are never edited.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import struct
import sys
from typing import Any

MAX_BLK_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_PIXELS = 8192 * 8192
TEXTURE_SUFFIXES = {".dds", ".tga"}
TOKEN = re.compile(
    r'(?P<space>\s+)|(?P<comment>//[^\r\n]*|/\*[\s\S]*?\*/)|'
    r'(?P<string>"(?:\\.|[^"\\])*")|(?P<punct>[{}:=;])|'
    r'(?P<word>[^\s{}:=;"/]+)|(?P<bad>.)'
)
DXGI_NAMES = {
    28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB",
    71: "BC1_UNORM", 72: "BC1_UNORM_SRGB",
    74: "BC2_UNORM", 75: "BC2_UNORM_SRGB",
    77: "BC3_UNORM", 78: "BC3_UNORM_SRGB",
    80: "BC4_UNORM", 81: "BC4_SNORM",
    83: "BC5_UNORM", 84: "BC5_SNORM",
    87: "B8G8R8A8_UNORM", 91: "B8G8R8A8_UNORM_SRGB",
    95: "BC6H_UF16", 96: "BC6H_SF16",
    98: "BC7_UNORM", 99: "BC7_UNORM_SRGB",
}


class BlkError(ValueError):
    pass


def parse_blk(source: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse typed scalar assignments and nested blocks, without executing includes.

    Deliberately reject unsupported syntax instead of presenting a partial parse
    as a valid configuration. Quoted comment markers and braces stay in strings.
    """
    tokens = []
    for match in TOKEN.finditer(source):
        kind = match.lastgroup
        if kind in {"space", "comment"}:
            continue
        line = source.count("\n", 0, match.start()) + 1
        if kind == "bad":
            raise BlkError(f"Unsupported token {match.group()!r} at line {line}")
        tokens.append((kind, match.group(), line))
    position = 0

    def consume(value: str | None = None) -> tuple[str, str, int]:
        nonlocal position
        if position >= len(tokens):
            raise BlkError("Unexpected end of BLK")
        token = tokens[position]
        if value is not None and token[1] != value:
            raise BlkError(f"Expected {value!r} at line {token[2]}, got {token[1]!r}")
        position += 1
        return token

    def scope(nested: bool = False, depth: int = 0):
        if depth > 32:
            raise BlkError("BLK nesting exceeds 32 levels")
        fields, blocks = [], []
        while position < len(tokens):
            if tokens[position][1] == "}":
                if not nested:
                    raise BlkError(f"Unmatched closing brace at line {tokens[position][2]}")
                consume("}")
                return fields, blocks
            if tokens[position][1] == ";":
                consume(";")
                continue
            kind, key, line = consume()
            if kind != "word":
                raise BlkError(f"Expected a field or block name at line {line}")
            if position < len(tokens) and tokens[position][1] == "{":
                consume("{")
                child_fields, child_blocks = scope(True, depth + 1)
                blocks.append({"kind": key, "line": line,
                               "fields": child_fields, "blocks": child_blocks})
            else:
                consume(":")
                field_kind, field_type, field_line = consume()
                if field_kind != "word":
                    raise BlkError(f"Expected a field type at line {field_line}")
                consume("=")
                value_kind, value, value_line = consume()
                if value_kind not in {"string", "word"}:
                    raise BlkError(f"Expected a scalar value at line {value_line}")
                if field_type == "t" and value_kind != "string":
                    raise BlkError(f"Text field {key!r} needs quotes at line {value_line}")
                if value_kind == "string":
                    value = value[1:-1]
                    value = re.sub(r'\\(["\\])', lambda m: m.group(1), value)
                fields.append({"key": key, "type": field_type,
                               "value": value, "line": line})
        if nested:
            raise BlkError("Unclosed block")
        return fields, blocks

    return scope()


def texture_header(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"bytes": path.stat().st_size}
    with path.open("rb") as handle:
        header = handle.read(148)
    if path.suffix.lower() == ".dds":
        if len(header) < 128 or header[:4] != b"DDS ":
            raise ValueError("Invalid or truncated DDS header")
        values = struct.unpack_from("<31I", header, 4)
        if values[0] != 124 or values[18] != 32:
            raise ValueError("Invalid DDS header size")
        flags, height, width, pitch, depth, mips = values[1:7]
        pf_flags, fourcc, bits = values[19:22]
        code = struct.pack("<I", fourcc).decode("ascii", errors="replace")
        masks = values[22:26]
        if code == "DX10":
            if len(header) < 148:
                raise ValueError("Truncated DX10 extension")
            dxgi, dimension, misc, array_size, misc2 = struct.unpack_from("<5I", header, 128)
            result.update(dxgi_format=dxgi, resource_dimension=dimension,
                          array_size=array_size, alpha_mode=misc2 & 7)
            format_name = DXGI_NAMES.get(dxgi, f"DXGI_{dxgi}")
        elif pf_flags & 4:
            format_name = {"DXT1": "DXT1 / BC1", "DXT3": "DXT3 / BC2",
                           "DXT5": "DXT5 / BC3", "ATI1": "ATI1 / BC4",
                           "ATI2": "ATI2 / BC5"}.get(code, code)
        else:
            format_name = f"{'RGBA' if masks[3] else 'RGB'}{bits} uncompressed"
        result.update(container="DDS", width=width, height=height, format=format_name,
                      mip_count=max(1, mips), mip_count_declared=mips,
                      pixel_format_flags=pf_flags, bit_count=bits,
                      channel_masks=list(masks), caps2=values[27], depth=depth,
                      row_pitch=pitch if flags & 8 else 0)
        # Single-surface BC formats have deterministic storage sizes. Verify the
        # top level so a valid-looking header cannot hide a truncated payload.
        block_bytes = None
        if code in {"DXT1", "ATI1", "BC4U", "BC4S"}:
            block_bytes = 8
        elif code in {"DXT3", "DXT5", "ATI2", "BC5U", "BC5S"}:
            block_bytes = 16
        elif code == "DX10":
            if result["dxgi_format"] in {71, 72, 80, 81}:
                block_bytes = 8
            elif result["dxgi_format"] in {74, 75, 77, 78, 83, 84, 95, 96, 98, 99}:
                block_bytes = 16
        if block_bytes:
            levels = max(1, mips)
            max_levels = max(width, height).bit_length()
            if levels > max_levels:
                raise ValueError("DDS declares too many mip levels")
            required = (148 if code == "DX10" else 128) + sum(
                max(1, (max(1, width >> level) + 3) // 4)
                * max(1, (max(1, height >> level) + 3) // 4) * block_bytes
                for level in range(levels)
            )
            if result["bytes"] < required:
                raise ValueError(f"Truncated DDS payload: needs at least {required} bytes")
    else:
        if len(header) < 18:
            raise ValueError("Truncated TGA header")
        image_type = header[2]
        width, height = struct.unpack_from("<HH", header, 12)
        bits, descriptor = header[16:18]
        if image_type not in {1, 2, 3, 9, 10, 11}:
            raise ValueError(f"Unsupported TGA image type {image_type}")
        result.update(container="TGA", width=width, height=height,
                      format=f"TGA {bits}-bit {'RLE' if image_type >= 9 else 'raw'}",
                      bit_count=bits, alpha_bits=descriptor & 15,
                      top_origin=bool(descriptor & 32), mip_count=1)
    if result["width"] < 1 or result["height"] < 1:
        raise ValueError("Texture has zero dimensions")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def role_for(source: str) -> str:
    name = source.lower().rstrip("*")
    if re.search(r"(?:_n|_n_dmg)$", name):
        return "packed_material"
    if "camo" in name:
        return "tile_camo"
    if "flame" in name:
        return "effect"
    if "coating" in name:
        return "coating"
    if re.search(r"(?:_c|_a|_c_dmg|_a_dmg)$", name):
        return "albedo"
    return "unknown"


def ensure_external_output(source: Path, output: Path) -> Path:
    source, output = source.resolve(), output.resolve()
    forbidden = source if source.is_dir() else source.parent
    if output == forbidden or forbidden in output.parents:
        raise ValueError("Output must be outside the source skin directory")
    output.mkdir(parents=True, exist_ok=True)
    return output


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inventory(root: Path, hashes: bool = False) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Skin directory not found: {root}")
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(root).as_posix().casefold())
    textures: dict[str, Any] = {}
    configs, issues = [], []
    references: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def issue(level: str, code: str, file: str, message: str, line: int | None = None):
        item = {"level": level, "code": code, "file": file, "message": message}
        if line is not None:
            item["line"] = line
        issues.append(item)

    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in TEXTURE_SUFFIXES:
            try:
                item = texture_header(path)
                if hashes:
                    item["sha256"] = sha256(path)
                textures[relative] = item
                if item["mip_count"] == 1 and path.suffix.lower() == ".dds" and max(item["width"], item["height"]) > 128:
                    issue("warning", "no_mip_chain", relative,
                          "DDS has only a top level; inspect distant aliasing in game")
            except (OSError, ValueError, struct.error) as exc:
                textures[relative] = {"error": str(exc)}
                issue("error", "invalid_texture", relative, str(exc))

    for path in (p for p in files if p.suffix.lower() == ".blk"):
        relative = path.relative_to(root).as_posix()
        entry: dict[str, Any] = {"file": relative, "vehicle_id": path.stem,
                                 "package": path.parent.relative_to(root).as_posix(),
                                 "mappings": []}
        configs.append(entry)
        try:
            if path.stat().st_size > MAX_BLK_BYTES:
                raise BlkError("BLK exceeds the 2 MiB inspection limit")
            raw = path.read_bytes()
            try:
                source = raw.decode("utf-8-sig")
                entry["encoding"] = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
            except UnicodeDecodeError:
                source = raw.decode("cp1252")
                entry["encoding"] = "cp1252"
                issue("warning", "legacy_encoding", relative, "BLK is not UTF-8")
            fields, blocks = parse_blk(source)
            entry["fields"] = fields
        except (OSError, ValueError) as exc:
            issue("error", "invalid_blk", relative, str(exc))
            continue
        names = [f["value"] for f in fields if f["key"] == "name" and f["type"] == "t"]
        if names != ["user"]:
            issue("error", "user_name", relative, 'Expected exactly one name:t="user"')
        for field in fields:
            if field["key"] != "name":
                issue("warning", "unhandled_field", relative,
                      f"Top-level field {field['key']}:{field['type']} needs manual review", field["line"])
        seen: dict[str, dict[str, Any]] = {}
        for block in blocks:
            kind, line = block["kind"], block["line"]
            if kind not in {"replace_tex", "set_tex"}:
                issue("warning", "unhandled_block", relative, f"Block {kind!r} needs manual review", line)
                continue
            if block["blocks"]:
                issue("error", "nested_mapping", relative, "Texture mappings must contain scalar fields", line)
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for field in block["fields"]:
                grouped[field["key"]].append(field)
            for key, values in grouped.items():
                if len(values) > 1:
                    issue("error", "duplicate_field", relative, f"Repeated {key!r} field in mapping", line)
                if key not in {"from", "to", "param"}:
                    issue("warning", "unhandled_mapping_field", relative, f"Unexpected mapping field {key!r}", line)
            mapping = {"kind": kind, "line": line}
            for key in ("from", "to", "param"):
                if grouped.get(key):
                    mapping[key] = grouped[key][-1]["value"]
                    if grouped[key][-1]["type"] != "t":
                        issue("error", "mapping_field_type", relative, f"{key!r} must be a text field", line)
            entry["mappings"].append(mapping)
            if not mapping.get("from") or not mapping.get("to"):
                issue("error", "missing_mapping_field", relative, "Mapping needs nonempty from:t and to:t", line)
                continue
            source_name, target = mapping["from"], mapping["to"]
            mapping["role"] = role_for(source_name)
            if kind == "set_tex" and mapping.get("param") != "camo_skin_tex":
                issue("error", "set_tex_param", relative, 'set_tex needs param:t="camo_skin_tex"', line)
            if kind == "set_tex" and mapping["role"] == "packed_material":
                issue("error", "normal_as_set_tex", relative, "Packed normal/material maps should use replace_tex", line)
            if kind == "replace_tex" and "param" in mapping:
                issue("warning", "param_on_replace", relative, "param is present on replace_tex; do not infer set_tex behavior", line)
            previous = seen.get(source_name)
            if previous:
                signature = (kind, target, mapping.get("param"))
                old_signature = (previous["kind"], previous["to"], previous.get("param"))
                code = "duplicate_mapping" if signature == old_signature else "conflicting_mapping"
                issue("warning", code, relative,
                      f"{source_name!r} repeats line {previous['line']}; engine precedence not verified", line)
            seen[source_name] = mapping
            portable = target.replace("\\", "/")
            if "*" in target or "?" in target:
                issue("warning", "wildcard_target", relative,
                      "to contains a wildcard; file lookup is unresolved and needs manual verification", line)
                continue
            if Path(portable).is_absolute() or PureWindowsPath(target).drive:
                issue("error", "absolute_target", relative, "to must identify a package-relative texture", line)
                continue
            resolved = (path.parent / portable).resolve()
            if path.parent.resolve() not in resolved.parents:
                issue("error", "outside_package", relative, "to resolves outside its skin package", line)
                continue
            target_relative = resolved.relative_to(root).as_posix()
            if not resolved.is_file():
                mapping["target_file"] = target_relative
                references[target_relative].append({"config": relative, **mapping})
                issue("error", "missing_texture", relative, f"Missing target: {target}", line)
                continue
            actual = path.parent
            for component in Path(portable).parts:
                matches = [p for p in actual.iterdir() if p.name.casefold() == component.casefold()]
                exact = next((p for p in matches if p.name == component), None)
                if exact is None and matches:
                    issue("warning", "case_mismatch", relative,
                          f"Target case differs from the on-disk filename: {target}", line)
                actual = exact or (matches[0] if matches else actual / component)
            target_relative = actual.resolve().relative_to(root).as_posix()
            mapping["target_file"] = target_relative
            references[target_relative].append({"config": relative, **mapping})
            if resolved.suffix.lower() not in TEXTURE_SUFFIXES:
                issue("error", "unsupported_target", relative, f"Target is not DDS/TGA: {target}", line)
        if not entry["mappings"]:
            issue("error", "no_mappings", relative, "No texture mappings found")

    for relative, texture in textures.items():
        texture["used_by"] = references.get(relative, [])
        texture["roles"] = sorted({m["role"] for m in references.get(relative, [])})
        if not texture["used_by"]:
            issue("info", "unreferenced_texture", relative,
                  "No literal BLK target references this file; it may be an alternate asset")
    total_bytes = sum(p.stat().st_size for p in files)
    summary = {
        "file_count": len(files), "top_level_directories": len([p for p in root.iterdir() if p.is_dir()]),
        "package_count": len({c["package"] for c in configs}), "config_count": len(configs),
        "texture_count": len(textures), "total_bytes": total_bytes,
        "extensions": dict(sorted(Counter(p.suffix.lower() or "(none)" for p in files).items())),
        "mapping_kinds": dict(Counter(m["kind"] for c in configs for m in c["mappings"])),
        "formats": dict(Counter(t.get("format", "invalid") for t in textures.values())),
        "dimensions": dict(Counter(f"{t['width']}x{t['height']}" for t in textures.values() if "width" in t)),
        "mip_counts": dict(Counter(str(t["mip_count"]) for t in textures.values() if "mip_count" in t)),
        "issue_levels": dict(Counter(i["level"] for i in issues)),
        "issue_codes": dict(Counter(i["code"] for i in issues)),
    }
    return {"schema_version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "root": str(root), "summary": summary, "configs": configs,
            "textures": textures, "issues": issues,
            "limitations": ["Static package inspection does not verify game resource names or UV compatibility.",
                            "Header checks do not decode every mip, face, array slice, or uncompressed payload.",
                            "The parser supports typed scalars and blocks; it does not execute includes.",
                            "Duplicate and overlapping mappings need an in-game check; no precedence is assumed."]}


def report_markdown(data: dict[str, Any]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    summary = data["summary"]
    lines = ["# War Thunder UserSkins inspection", "", f"Source: `{data['root']}`", "",
             f"{summary['package_count']} skin package directories; {summary['config_count']} BLKs; "
             f"{summary['texture_count']} textures; {summary['total_bytes'] / (1024**3):.2f} GiB including archives.", "",
             "## Texture storage", "", "| Format | Files |", "| --- | ---: |"]
    lines.extend(f"| {cell(key)} | {value} |" for key, value in sorted(summary["formats"].items()))
    lines.extend(["", "## Packages and resource mappings", "",
                  "| BLK | replace_tex | set_tex | Unique targets |", "| --- | ---: | ---: | ---: |"])
    for config in data["configs"]:
        kinds = Counter(m["kind"] for m in config["mappings"])
        targets = {m.get("target_file") for m in config["mappings"] if m.get("target_file")}
        lines.append(f"| {cell(config['file'])} | {kinds['replace_tex']} | {kinds['set_tex']} | {len(targets)} |")
    lines.extend(["", "## Static inspection findings", "",
                  "These are package checks; they are not claims about in-game appearance.", "",
                  "| Level | Code | File:line | Finding |", "| --- | --- | --- | --- |"])
    for item in data["issues"]:
        location = item["file"] + (f":{item['line']}" if "line" in item else "")
        lines.append(f"| {cell(item['level'])} | {cell(item['code'])} | {cell(location)} | {cell(item['message'])} |")
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {text}" for text in data["limitations"])
    return "\n".join(lines) + "\n"


def pillow_modules():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageStat
    except ImportError as exc:
        raise ValueError("Previews require Pillow: python -m pip install Pillow") from exc
    return Image, ImageDraw, ImageFont, ImageStat


def load_font(size: int):
    _, _, ImageFont, _ = pillow_modules()
    candidates = [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/arial.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def open_rgba(path: Path):
    Image, _, _, _ = pillow_modules()
    meta = texture_header(path)
    if meta["width"] * meta["height"] > MAX_PREVIEW_PIXELS:
        raise ValueError("Preview decode limit is 8192 x 8192 pixels; inspect this texture with a streaming tool")
    if meta.get("array_size", 1) > 1 or meta.get("depth", 0) > 1 or meta.get("caps2", 0) & 0x200:
        raise ValueError("Previewing DDS arrays, volumes, and cubemaps is not supported")
    # Pillow's generic legacy DDS RGB decoder may process every pixel in Python.
    # Common byte-aligned DDS masks can use the compiled raw decoder directly.
    if meta["container"] == "DDS" and meta["pixel_format_flags"] & 64:
        modes = {
            (32, (0xFF, 0xFF00, 0xFF0000, 0xFF000000)): ("RGBA", "RGBA"),
            (32, (0xFF0000, 0xFF00, 0xFF, 0xFF000000)): ("RGBA", "BGRA"),
            (32, (0xFF, 0xFF00, 0xFF0000, 0)): ("RGB", "RGBX"),
            (32, (0xFF0000, 0xFF00, 0xFF, 0)): ("RGB", "BGRX"),
            (24, (0xFF, 0xFF00, 0xFF0000, 0)): ("RGB", "RGB"),
            (24, (0xFF0000, 0xFF00, 0xFF, 0)): ("RGB", "BGR"),
        }
        mode = modes.get((meta["bit_count"], tuple(meta["channel_masks"])))
        if mode:
            packed_row = meta["width"] * meta["bit_count"] // 8
            stride = meta["row_pitch"] or packed_row
            if stride < packed_row:
                raise ValueError("DDS row pitch is smaller than its pixel width")
            required = stride * meta["height"]
            if meta["bytes"] < 128 + required:
                raise ValueError("Truncated uncompressed DDS top level")
            with path.open("rb") as handle:
                handle.seek(128)
                pixels = handle.read(required)
            image = Image.frombytes(mode[0], (meta["width"], meta["height"]),
                                    pixels, "raw", mode[1], stride, 1)
            return image if mode[0] == "RGBA" else image.convert("RGBA"), meta
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGBA")
    return image, meta


def channel_preview(path: Path, output: Path, size: int) -> dict[str, Any]:
    Image, ImageDraw, _, ImageStat = pillow_modules()
    image, meta = open_rgba(path)
    meta["file"] = str(path.resolve())
    meta["sha256"] = sha256(path)
    meta["channel_stats"] = {}
    # Resize RGB separately: resizing RGBA premultiplies alpha and destroys the
    # visible RGB of alpha-zero paint masks and packed material channels.
    rgb = image.convert("RGB")
    rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
    rgb.save(output / "rgb.png")
    channels = image.split()
    font = load_font(18)
    tile_width = max(320, rgb.width)
    tile_height = rgb.height + 45
    sheet = Image.new("RGB", (tile_width * 3, tile_height * 2), (242, 240, 236))
    draw = ImageDraw.Draw(sheet)
    previews = [("RGB (alpha ignored)", rgb)]
    for label, channel in zip("RGBA", channels):
        stats = ImageStat.Stat(channel)
        extrema = channel.getextrema()
        meta["channel_stats"][label] = {"min": extrema[0], "max": extrema[1],
                                        "mean": round(stats.mean[0], 3),
                                        "stddev": round(stats.stddev[0], 3)}
        channel.thumbnail((size, size), Image.Resampling.LANCZOS)
        channel.save(output / f"{label.lower()}.png")
        previews.append((label, channel.convert("RGB")))
        channel.close()
    image.close()
    for index, (label, preview) in enumerate(previews):
        x, y = (index % 3) * tile_width, (index // 3) * tile_height
        draw.text((x + 10, y + 10), label, fill=(28, 30, 32), font=font)
        sheet.paste(preview, (x + (tile_width - preview.width) // 2, y + 40))
        preview.close()
    draw.text((tile_width * 2 + 10, tile_height + 10),
              f"{meta['width']} x {meta['height']}\n{meta['format']}\n{meta['mip_count']} mip level(s)",
              fill=(28, 30, 32), font=font, spacing=10)
    sheet.save(output / "channels.png")
    sheet.close()
    write_json(output / "texture.json", meta)
    return meta


def contact_sheet(root: Path, data: dict[str, Any], output: Path, limit: int) -> list[dict[str, Any]]:
    Image, ImageDraw, _, _ = pillow_modules()
    selected, used = [], set()
    for config in data["configs"]:
        if config["package"] in used:
            continue
        candidates = [m for m in config["mappings"] if m.get("role") == "albedo"
                      and m.get("target_file") in data["textures"]]
        if candidates:
            selected.append(candidates[0]["target_file"])
            used.add(config["package"])
        if len(selected) >= limit:
            break
    columns, width, height = 4, 420, 370
    rows = max(1, (len(selected) + columns - 1) // columns)
    sheet = Image.new("RGB", (width * columns, height * rows), (242, 240, 236))
    draw, font = ImageDraw.Draw(sheet), load_font(14)
    index = []
    preview_dir = output / "previews"
    preview_dir.mkdir(exist_ok=True)
    for number, relative in enumerate(selected):
        x, y = number % columns * width, number // columns * height
        try:
            rgba, meta = open_rgba(root / relative)
            preview = rgba.convert("RGB")
            rgba.close()
            preview.thumbnail((width - 20, height - 95), Image.Resampling.LANCZOS)
            filename = f"{number + 1:03d}.png"
            preview.save(preview_dir / filename)
            sheet.paste(preview, (x + (width - preview.width) // 2, y + 5))
            preview.close()
            item = {"number": number + 1, "texture": relative,
                    "preview": f"previews/{filename}", "width": meta["width"], "height": meta["height"]}
            label = f"{number + 1:02d}  {relative}"
        except (OSError, ValueError, NotImplementedError) as exc:
            item = {"number": number + 1, "texture": relative, "error": str(exc)}
            label = f"{number + 1:02d}  DECODE ERROR: {relative}"
        index.append(item)
        label_lines, current = [], ""
        for char in label:
            if current and draw.textlength(current + char, font=font) > width - 20:
                label_lines.append(current)
                current = ""
            current += char
        label_lines.append(current)
        draw.multiline_text((x + 10, y + height - 88), "\n".join(label_lines[:4]),
                            fill=(28, 30, 32), font=font, spacing=3)
    sheet.save(output / "contact-sheet.png")
    sheet.close()
    write_json(output / "previews.json", index)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    scan = subcommands.add_parser("scan", help="Inventory textures and lint all BLKs")
    scan.add_argument("root", type=Path)
    scan.add_argument("--out", type=Path, required=True)
    scan.add_argument("--hash", action="store_true", help="SHA-256 each texture (reads all texture bytes)")
    scan.add_argument("--previews", type=int, default=0, metavar="COUNT",
                      help="Preview one albedo per package, up to COUNT")
    scan.add_argument("--strict", action="store_true", help="Return exit code 2 on detected errors")
    preview = subcommands.add_parser("preview", help="Inspect RGB and RGBA channels of one texture")
    preview.add_argument("texture", type=Path)
    preview.add_argument("--out", type=Path, required=True)
    preview.add_argument("--size", type=int, default=768, help="Maximum side of each channel thumbnail")
    args = parser.parse_args()
    try:
        if args.command == "scan":
            if args.previews < 0 or args.previews > 200:
                raise ValueError("--previews must be between 0 and 200")
            output = ensure_external_output(args.root, args.out)
            data = inventory(args.root, args.hash)
            write_json(output / "inventory.json", data)
            (output / "report.md").write_text(report_markdown(data), encoding="utf-8")
            if args.previews:
                previews = contact_sheet(args.root.resolve(), data, output, args.previews)
                data["summary"]["preview_decode_errors"] = sum("error" in p for p in previews)
                write_json(output / "inventory.json", data)
            print(json.dumps({"output": str(output), "summary": data["summary"]}, ensure_ascii=False, indent=2))
            return 2 if args.strict and data["summary"]["issue_levels"].get("error", 0) else 0
        if not 128 <= args.size <= 2048:
            raise ValueError("--size must be between 128 and 2048")
        output = ensure_external_output(args.texture, args.out)
        meta = channel_preview(args.texture, output, args.size)
        print(json.dumps({"output": str(output), "texture": meta}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, NotImplementedError, struct.error) as exc:
        print(f"Inspection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
