"""Validated readers for Dagor GRP2/3, DxP2 and VRFs/VRFx containers.

Format references: Gaijin's DagorEngine grpData.h/vromfs source and klensy's
wt-tools vromfs_parser.py. This module implements the readers independently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
import struct
import zlib

MAX_HEADER = 64 * 1024 * 1024
MAX_BODY = 512 * 1024 * 1024
MAX_ENTRIES = 1_000_000
CLASS_NAMES = {
    0xB4B7D9C4: "DynModel", 0x56F81B6D: "GeomNodeTree", 0x77F8232F: "RendInst",
    0xACE50000: "CollisionGeom", 0xA0000000: "AnimChar",
}


class FormatError(ValueError):
    pass


def bounds(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise FormatError(f"Range {offset}:{offset + size} exceeds {len(data)} bytes")
    return data[offset:offset + size]


def unpack(data: bytes, fmt: str, offset: int):
    return struct.unpack(fmt, bounds(data, offset, struct.calcsize(fmt)))


def cstring(data: bytes, offset: int) -> str:
    bounds(data, offset, 1)
    end = data.find(b"\0", offset, min(offset + 65536, len(data)))
    if end < 0:
        raise FormatError("Unterminated resource name")
    raw = data[offset:end]
    if raw == b"\xff?nm":
        return "nm"
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FormatError("Resource name is not UTF-8") from exc


def safe_target(root: Path, name: str) -> Path:
    portable = name.replace("\\", "/")
    parsed = PurePosixPath(portable)
    if (not portable or parsed.is_absolute() or PureWindowsPath(name).drive
            or any(p in {"..", ""} for p in parsed.parts)
            or any(":" in p for p in parsed.parts)):
        raise FormatError(f"Unsafe archive path {name!r}")
    candidate = (root / Path(*parsed.parts)).resolve()
    if root.resolve() not in candidate.parents:
        raise FormatError(f"Archive target escapes output: {name!r}")
    return candidate


@dataclass
class Entry:
    name: str
    offset: int
    size: int
    class_id: int | None = None
    resource_id: int | None = None
    dependencies: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def json(self):
        value = asdict(self)
        if self.class_id is not None:
            value["class_hex"] = f"0x{self.class_id:08x}"
            value["class_name"] = CLASS_NAMES.get(self.class_id, "Other")
        return value


class GrpArchive:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            first = stream.read(64)
            if first[:4] not in {b"GRP2", b"GRP3"}:
                raise FormatError("Expected GRP2 or GRP3")
            _, desc_size, stored_size = unpack(first, "<III", 4)
            if not 48 <= desc_size <= MAX_HEADER:
                raise FormatError("GRP descriptor size exceeds limit")
            if stored_size + 16 > self.size:
                raise FormatError("GRP resource payload is truncated")
            stream.seek(0)
            data = stream.read(desc_size + 16)
        self.magic = first[:4].decode("ascii")
        name_offset, name_count = unpack(data, "<II", 16)
        entry_offset, entry_count = unpack(data, "<II", 32)
        ref_offset, ref_count = unpack(data, "<II", 48)
        if name_count > MAX_ENTRIES or entry_count > name_count or ref_count > entry_count:
            raise FormatError("Invalid GRP entry counts")
        pointers = unpack(data, f"<{name_count}I", name_offset) if name_count else ()
        names = [cstring(data, pointer) for pointer in pointers]
        records = [unpack(data, "<IIHH", entry_offset + i * 12) for i in range(entry_count)]
        offsets = sorted({r[1] for r in records if r[1]}) + [min(self.size, stored_size + 16)]
        ends = dict(zip(offsets, offsets[1:]))
        self.entries: list[Entry] = []
        for i, (class_id, offset, resource_id, reserved) in enumerate(records):
            if offset and (offset < desc_size + 12 or offset > self.size):
                raise FormatError("GRP resource offset is outside its payload")
            if resource_id >= len(names):
                raise FormatError("GRP entry has an invalid resource name ID")
            entry = Entry(names[resource_id], offset, ends[offset] - offset if offset else 0,
                          class_id, resource_id, extra={"reserved": reserved})
            self.entries.append(entry)
        by_id = {e.resource_id: e for e in self.entries}
        for i in range(ref_count):
            if self.magic == "GRP2":
                class_id, res_id, reserved_id, offset, count, reserved = unpack(data, "<IHHIIQ", ref_offset + i * 24)
            else:
                class_id, res_id, count, offset = unpack(data, "<IHHQ", ref_offset + i * 16)
            if count > MAX_ENTRIES:
                raise FormatError("Too many GRP references")
            refs = unpack(data, f"<{count}H", offset) if count else ()
            if any(index >= len(names) and index != 0xFFFF for index in refs):
                raise FormatError("GRP dependency references an invalid name index")
            if res_id in by_id:
                by_id[res_id].dependencies = [names[index] for index in refs if index != 0xFFFF]
        self.metadata = {"magic": self.magic, "bytes": self.size, "names": name_count,
                         "entry_count": entry_count, "descriptor_bytes": desc_size}

    def read(self, entry: Entry) -> bytes:
        with self.path.open("rb") as stream:
            stream.seek(entry.offset)
            data = stream.read(entry.size)
        if len(data) != entry.size:
            raise FormatError("GRP changed or was truncated while reading")
        return data


class DxpArchive:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            first = stream.read(16)
            if first[:4] != b"DxP2":
                raise FormatError("Expected DxP2")
            version, count, header_size = unpack(first, "<III", 4)
            if version != 2 or count > MAX_ENTRIES or not 56 <= header_size <= MAX_HEADER:
                raise FormatError("Unsupported DxP2 version or invalid descriptor")
            data = stream.read(header_size)
        name_offset, name_count = unpack(data, "<II", 0)
        texture_offset, texture_count = unpack(data, "<II", 16)
        record_offset, record_count = unpack(data, "<II", 32)
        if name_count != count or texture_count != count or record_count != count:
            raise FormatError("DxP2 tables disagree on texture count")
        pointers = unpack(data, f"<{count}Q", name_offset) if count else ()
        names = [cstring(data, pointer) for pointer in pointers]
        self.entries = []
        for i, name in enumerate(names):
            header = bounds(data, texture_offset + i * 32, 32)
            label, fourcc, flags, height, width, levels, hq_levels, depth, bpp, quality, shift, mem_size, packed_size = struct.unpack("<4s4sIHHBBHHBBII", header)
            offset = unpack(data, "<I", record_offset + 12 + i * 24)[0]
            if packed_size and (offset + packed_size > self.size or offset < 16 + header_size):
                raise FormatError("DxP2 texture payload is truncated or overlaps metadata")
            self.entries.append(Entry(name, offset, packed_size, extra={
                "header_hex": header.hex(), "fourcc": fourcc.decode("ascii", errors="replace"),
                "width": width, "height": height, "mips": levels, "hq_mips": hq_levels,
                "compression": (flags >> 24) & 0xE0, "flags": flags,
                "uncompressed_bytes": mem_size, "depth": depth, "bits_per_pixel": bpp}))
        self.metadata = {"magic": "DxP2", "bytes": self.size, "entry_count": count,
                         "descriptor_bytes": header_size}

    def read(self, entry: Entry) -> bytes:
        with self.path.open("rb") as stream:
            stream.seek(entry.offset)
            payload = stream.read(entry.size)
        if len(payload) != entry.size:
            raise FormatError("DxP2 changed or was truncated while reading")
        return bytes.fromhex(entry.extra["header_hex"]) + payload


class VromfsArchive:
    def __init__(self, path: Path):
        self.path = path.resolve()
        raw = self.path.read_bytes()
        if raw[:4] not in {b"VRFs", b"VRFx"}:
            raise FormatError("Expected VRFs or VRFx")
        original_size, pack_flags = unpack(raw, "<II", 8)
        packed_size, compression_flags = pack_flags & 0x3FFFFFFF, pack_flags >> 30
        if original_size > MAX_BODY:
            raise FormatError("VROMFS exceeds the 512 MiB decoded limit")
        start, version, ext_flags = 16, None, 0
        if raw[:4] == b"VRFx":
            ext_size, ext_flags, version = unpack(raw, "<HHI", 16)
            if ext_size < 8:
                raise FormatError("Invalid VRFx extended header")
            bounds(raw, 16, ext_size)
            start += ext_size
        if packed_size:
            payload = bytearray(bounds(raw, start, packed_size))
            if pack_flags & 0x40000000:
                blocks = [(0, (0xAA55AA55, 0xF00FF00F, 0xAA55AA55, 0x12481248))] if packed_size >= 16 else []
                if packed_size >= 32:
                    blocks.append(((packed_size // 4) * 4 - 16,
                                   (0x12481248, 0xAA55AA55, 0xF00FF00F, 0xAA55AA55)))
                for offset, keys in blocks:
                    values = struct.unpack_from("<4I", payload, offset)
                    struct.pack_into("<4I", payload, offset, *(value ^ key for value, key in zip(values, keys)))
                try:
                    import zstandard
                except ImportError as exc:
                    raise FormatError("Zstandard is required: python -m pip install zstandard") from exc
                body = zstandard.ZstdDecompressor().decompress(payload, max_output_size=original_size)
            else:
                decoder = zlib.decompressobj()
                body = decoder.decompress(payload, original_size + 1)
                if len(body) > original_size or not decoder.eof:
                    raise FormatError("Invalid or oversized zlib VROMFS payload")
        else:
            body = bounds(raw, start, original_size)
        if len(body) != original_size:
            raise FormatError("VROMFS decoded size differs from its header")
        name_offset, count = unpack(body, "<II", 0)
        data_offset = unpack(body, "<I", 16)[0]
        if count > MAX_ENTRIES:
            raise FormatError("Too many VROMFS files")
        pointers = unpack(body, f"<{count}Q", name_offset) if count else ()
        self.entries = []
        for i, pointer in enumerate(pointers):
            name = cstring(body, pointer)
            offset, size, reserved = unpack(body, "<IIQ", data_offset + i * 16)
            bounds(body, offset, size)
            self.entries.append(Entry(name, offset, size, extra={"reserved": reserved}))
        self.body = body
        self.metadata = {"magic": raw[:4].decode("ascii"), "bytes": len(raw), "version_raw": version,
                         "extended_flags": ext_flags, "compression_flags": compression_flags,
                         "decoded_bytes": len(body), "entry_count": count}

    def read(self, entry: Entry) -> bytes:
        return bounds(self.body, entry.offset, entry.size)


def read_archive(path: Path):
    with path.open("rb") as stream:
        magic = stream.read(4)
    archive_type = {b"GRP2": GrpArchive, b"GRP3": GrpArchive, b"DxP2": DxpArchive,
                    b"VRFs": VromfsArchive, b"VRFx": VromfsArchive}.get(magic)
    if archive_type is None:
        raise FormatError(f"Unsupported archive signature: {magic!r}")
    return archive_type(path)
