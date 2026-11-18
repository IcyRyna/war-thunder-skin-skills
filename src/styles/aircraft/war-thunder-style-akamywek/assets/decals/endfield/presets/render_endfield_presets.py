"""Generate high-resolution transparent Arknights: Endfield industrial decal presets using bundled Skill fonts."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE.parents[2] / "fonts"

WHITE = (236, 236, 236, 255)
YELLOW = (234, 184, 24, 255)
STEEL = (178, 184, 192, 235)
MAGENTA = (255, 36, 160, 255)
MINT = (0, 229, 155, 255)
CHARCOAL_INK = (34, 35, 38, 255)


def font_main(size: int, variation: str = "Bold") -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / "Orbitron-VF.ttf"), size)
    font.set_variation_by_name(variation)
    return font


def font_sub(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / "Michroma-Regular.ttf"), size)


def draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    tracking: float = 0.08,
    anchor_x: str = "left",
):
    x, y = xy
    adv = [font.getlength(ch) for ch in text]
    step = font.size * tracking
    total = sum(adv) + step * max(0, len(text) - 1)
    if anchor_x == "center":
        x -= total * 0.5
    elif anchor_x == "right":
        x -= total
    cur = x
    for ch, w in zip(text, adv):
        draw.text((cur, y), ch, font=font, fill=fill)
        cur += w + step


def apply_diagonal_hatch(alpha_img: Image.Image, pitch: int = 14, stripe: int = 5) -> np.ndarray:
    alpha = np.asarray(alpha_img)
    yy, xx = np.ogrid[: alpha.shape[0], : alpha.shape[1]]
    mask = ((xx + yy) % pitch) < stripe
    out = alpha.astype(np.float32) * np.where(mask, 0.34, 0.09)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def make_talos_wiki_bar(title: str = "ENDFIELD INDUSTRIES", watermark: str = "TALOS-II") -> Image.Image:
    w, h = 1600, 320
    # 1. Subtle hatched large background wordmark
    wm_mask = Image.new("L", (w, h), 0)
    wmd = ImageDraw.Draw(wm_mask)
    draw_tracked(wmd, (84, 8), watermark, font_main(122, "Black"), 255, tracking=0.06)
    wm_alpha = apply_diagonal_hatch(wm_mask, pitch=14, stripe=5)
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    canvas[..., 0], canvas[..., 1], canvas[..., 2] = 220, 224, 230
    canvas[..., 3] = wm_alpha
    im = Image.fromarray(canvas, "RGBA")
    d = ImageDraw.Draw(im)

    # 2. Small sub-tag over bracketed title (Endfield UI Rule #3)
    d.polygon([(38, 62), (58, 62), (48, 80)], fill=YELLOW)
    draw_tracked(d, (68, 57), "// ARKNIGHTS: ENDFIELD", font_sub(25), WHITE, tracking=0.14)

    # Brackets + main title
    d.line([(40, 122), (24, 122), (24, 214), (40, 214)], fill=STEEL, width=5)
    d.line([(972, 122), (988, 122), (988, 214), (972, 214)], fill=STEEL, width=5)
    draw_tracked(d, (46, 134), title, font_main(62, "Bold"), WHITE, tracking=0.06)

    # 3. Bottom telemetry strip (Yellow + Magenta + Mint + hatched tail)
    y0, y1 = 244, 272
    d.rectangle([22, y0, 1020, y1], fill=YELLOW)
    d.rectangle([1020, y0, 1180, y1], fill=MAGENTA)
    d.rectangle([1180, y0, 1340, y1], fill=MINT)
    # Hatched tail block
    tail_m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(tail_m).rectangle([1340, y0, 1480, y1], fill=255)
    yy, xx = np.ogrid[:h, :w]
    tail_a = np.where((np.asarray(tail_m) > 0) & (((xx + yy) % 12) < 5), 185, 0).astype(np.uint8)
    tail_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    tail_rgba[..., :3] = 210
    tail_rgba[..., 3] = tail_a
    im = Image.alpha_composite(im, Image.fromarray(tail_rgba, "RGBA"))
    d = ImageDraw.Draw(im)

    # Right corner bracket + solid square marker
    d.line([(1518, 42), (1564, 42), (1564, 88)], fill=WHITE, width=7)
    d.rectangle([1534, 244, 1564, 274], fill=WHITE)
    return im


def make_protocol_reclamation(subline: str = "CONFORMAL // SECTOR-04") -> Image.Image:
    # Render at 2x scale then downsample for crisp anti-aliased polygons without opaque black box backing
    w, h = 2560, 620
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # Transparent-gap yellow hazard slashes (no solid black rectangle behind them!)
    for i in range(6):
        x = 56 + i * 90
        d.polygon([(x + 36, 36), (x + 92, 36), (x + 42, 206), (x - 14, 206)], fill=YELLOW)

    draw_tracked(d, (650, 34), "PROTOCOL // RECLAMATION", font_main(84, "Bold"), YELLOW, tracking=0.06)
    draw_tracked(d, (654, 148), "TALOS-II  FRONTIER  AIC", font_sub(48), WHITE, tracking=0.14)

    d.rectangle([28, 256, 2480, 268], fill=YELLOW)
    d.rectangle([28, 304, 60, 368], fill=YELLOW)
    draw_tracked(d, (86, 306), subline, font_main(58, "Bold"), WHITE, tracking=0.10)

    bars_x = [40, 64, 96, 114, 146, 178, 198, 224, 256, 284, 304, 338, 360, 396, 418, 452]
    bars_w = [12, 18, 10, 20, 14, 10, 16, 12, 18, 10, 22, 12, 20, 10, 16, 14]
    for bx, bw in zip(bars_x, bars_w):
        d.rectangle([bx, 424, bx + bw, 554], fill=WHITE)

    draw_tracked(d, (510, 424), "AIC-LINK ACTIVE", font_main(58, "Bold"), YELLOW, tracking=0.10)
    draw_tracked(d, (512, 502), "ENDFIELD INDUSTRIES", font_sub(36), STEEL, tracking=0.12)

    # Diamond core emblem on right (no occlusion risk if centered cleanly inside chart margin)
    cx, cy = 2380, 488
    d.polygon([(cx, cy - 76), (cx + 76, cy), (cx, cy + 76), (cx - 76, cy)], outline=YELLOW, width=12)
    d.polygon([(cx, cy - 42), (cx + 42, cy), (cx, cy + 42), (cx - 42, cy)], fill=WHITE)

    # Thin corner reticles
    for pts in [
        [(16, 72), (16, 16), (72, 16)],
        [(w - 72, 16), (w - 16, 16), (w - 16, 72)],
        [(16, h - 72), (16, h - 16), (72, h - 16)],
        [(w - 72, h - 16), (w - 16, h - 16), (w - 16, h - 72)],
    ]:
        d.line(pts, fill=STEEL, width=7)
    return im.resize((1280, 310), Image.LANCZOS)


def make_aic_dijiang(subline: str = "ORBITAL TRANSFER // TALOS-II") -> Image.Image:
    w, h = 2480, 600
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    d.rectangle([32, 36, 64, h - 36], fill=YELLOW)
    cx, cy = 248, 232
    d.polygon([(cx, cy - 136), (cx + 136, cy), (cx, cy + 136), (cx - 136, cy)], outline=WHITE, width=14)
    d.polygon([(cx, cy - 80), (cx + 80, cy), (cx, cy + 80), (cx - 80, cy)], fill=YELLOW)
    d.rectangle([112, 432, 384, 522], fill=WHITE)
    draw_tracked(d, (248, 452), "DIJIANG", font_main(44, "Bold"), CHARCOAL_INK, tracking=0.06, anchor_x="center")

    draw_tracked(d, (460, 56), "AIC // ENDFIELD", font_main(98, "Bold"), WHITE, tracking=0.08)
    draw_tracked(d, (464, 198), "AUTOMATED INDUSTRY COMPLEX", font_sub(48), YELLOW, tracking=0.10)
    d.line([(460, 312), (2412, 312)], fill=STEEL, width=6)
    draw_tracked(d, (460, 356), subline, font_main(52, "Bold"), WHITE, tracking=0.10)
    draw_tracked(d, (462, 454), "PROTOCOL CORE 01-A", font_sub(38), STEEL, tracking=0.10)

    for i in range(11):
        x = 1720 + i * 64
        d.rectangle([x, 444, x + 36, 532], fill=YELLOW if i % 2 == 0 else WHITE)
    for pts in [
        [(16, 72), (16, 16), (72, 16)],
        [(w - 72, 16), (w - 16, 16), (w - 16, 72)],
        [(16, h - 72), (16, h - 16), (72, h - 16)],
        [(w - 72, h - 16), (w - 16, h - 16), (w - 16, h - 72)],
    ]:
        d.line(pts, fill=STEEL, width=7)
    return im.resize((1240, 300), Image.LANCZOS)


def make_caution_no_step(tag: str = "NO STEP") -> Image.Image:
    w, h = 2240, 340
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Transparent-gap diagonal warning bars
    for i in range(21):
        x = 24 + i * 108
        x0, x1 = max(24, x), min(w - 24, x + 60)
        if x1 > x0:
            d.polygon([(x + 30, 24), (x + 88, 24), (x + 38, 148), (x - 20, 148)], fill=YELLOW)
    # Clip cleanly on left & right margins
    arr = np.asarray(im).copy()
    arr[:, :24, 3] = 0
    arr[:, -24:, 3] = 0
    im = Image.fromarray(arr, "RGBA")
    d = ImageDraw.Draw(im)
    draw_tracked(d, (32, 214), f"CAUTION // ORIGINIUM PROTOCOL // {tag}", font_main(52, "Bold"), WHITE, tracking=0.08)
    d.rectangle([w - 116, 214, w - 32, 290], fill=YELLOW)
    return im.resize((1120, 170), Image.LANCZOS)


def make_originium_seal() -> Image.Image:
    w = 960
    im = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = w // 2
    d.polygon([(c, 44), (w - 44, c), (c, w - 44), (44, c)], outline=YELLOW, width=20)
    d.polygon([(c, 128), (w - 128, c), (c, w - 128), (128, c)], outline=WHITE, width=8)
    d.polygon([(c, 216), (c + 156, c), (c, w - 216), (c - 156, c)], fill=YELLOW)
    # Clear transparent center diamond + transparent horizontal label slot across middle
    arr = np.asarray(im).copy()
    yy, xx = np.mgrid[:w, :w]
    inner_diamond = (np.abs(xx - c) / 92.0 + np.abs(yy - c) / 160.0) <= 1.0
    label_slot = (np.abs(yy - c) <= 52) & (np.abs(xx - c) <= 230)
    arr[inner_diamond | label_slot, :] = 0
    im = Image.fromarray(arr, "RGBA")
    d = ImageDraw.Draw(im)
    draw_tracked(d, (c, c - 26), "TALOS-II", font_main(50, "Bold"), WHITE, tracking=0.14, anchor_x="center")
    for pts in [
        [(96, 192), (96, 96), (192, 96)],
        [(w - 192, 96), (w - 96, 96), (w - 96, 192)],
        [(96, w - 192), (96, w - 96), (192, w - 96)],
        [(w - 192, w - 96), (w - 96, w - 96), (w - 96, w - 192)],
    ]:
        d.line(pts, fill=WHITE, width=10)
    return im.resize((720, 720), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=HERE)
    ap.add_argument("--title", default="ENDFIELD INDUSTRIES")
    ap.add_argument("--subline", default="CONFORMAL // SECTOR-04")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    make_talos_wiki_bar(title=args.title).save(args.out / "talos_wiki_bar_dark.png")
    make_protocol_reclamation(subline=args.subline).save(args.out / "protocol_reclamation.png")
    make_aic_dijiang().save(args.out / "aic_dijiang.png")
    make_caution_no_step().save(args.out / "caution_no_step.png")
    make_originium_seal().save(args.out / "originium_seal.png")
    print("Generated Endfield presets in", args.out)


if __name__ == "__main__":
    main()
