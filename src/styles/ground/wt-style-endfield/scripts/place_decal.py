"""Place an intact transparent PNG by its visible-ink bounds; no UV mapping."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image
from texture_semantics import resize_texture

MAX_PIXELS = 67_108_864


def place(asset: Path, canvas: tuple[int, int], ink_width: float, x: int, y: int,
          out: Path, allow_clipping: bool = False) -> dict:
    if any(type(v) is not int or v < 1 for v in canvas) or canvas[0] * canvas[1] > MAX_PIXELS:
        raise ValueError("Canvas must have positive dimensions and at most 67,108,864 pixels")
    if not math.isfinite(ink_width) or ink_width <= 0:
        raise ValueError("Ink width must be positive and finite")
    receipt_path = out.with_suffix(out.suffix + ".json")
    if out.resolve() == asset.resolve() or out.exists() or receipt_path.exists():
        raise FileExistsError("Output/receipt exists or would overwrite the source")
    with Image.open(asset) as source:
        source.load()
        if source.mode != "RGBA":
            raise ValueError("Source must be an RGBA PNG")
        if source.format != "PNG":
            raise ValueError("Source must be PNG")
        bounds = source.getchannel("A").getbbox()
        if bounds is None or source.getchannel("A").getextrema()[0] != 0:
            raise ValueError("Source needs visible ink and a transparent background")
        scale = ink_width / (bounds[2] - bounds[0])
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        if size[0] * size[1] > MAX_PIXELS:
            raise ValueError("Scaled asset exceeds the pixel limit")
        resized = resize_texture(source, size, "opacity", "srgb", Image.Resampling.LANCZOS)
        scaled_bounds = resized.getchannel("A").getbbox()
        if scaled_bounds is None:
            raise ValueError("Ink disappeared at target scale; choose a larger size")
        px, py = x - scaled_bounds[0], y - scaled_bounds[1]
        visible = (x, y, px + scaled_bounds[2], py + scaled_bounds[3])
        clipped = visible[0] < 0 or visible[1] < 0 or visible[2] > canvas[0] or visible[3] > canvas[1]
        if clipped and not allow_clipping:
            raise ValueError("Visible ink would be clipped; adjust placement or explicitly allow clipping")
        result = Image.new("RGBA", canvas, (0, 0, 0, 0))
        result.alpha_composite(resized, (px, py))
        data = {"source_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "source_size": list(source.size), "source_alpha_bbox": list(bounds),
                "requested_uniform_scale": scale, "rasterized_size": list(size),
                "raster_scale_xy": [size[0] / source.width, size[1] / source.height],
                "translation_xy": [px, py], "visible_output_bounds": list(visible),
                "canvas": list(canvas), "clipped": clipped, "upscaled": scale > 1,
                "alpha_semantics": "opacity", "color_space": "srgb",
                "warning": "Upscaling does not recover source detail; use a vector master for larger markings." if scale > 1 else None,
                "uv_or_3d_verified": False}
    out.parent.mkdir(parents=True, exist_ok=True)
    # Save losslessly and exclusively; do not silently replace existing work.
    with out.open("xb") as stream:
        result.save(stream, format="PNG", optimize=True)
    data["output_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return data


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--canvas", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"), required=True)
    parser.add_argument("--ink-width", type=float, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-clipping", action="store_true")
    args = parser.parse_args()
    try:
        result = place(args.asset, tuple(args.canvas), args.ink_width, args.x, args.y, args.out, args.allow_clipping)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"place_decal: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
