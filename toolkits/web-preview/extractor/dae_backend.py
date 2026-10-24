"""Headless adapter for the pinned Dagor Asset Explorer model decoder.

GRP/DXP index reading uses our validated readers, not DAE's older container
reader. Its vertex, shader mesh and skeleton decoders remain upstream code.
"""
from __future__ import annotations

import importlib
import lzma
import os
from pathlib import Path
import sys
import types

from archives import FormatError, GrpArchive, MAX_BODY

PINNED_DAE = "1f0d1e04ded04bf9b28e8d5be93cb79714f505d3"
VENDOR = Path(__file__).parent / "vendor/dagor-asset-explorer"
_dll_paths = []


def decompress_lzma(data: bytes) -> bytes:
    if len(data) < 5:
        raise FormatError("LZMA properties are truncated")
    # pylzma uses five LZMA1 properties followed immediately by the stream.
    # FORMAT_ALONE uses the same properties plus an eight-byte size field.
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE, memlimit=MAX_BODY)
    result = decoder.decompress(data[:5] + b"\xff" * 8 + data[5:], max_length=MAX_BODY + 1)
    if len(result) > MAX_BODY or not decoder.needs_input and not decoder.eof:
        raise FormatError("LZMA output exceeds 512 MiB")
    return result


def compress_lzma(data: bytes) -> bytes:
    encoded = lzma.compress(data, format=lzma.FORMAT_ALONE)
    return encoded[:5] + encoded[13:]


def backend():
    if os.name != "nt":
        raise FormatError("The bundled DAE native decoder currently requires Windows x64")
    if not (VENDOR / "src/dae/parse/realres.py").is_file():
        raise FormatError("Pinned Dagor Asset Explorer checkout is missing; run setup.ps1")
    compatibility = types.ModuleType("pylzma")
    compatibility.decompress = decompress_lzma
    compatibility.compress = compress_lzma
    sys.modules.setdefault("pylzma", compatibility)
    sys.path.insert(0, str(VENDOR / "src/dae"))
    _dll_paths.append(os.add_dll_directory(str(VENDOR / "lib")))
    try:
        realres = importlib.import_module("parse.realres")
        material = importlib.import_module("parse.material")
        gameres = importlib.import_module("parse.gameres")
        cacher = importlib.import_module("util.assetcacher").AssetCacher
    except (ImportError, OSError) as exc:
        raise FormatError(f"DAE dependency could not load: {exc}; run setup.ps1") from exc
    if not getattr(material, "_skin_unique_names", False):
        original_names = material.computeMaterialNames

        def unique_names(materials, parent=None):
            original_names(materials, parent)
            seen = set()
            for index, item in enumerate(materials or []):
                name = item.getName()
                if not name or name in seen:
                    base = name or item.cls or "material"
                    candidate = f"{base}_{index:03d}"
                    while candidate in seen:
                        candidate += "_copy"
                    item.setName(candidate)
                seen.add(item.getName())

        material.computeMaterialNames = unique_names
        realres.computeMaterialNames = unique_names
        gameres.computeMaterialNames = unique_names
        material._skin_unique_names = True
    return types.SimpleNamespace(realres=realres, material=material, gameres=gameres, cacher=cacher)


def load_model(pack: Path, name: str, lod: int, descriptors: list[Path]):
    runtime = backend()
    runtime.cacher.clearCache()
    for path in descriptors:
        if path.is_file():
            desc = runtime.gameres.GameResDesc(str(path))
            desc.loadDataBlock()
            runtime.cacher.appendGameResDesc(desc)
    archive = GrpArchive(pack)
    objects = {}
    for entry in archive.entries:
        if entry.name not in {name, name + "_skeleton"}:
            continue
        cls = runtime.realres.REALRES_CLASSES_DICT.get(entry.class_id)
        if cls is None:
            raise FormatError(f"Unsupported resource class {entry.class_id:#x}")
        resource = cls(str(pack), name=entry.name, size=entry.size, offset=entry.offset)
        runtime.cacher.cacheAsset(resource)
        objects[entry.name] = resource
    if name not in objects:
        raise FormatError(f"Model {name!r} is not present in {pack}")
    model = objects[name].getModel(lod)
    if model.vertCnt == 0 or model.getFaceCount() == 0:
        raise FormatError("Decoder returned an empty model")
    return model, runtime
