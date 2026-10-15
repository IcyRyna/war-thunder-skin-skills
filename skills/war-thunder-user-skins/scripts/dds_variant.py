#!/usr/bin/env python3
"""Build an independent DDS/mip variant of a verified TGA/BLK skin.

Pillow and NumPy are required. Conversion uses the pinned Microsoft DirectXTex
May 2026 texconv binary. RGBA8 is the lossless top-level baseline; BC3 is an
explicitly experimental lossy variant. Every DDS mip is decoded and archived.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image

from artifact_io import ArtifactTransaction
from inspect_skins import inventory

TEXCONV_RELEASE = "may2026"
TEXCONV_VERSION = "texconv version 2026.5.8.1"
TEXCONV_SHA256 = "dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06"
TEXCONV_URL = "https://github.com/microsoft/DirectXTex/releases/download/may2026/texconv.exe"
MAX_PIXELS = 8192 * 8192
DXGI = {"rgba8": {"color": 29, "data": 28}, "bc3": {"color": 78, "data": 77}}
FORMAT_NAMES = {28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB",
                77: "BC3_UNORM", 78: "BC3_UNORM_SRGB"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mip_sizes(width: int, height: int) -> list[tuple[int, int]]:
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise ValueError("Unsupported image dimensions")
    sizes = [(width, height)]
    while width > 1 or height > 1:
        width, height = max(1, width // 2), max(1, height // 2)
        sizes.append((width, height))
    return sizes


def _single_mip_header(width: int, height: int, dxgi: int) -> bytes:
    values = [0] * 31
    values[0:7] = [124, 0x100F, height, width,
                   width * 4 if dxgi in {28, 29} else max(1, (width + 3) // 4) * 16,
                   0, 1]
    values[18:22] = [32, 4, struct.unpack("<I", b"DX10")[0], 0]
    values[26] = 0x1000
    return b"DDS " + struct.pack("<31I", *values) + struct.pack("<5I", dxgi, 3, 0, 1, 4)


def decode_mips(path: Path) -> tuple[dict, list[np.ndarray]]:
    """Decode every surface from actual DDS payload, rejecting extra/truncated data.

    Each compressed mip is wrapped as a single-level DDS for Pillow's BC decoder.
    No mip is reconstructed by resizing the top-level image.
    """
    payload = path.read_bytes()
    if len(payload) < 148 or payload[:4] != b"DDS ":
        raise ValueError("DDS header is missing or truncated")
    header = struct.unpack_from("<31I", payload, 4)
    if header[0] != 124 or header[18] != 32 or struct.pack("<I", header[20]) != b"DX10":
        raise ValueError("Expected a DirectX 10 DDS header")
    dxgi, dimension, misc, array_size, alpha_mode = struct.unpack_from("<5I", payload, 128)
    if dxgi not in FORMAT_NAMES or dimension != 3 or misc != 0 or array_size != 1:
        raise ValueError("Expected one supported, non-cube 2D DDS texture")
    if header[5] not in {0, 1} or header[27] != 0:
        raise ValueError("DDS volume/cube surfaces are unsupported")
    sizes = mip_sizes(header[3], header[2])
    if header[6] != len(sizes):
        raise ValueError("DDS does not contain the complete mip chain to 1x1")
    decoded, offset = [], 148
    for width, height in sizes:
        count = width * height * 4 if dxgi in {28, 29} else max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
        chunk = payload[offset:offset + count]
        if len(chunk) != count:
            raise ValueError(f"Truncated mip payload at {width}x{height}")
        if dxgi in {28, 29}:
            image = np.frombuffer(chunk, np.uint8).reshape(height, width, 4).copy()
        else:
            # BC3_UNORM and BC3_UNORM_SRGB have identical block bit layouts.
            # Pillow supports 77 but not 78; relabel only this in-memory decoder
            # wrapper. Stored DDS metadata and decoded byte values stay intact.
            with Image.open(BytesIO(_single_mip_header(width, height, 77) + chunk)) as bitmap:
                bitmap.load()
                image = np.asarray(bitmap.convert("RGBA")).copy()
        if image.shape != (height, width, 4):
            raise ValueError("DDS decoder returned unexpected dimensions")
        decoded.append(image)
        offset += count
    if offset != len(payload):
        raise ValueError("DDS has unexpected trailing or additional surface data")
    return {"width": header[3], "height": header[2], "dxgi": dxgi,
            "format": FORMAT_NAMES[dxgi], "mip_count": len(sizes),
            "alpha_mode": alpha_mode, "all_mips_decoded": True}, decoded


def reference_mips(pixels: np.ndarray, semantic: str) -> list[np.ndarray]:
    """Explicit BOX mip generator: color RGB in linear light, A/data independently.

    Packed G/A remain numeric data. No photographic adjustment, premultiplication,
    normal reconstruction or normalization is silently introduced.
    """
    result = [pixels.copy()]
    for width, height in mip_sizes(pixels.shape[1], pixels.shape[0])[1:]:
        current = result[-1].astype(np.float32) / 255.0
        if semantic == "color":
            rgb = current[:, :, :3]
            current[:, :, :3] = np.where(rgb <= 0.04045, rgb / 12.92,
                                        ((rgb + 0.055) / 1.055) ** 2.4)
        channels = []
        for channel in range(4):
            with Image.fromarray(current[:, :, channel]) as plane:
                channels.append(np.asarray(plane.resize((width, height), Image.Resampling.BOX)))
        filtered = np.stack(channels, axis=2)
        if semantic == "color":
            rgb = filtered[:, :, :3]
            filtered[:, :, :3] = np.where(rgb <= 0.0031308, rgb * 12.92,
                                         1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055)
        result.append(np.clip(np.rint(filtered * 255), 0, 255).astype(np.uint8))
    return result


def write_rgba8_mips(path: Path, mips: list[np.ndarray], semantic: str) -> None:
    """Write the already-filtered numeric mip chain without image-loader policy."""
    top = mips[0]
    header = bytearray(_single_mip_header(top.shape[1], top.shape[0], DXGI["rgba8"][semantic]))
    struct.pack_into("<I", header, 8, 0x2100F)
    struct.pack_into("<I", header, 28, len(mips))
    struct.pack_into("<I", header, 108, 0x401008 if len(mips) > 1 else 0x1000)
    with path.open("wb") as stream:
        stream.write(header)
        for mip in mips:
            stream.write(mip.tobytes())


def _run(command: list[str], timeout: int = 180) -> dict:
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                 encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"texconv could not complete: {error}") from error
    result = {"command": command, "returncode": process.returncode,
              "stdout": process.stdout, "stderr": process.stderr}
    if process.returncode:
        raise ValueError("texconv failed: " + json.dumps(result, ensure_ascii=False))
    return result


def validate_tool(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"texconv executable does not exist: {path}")
    digest = sha256(path)
    if digest != TEXCONV_SHA256:
        raise ValueError("texconv does not match the pinned official May 2026 binary")
    version = _run([str(path), "--version"])
    if version["stdout"].strip() != TEXCONV_VERSION:
        raise ValueError("Unexpected texconv version")
    help_text = _run([str(path), "--help"])["stdout"]
    required = ["--tga-zero-alpha", "--ignore-srgb", "--separate-alpha", "-nowic"]
    if any(option not in help_text for option in required):
        raise ValueError("texconv lacks required channel-preservation options")
    return {"release": TEXCONV_RELEASE, "version": TEXCONV_VERSION, "sha256": digest,
            "asset_url": TEXCONV_URL, "executable": str(path),
            "required_options_verified": required}


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plan(source: Path, roles: dict[str, str]) -> tuple[dict, list[dict], list[Path], str]:
    data = inventory(source)
    serious = [issue for issue in data["issues"] if issue["level"] == "error" or
               issue["code"] in {"duplicate_mapping", "conflicting_mapping", "unhandled_field",
                                 "unhandled_block", "unhandled_mapping_field", "wildcard_target"}]
    if serious:
        raise ValueError("Input package requires correction: " + json.dumps(serious, ensure_ascii=False))
    if len(data["configs"]) != 1 or Path(data["configs"][0]["file"]).parent != Path("."):
        raise ValueError("Expected one vehicle BLK at the skin directory root")
    config = data["configs"][0]
    if set(roles) - {m["from"] for m in config["mappings"]}:
        raise ValueError("A semantic override does not match an exact from resource")
    textures = {}
    blocks = ['name:t="user"']
    for mapping in config["mappings"]:
        relative = Path(mapping["target_file"])
        if relative.suffix.lower() != ".tga":
            raise ValueError("All mapped input textures must be lossless TGA files")
        semantic = roles.get(mapping["from"])
        if semantic is None:
            if mapping["role"] in {"albedo", "tile_camo"}:
                semantic = "color"
            elif mapping["role"] == "packed_material":
                semantic = "data"
            else:
                raise ValueError(f"Unknown texture semantics for {mapping['from']}; use --role exact_from=color|data")
        if semantic not in {"color", "data"}:
            raise ValueError("Texture semantic must be color or data")
        previous = textures.get(relative.as_posix().casefold())
        if previous and previous["semantic"] != semantic:
            raise ValueError("One input texture is mapped with contradictory semantics")
        if not previous:
            # Bind the hash to the exact bytes decoded, even if another process
            # replaces the source between decoding and the final input check.
            with (source / relative).open("rb") as stream:
                source_bytes = stream.read(MAX_PIXELS * 4 + 2 * 1024 * 1024 + 1)
            if len(source_bytes) > MAX_PIXELS * 4 + 2 * 1024 * 1024:
                raise ValueError("TGA exceeds the validated byte limit")
            input_digest = hashlib.sha256(source_bytes).hexdigest()
            with Image.open(BytesIO(source_bytes)) as bitmap:
                if bitmap.format != "TGA" or bitmap.width * bitmap.height > MAX_PIXELS:
                    raise ValueError("Expected an 8-bit TGA within the validated pixel limit")
                bitmap.load()
                pixels = np.asarray(bitmap.convert("RGBA")).copy()
            textures[relative.as_posix().casefold()] = {"relative": relative,
                "output": relative.with_suffix(".dds"), "semantic": semantic,
                "pixels": pixels, "input_sha256": input_digest}
        target = relative.with_suffix(".dds").as_posix()
        body = [mapping["kind"] + "{", "  from:t=" + _quote(mapping["from"]),
                "  to:t=" + _quote(target)]
        if "param" in mapping:
            body.append("  param:t=" + _quote(mapping["param"]))
        blocks.append("\n".join([*body, "}"]))
    used = {item["relative"].as_posix().casefold() for item in textures.values()}
    unreferenced = set(name.casefold() for name in data["textures"]) - used
    if unreferenced:
        raise ValueError("Unreferenced textures need explicit disposition before conversion: " + repr(sorted(unreferenced)))
    extras = [path.relative_to(source) for path in source.rglob("*") if path.is_file()
              and path.suffix.lower() not in {".tga", ".dds", ".blk"}]
    return config, list(textures.values()), extras, "\n\n".join(blocks) + "\n"


def convert(input_directory: Path, output: Path, texconv: Path, output_format: str = "rgba8",
            roles: dict[str, str] | None = None) -> dict:
    source, output, texconv = input_directory.resolve(), output.resolve(), texconv.resolve()
    if output_format not in DXGI:
        raise ValueError("DDS format must be rgba8 or bc3")
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("DDS variant must be outside the input skin directory")
    if output.exists():
        raise FileExistsError("Choose a new DDS skin output directory")
    if not source.is_dir():
        raise ValueError("Input skin directory does not exist")
    source_hashes = {str(path.relative_to(source)): sha256(path) for path in source.rglob("*") if path.is_file()}
    config, textures, extras, blk_text = _plan(source, roles or {})
    planned_hashes = {str(path.relative_to(source)): sha256(path) for path in source.rglob("*") if path.is_file()}
    if source_hashes != planned_hashes or any(
            item["input_sha256"] != source_hashes.get(str(item["relative"])) for item in textures):
        raise ValueError("Input skin changed while its conversion plan was being read")
    package_files = [Path(config["file"]), *(item["output"] for item in textures), *extras]
    if len({str(path).casefold() for path in package_files}) != len(package_files):
        raise ValueError("Generated DDS package filenames collide")
    archive = output.with_suffix(".zip")
    report_path = output.with_suffix(".dds.json")
    mips_archive = output.with_suffix(".mips.zip")
    outputs = [output / relative for relative in package_files] + [archive, report_path, mips_archive]
    inputs = [source, *(path for path in source.rglob("*") if path.is_file())] + ([texconv] if texconv.exists() else [])
    with ArtifactTransaction(outputs, inputs, label="dds-variant",
                             failure_directory=output.parent / ".artifact-failures") as transaction:
        staged_report = transaction.stage(report_path)
        tool = validate_tool(texconv)
        with tempfile.TemporaryDirectory(prefix="dds-work-", dir=staged_report.parent) as working:
            work = Path(working)
            package = work / "skin"
            package.mkdir()
            records = []
            with zipfile.ZipFile(transaction.stage(mips_archive), "w", zipfile.ZIP_DEFLATED) as mip_zip:
                for item in textures:
                    destination = package / item["output"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    # Explicitly generate the chain, including 1-pixel-wide tails.
                    # This avoids texconv's rectangular BOX-tail behavior and its
                    # deferred color conversion when generating compressed mips.
                    baseline = work / "baseline" / item["output"]
                    baseline.parent.mkdir(parents=True, exist_ok=True)
                    reference = reference_mips(item["pixels"], item["semantic"])
                    write_rgba8_mips(baseline, reference, item["semantic"])
                    fmt = FORMAT_NAMES[DXGI["rgba8"][item["semantic"]]]
                    command = [str(texconv), "-nologo", "-dx10", "-m", "0", "-if", "BOX",
                               "-nowic", "-sepalpha", "-f", fmt, "-o", str(destination.parent)]
                    baseline_header, baseline_mips = decode_mips(baseline)
                    if baseline_header["dxgi"] != DXGI["rgba8"][item["semantic"]]:
                        raise ValueError("Baseline DDS has unexpected color-space metadata")
                    if not np.array_equal(baseline_mips[0], item["pixels"]):
                        raise ValueError("Uncompressed baseline changed top-level RGBA pixels")
                    if output_format == "bc3":
                        command[command.index("-f") + 1] = FORMAT_NAMES[DXGI["bc3"][item["semantic"]]]
                        if item["semantic"] == "data":
                            command.extend(["-bc", "u"])
                    command.append(str(baseline))
                    invocations = [_run(command)]
                    if not destination.is_file():
                        raise ValueError("texconv returned success without its expected DDS output")
                    header, decoded = decode_mips(destination)
                    original = item["pixels"]
                    if header["dxgi"] != DXGI[output_format][item["semantic"]] or decoded[0].shape != original.shape:
                        raise ValueError("DDS format or original atlas dimensions changed")
                    top_delta = np.abs(decoded[0].astype(np.int16) - original.astype(np.int16))
                    if output_format == "rgba8" and np.any(top_delta):
                        raise ValueError("RGBA8 top-level conversion changed source pixels")
                    mip_records = []
                    for level, (pixels, expected) in enumerate(zip(decoded, reference)):
                        if not np.any(original[:, :, 3]) and np.any(pixels[:, :, 3]):
                            raise ValueError("All-zero source alpha was changed")
                        stream = BytesIO()
                        Image.fromarray(pixels).save(stream, format="PNG")
                        png = stream.getvalue()
                        member = item["output"].with_suffix("").as_posix() + f"/mip-{level:02d}.png"
                        mip_zip.writestr(member, png)
                        delta = np.abs(pixels.astype(np.int16) - expected.astype(np.int16))
                        if output_format == "rgba8" and np.any(delta):
                            raise ValueError("texconv changed an existing semantic mip")
                        mip_records.append({"level": level, "width": pixels.shape[1], "height": pixels.shape[0],
                            "decoded_rgba_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                            "decoded_png": member, "png_sha256": hashlib.sha256(png).hexdigest(),
                            "channel_min": pixels.min(axis=(0, 1)).tolist(),
                            "channel_max": pixels.max(axis=(0, 1)).tolist(),
                            "mae_vs_uncompressed_semantic_mip": delta.mean(axis=(0, 1)).tolist(),
                            "max_abs_vs_uncompressed_semantic_mip": delta.max(axis=(0, 1)).tolist()})
                    records.append({"source": item["relative"].as_posix(), "target": item["output"].as_posix(),
                        "semantic": item["semantic"], "input_sha256": item["input_sha256"],
                        "dds_sha256": sha256(destination), "bytes": destination.stat().st_size,
                        "header": header, "commands": invocations,
                        "baseline_all_mips_decoded": baseline_header["all_mips_decoded"],
                        "baseline_top_rgba_exact": True,
                        "top_rgba_exact": not bool(np.any(top_delta)),
                        "top_ga_exact": not bool(np.any(top_delta[:, :, [1, 3]])),
                        "top_channel_mae": top_delta.mean(axis=(0, 1)).tolist(),
                        "top_channel_max_abs": top_delta.max(axis=(0, 1)).tolist(),
                        "mips": mip_records})
            (package / config["file"]).write_text(blk_text, encoding="utf-8")
            for relative in extras:
                (package / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, package / relative)
            inspected = inventory(package)
            errors = [issue for issue in inspected["issues"] if issue["level"] == "error"]
            if errors:
                raise ValueError("Converted DDS skin failed BLK validation: " + json.dumps(errors))
            current = {str(path.relative_to(source)): sha256(path) for path in source.rglob("*") if path.is_file()}
            if source_hashes != current:
                raise ValueError("Input skin changed during conversion")
            if any(sha256(source / item["relative"]) != item["input_sha256"] for item in textures):
                raise ValueError("A source texture changed after it was decoded")
            if sha256(texconv) != tool["sha256"]:
                raise ValueError("texconv changed during conversion")
            with zipfile.ZipFile(transaction.stage(archive), "w", zipfile.ZIP_DEFLATED) as zipped:
                for relative in sorted(package_files):
                    path = package / relative
                    shutil.copyfile(path, transaction.stage(output / relative))
                    zipped.write(path, (Path(output.name) / relative).as_posix())
            report = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                "status": "complete_offline", "input": str(source), "output": str(output),
                "zip": str(archive), "mips_zip": str(mips_archive), "report": str(report_path),
                "format": output_format, "experimental_compression": output_format == "bc3",
                "tool": tool, "source_files_unchanged": True, "textures": records,
                "input_file_hashes": source_hashes,
                "zip_sha256": sha256(transaction.stage(archive)),
                "mips_zip_sha256": sha256(transaction.stage(mips_archive)),
                "semantics": {"mip_generator": "explicit float-channel BOX, including 1D rectangular tails; texconv preserves existing mips",
                    "color_rgb": "sRGB decode -> linear BOX mip filtering -> sRGB encode",
                    "color_alpha": "independent linear numeric channel, no premultiplication",
                    "packed_data": "independent linear BOX per RGBA channel; no sRGB/premultiplication",
                    "packed_ga": "original numeric normal X/Y channels; no silent vector renormalization"},
                "limitations": ["Target-game shader and runtime mip/LOD selection remain unverified.",
                    "Packed G/A use a numeric baseline; this does not claim vector-normal-aware mip filtering.",
                    "BC3 is a lossy experiment and is never substituted for the TGA or RGBA8 baseline.",
                    "Mip differences are measured against the explicit uncompressed semantic chain; they are not aesthetic scores."]}
            _write_json(staged_report, report)
        transaction.commit()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", dest="input_directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--texconv", type=Path, required=True)
    parser.add_argument("--format", choices=["rgba8", "bc3"], default="rgba8")
    parser.add_argument("--role", action="append", default=[], metavar="FROM=color|data")
    arguments = parser.parse_args()
    try:
        roles = {}
        for value in arguments.role:
            name, semantic = value.rsplit("=", 1)
            if not name or name in roles or semantic not in {"color", "data"}:
                raise ValueError("Use unique exact from resources with --role FROM=color|data")
            roles[name] = semantic
        report = convert(arguments.input_directory, arguments.out, arguments.texconv, arguments.format, roles)
        print(json.dumps({"status": report["status"], "report": report["report"],
                          "zip": report["zip"], "mips_zip": report["mips_zip"]}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, struct.error, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
