"""DDSx 2D BC top mip to DDS. Correct legacy archive metadata's swapped axes."""
import struct


def top_mip(data, meta):
    # The existing index labels raw DDSx w,h as height,width; freeze that API and
    # correct it at this candidate boundary (same correction as native 99A evidence).
    width, height = meta["height"], meta["width"]
    if min(width, height) < 1 or max(width, height) > 16384:
        raise ValueError("Invalid DDSx preview dimensions")
    if meta.get("depth", 0) > 1 or meta["flags"] & (0x800 | 0x1000 | 0x200000 | 0x20000):
        raise ValueError("Unsupported DDSx volume/array/cube/paired-base texture")
    block = {"DXT1": 8, "DXT3": 16, "DXT5": 16, "BC7 ": 16}.get(meta["fourcc"])
    if block is None:
        raise ValueError("Unsupported DDSx format " + meta["fourcc"])
    size = lambda level: max(1, (max(1, width >> level) + 3) // 4) * max(1, (max(1, height >> level) + 3) // 4) * block
    top = size(0)
    if meta["flags"] & 0x4000:
        if len(data) != top + 12:
            raise ValueError("Unexpected Kaiser DDSx payload length")
        pixels = data[:top]
    else:
        if not 1 <= meta["mips"] <= 16 or len(data) != sum(size(i) for i in range(meta["mips"])):
            raise ValueError("DDSx payload disagrees with declared mip chain")
        pixels = data[-top:] if meta["flags"] & 0x40000 else data[:top]
    header = [0] * 31
    header[0], header[1], header[2], header[3], header[4], header[6] = 124, 0x81007, height, width, top, 1
    header[18], header[19], header[26] = 32, 4, 0x1000
    dx10 = meta["fourcc"] == "BC7 "
    header[20] = int.from_bytes(b"DX10" if dx10 else meta["fourcc"].encode("ascii"), "little")
    extra = struct.pack("<5I", 98, 3, 0, 1, 0) if dx10 else b""
    return b"DDS " + struct.pack("<31I", *header) + extra + pixels, {"dimensions": [width, height], "mips": 1, "axis_correction": "legacy index metadata swapped at candidate boundary"}
