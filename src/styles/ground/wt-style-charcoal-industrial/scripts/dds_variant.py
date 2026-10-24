"""DDS codec and pinned DirectXTex verification reused from aircraft dds_variant.

Extracted unchanged core algorithms from the approved local shared aircraft tool;
plan/inventory/aircraft CLI intentionally excluded. Ground semantics and mip
filtering belong to ground_dds and texture_semantics. The supported atlas bound
is 16384x16384; channels remain bytes throughout DDS encode/decode.
Source SHA-256: 6ffe49b8b1e29ac8b92e93a70b6357a59e22ca52caccfc77e36339b17a83bd03
"""
from __future__ import annotations
import hashlib
from io import BytesIO
from pathlib import Path
import struct
import subprocess
import json
import numpy as np
from PIL import Image

TEXCONV_RELEASE = "may2026"
TEXCONV_VERSION = "texconv version 2026.5.8.1"
TEXCONV_SHA256 = "dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06"
TEXCONV_URL = "https://github.com/microsoft/DirectXTex/releases/download/may2026/texconv.exe"
MAX_PIXELS = 16384 * 16384
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
    if (type(width) is not int or type(height) is not int or width < 1 or height < 1
            or max(width, height) > 16384 or width * height > MAX_PIXELS):
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

