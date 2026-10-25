"""Inspect bundled transparent assets and estimate this batch's image payload."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 18_000_000


def catalog() -> list[dict]:
    data = json.loads((ROOT / "assets/catalog.json").read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("Unsupported asset catalog")
    return data["items"]


def asset_path(relative: str) -> Path:
    path = ROOT / relative
    if not path.resolve().is_relative_to((ROOT / "assets").resolve()):
        raise ValueError(f"Asset outside package assets: {relative}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or linked asset: {relative}")
    return path


def check() -> dict:
    failures, count, ids = [], 0, set()
    for item in catalog():
        if not isinstance(item.get("id"), str) or item["id"] in ids:
            failures.append(f"Invalid/duplicate ID: {item.get('id')}")
        ids.add(item.get("id"))
        for key in ("png", "svg"):
            entry = item.get(key)
            if not entry:
                continue
            try:
                path = asset_path(entry["path"])
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    raise ValueError("SHA-256 mismatch")
                if len(raw) != entry["bytes"]:
                    raise ValueError("Byte count mismatch")
                if key == "png":
                    with Image.open(path) as image:
                        image.load()
                        if image.mode != "RGBA":
                            raise ValueError("PNG is not RGBA")
                        alpha = image.getchannel("A")
                        if alpha.getextrema()[0] != 0 or alpha.getextrema()[1] == 0:
                            raise ValueError("PNG needs both transparent background and visible ink")
                        if list(image.size) != entry["size"] or list(alpha.getbbox()) != entry["alpha_bbox"]:
                            raise ValueError("Dimensions or ink bounds mismatch")
                    count += 1
            except (ValueError, OSError, KeyError) as exc:
                failures.append(f"{item.get('id')} {key}: {exc}")
    return {"ok": not failures, "transparent_png_count": count, "failures": failures}


def sheet(out: Path) -> dict:
    items = catalog()
    columns, width, height = 4, 320, 220
    board = Image.new("RGB", (columns * width, math.ceil(len(items) / columns) * height), "#262b2e")
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=17)
    for index, item in enumerate(items):
        x, y = (index % columns) * width, (index // columns) * height
        tile = Image.new("RGBA", (width - 12, height - 42), "#62686a")
        td = ImageDraw.Draw(tile)
        for row in range(0, tile.height, 16):
            for col in range(0, tile.width, 16):
                if (row // 16 + col // 16) % 2:
                    td.rectangle((col, row, col + 15, row + 15), fill="#7c8284")
        with Image.open(asset_path(item["png"]["path"])) as source:
            # Contact-sheet crop only: original asset and alpha remain unchanged.
            preview = source.convert("RGBA").crop(source.getchannel("A").getbbox())
            preview.thumbnail((tile.width - 20, tile.height - 20), Image.Resampling.LANCZOS)
            tile.alpha_composite(preview, ((tile.width - preview.width) // 2, (tile.height - preview.height) // 2))
        board.paste(tile.convert("RGB"), (x + 6, y + 6))
        draw.text((x + 8, y + height - 28), item["id"], font=font, fill="white")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise FileExistsError(f"Refusing to replace {out}")
    board.save(out, format="JPEG", quality=83, optimize=True)
    return {"output": str(out.resolve()), "bytes": out.stat().st_size, "purpose": "checkerboard inspection preview only"}


def budget(paths: list[Path]) -> dict:
    items = []
    for path in paths:
        with Image.open(path) as image:
            image.verify()
        size = path.stat().st_size
        items.append({"file": str(path), "bytes": size, "base64_bytes": 4 * ((size + 2) // 3)})
    estimated = sum(item["base64_bytes"] for item in items) + 131_072
    return {"ok": estimated < LIMIT, "limit_bytes": LIMIT, "estimated_encoded_bytes": estimated,
            "assumed_overhead_bytes": 131_072, "files": items,
            "limitation": "This batch only; excludes existing conversation images, retries and unknown protocol overhead."}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    contact = sub.add_parser("sheet")
    contact.add_argument("--out", type=Path, required=True)
    transmission = sub.add_parser("budget")
    transmission.add_argument("images", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = {"items": [{"id": v["id"], "purpose": v["purpose"], "png": v["png"]["path"]} for v in catalog()]}
        elif args.command == "check":
            result = check()
        elif args.command == "sheet":
            result = sheet(args.out)
        else:
            result = budget(args.images)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 1
    except (ValueError, OSError, KeyError) as exc:
        print(f"asset_pack: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
