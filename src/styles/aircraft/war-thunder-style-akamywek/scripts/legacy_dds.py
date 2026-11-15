"""Export/check the legacy BGRA8 single-level path validated on J-10C.

Requires Pillow and NumPy. Does not modify BLK, material textures or game files.
This is an explicitly selected compatibility path, not a global mip policy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import BinaryIO
import numpy as np
from PIL import Image
from artifact_io import ArtifactError, ArtifactTransaction

MAX_PIXELS = 8192 * 8192
PIXEL_FORMAT = (32, 65, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)


def read_source(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        if im.mode not in ('RGB', 'RGBA', 'P', 'L', 'LA'):
            raise ValueError(f'Expected an 8-bit source; got {im.mode}. Convert deliberately first.')
        if not 0 < im.width * im.height <= MAX_PIXELS:
            raise ValueError('Source must contain 1..67108864 pixels.')
        return np.array(im.convert('RGBA'))


def header(width: int, height: int) -> bytes:
    # Same header conventions as the case-verified texconv -dx9 -m 1 output.
    words = [124, 135183, height, width, width * 4, 1, 1]
    words += [0] * 11
    words += list(PIXEL_FORMAT)
    words += [4096, 0, 0, 0, 0]
    return b'DDS ' + struct.pack('<31I', *words)


def decode_review_image(stream: BinaryIO) -> Image.Image | None:
    """Use Pillow's native BGRA decoder for this exact export profile; rewind all other inputs."""
    stream.seek(0)
    prefix = stream.read(128)
    if len(prefix) == 128 and prefix.startswith(b'DDS '):
        height, width = struct.unpack_from('<2I', prefix, 12)
        if 0 < width * height <= MAX_PIXELS and prefix == header(width, height):
            stream.seek(0, 2)
            if stream.tell() == 128 + width * height * 4:
                stream.seek(128)
                image = Image.new('RGBA', (width, height))
                for y in range(0, height, 128):
                    rows = min(height - y, 128)
                    block = stream.read(rows * width * 4)
                    if len(block) != rows * width * 4:
                        raise ValueError('Legacy BGRA8 image changed during decoding')
                    tile = Image.frombytes('RGBA', (width, rows), block, 'raw', 'BGRA')
                    image.paste(tile, (0, y))
                return image
    stream.seek(0)
    return None


def check(path: Path, source: Path | None = None) -> dict:
    with path.open('rb') as f:
        prefix = f.read(128)
    if len(prefix) != 128 or prefix[:4] != b'DDS ':
        raise ValueError('Missing or truncated legacy DDS header.')
    h = struct.unpack('<31I', prefix[4:])
    height, width = h[2], h[3]
    if h[0] != 124 or h[18:26] != PIXEL_FORMAT:
        raise ValueError('Expected traditional BGRA8 masks, not DX10 or compressed DDS.')
    if not 0 < width * height <= MAX_PIXELS or not width or not height:
        raise ValueError('Unsupported DDS dimensions.')
    if h[4] != width * 4 or h[6] != 1 or h[26] != 4096 or any(h[27:30]):
        raise ValueError('Expected one 2D level with tightly packed BGRA8 pixels.')
    if path.stat().st_size != 128 + width * height * 4:
        raise ValueError('Unexpected payload length or extra mip levels.')
    if prefix != header(width, height):
        raise ValueError('Header differs from the specified legacy 2D BGRA8 export profile.')
    if source is not None:
        expected = read_source(source)
        if expected.shape != (height, width, 4):
            raise ValueError('Source and DDS dimensions differ.')
        with path.open('rb') as f:
            f.seek(128)
            for y in range(0, height, 128):
                rows = min(128, height - y)
                data = f.read(rows * width * 4)
                actual = np.frombuffer(data, np.uint8).reshape(rows, width, 4)
                for channel, encoded in enumerate((2, 1, 0, 3)):
                    if not np.array_equal(expected[y:y+rows, :, channel], actual[:, :, encoded]):
                        raise ValueError(f'RGBA mismatch at rows {y}..{y+rows-1}, channel {channel}.')
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            digest.update(chunk)
    return dict(width=width, height=height, format='legacy BGRA8', mip_levels=1,
                source_rgba_exact=source is not None, sha256=digest.hexdigest())


def export(source: Path, output: Path) -> dict:
    if source.resolve() == output.resolve():
        raise ValueError('Input and output must differ.')
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    rgba = read_source(source)
    height, width = rgba.shape[:2]
    with ArtifactTransaction([output], inputs=[source], label='legacy-dds') as tx:
        staged = tx.stage(output)
        with staged.open('xb') as f:
            f.write(header(width, height))
            for y in range(0, height, 128):
                f.write(rgba[y:y+128, :, [2, 1, 0, 3]].tobytes())
        del rgba
        result = check(staged, source)
        tx.commit()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('export'); p.add_argument('--input', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('check'); p.add_argument('--dds', type=Path, required=True); p.add_argument('--source', type=Path)
    args = parser.parse_args()
    try:
        result = export(args.input, args.out) if args.command == 'export' else check(args.dds, args.source)
    except (OSError, ValueError, ArtifactError) as exc:
        parser.exit(2, f'error: {exc}\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
