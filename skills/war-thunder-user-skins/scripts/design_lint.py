"""Check a vector_paint design for the habitual taste mistakes before anything is painted.

Models drift to the same defaults: stock or decorative fonts, missing CJK glyphs,
filler English, text sizes that are almost but not quite the same, pure black and
white, neon primaries, several saturated hues, hue-shifting gradients, equal-width
lines, floating outline frames, glow made of stacked strokes, too many line angles
and repeated character art.  This reads the design JSON only (no geometry) and lists
each hit with the item, the reason and the fix; see references/taste-corrections.md.

It is a gate for known mistakes, not an art score: a clean report does not mean the
design is good, and a deliberate exception is fine when the design notes say why.
Exit status is 1 when an error is found (or any warning with --strict).
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

# Same default as vector_paint.py; WT_SKIN_FONT overrides it on both.
DEFAULT_FONT = os.environ.get('WT_SKIN_FONT', 'C:/Windows/Fonts/bahnschrift.ttf')
# Stock UI faces, script and novelty faces, and thin serif CJK faces that vanish at viewing distance.
DISCOURAGED_FONTS = {
    'arial': 'stock UI face', 'arialbd': 'stock UI face', 'arialbi': 'stock UI face', 'ariali': 'stock UI face',
    'times': 'serif body face', 'timesbd': 'serif body face', 'georgia': 'serif body face',
    'calibri': 'stock UI face', 'calibrib': 'stock UI face', 'segoeui': 'stock UI face', 'segoeuib': 'stock UI face',
    'verdana': 'stock UI face', 'tahoma': 'stock UI face', 'comic': 'novelty face', 'comicbd': 'novelty face',
    'impact': 'condensed poster face, reads as a meme', 'papyrus': 'novelty face', 'segoepr': 'script face',
    'segoeprb': 'script face', 'segoesc': 'script face', 'segoescb': 'script face', 'simsun': 'thin serif CJK face',
    'simsunb': 'thin serif CJK face', 'simsunextg': 'thin serif CJK face', 'mingliub': 'thin serif CJK face',
    'dejavusans': 'library fallback face', 'dejavuserif': 'library fallback face',
}
FILLER = re.compile(r'\b(LOREM|IPSUM|SAMPLE|PLACEHOLDER|TEXT\s*HERE|YOUR\s+TEXT|TITLE|CYBER\w*|NEON|ULTIMATE|PREMIUM|'
                    r'AWESOME|EPIC|LEGEND(ARY)?|SYSTEM\s+ONLINE|WARNING\s+ZONE|ULTRA)\b', re.I)
CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]')
LIGHT = re.compile(r'thin|light|hairline|extralight|semilight', re.I)
LIGHT_FILES = {'msyhl', 'dengl', 'segoeuil', 'segoeuisl', 'yugothl', 'arialn'}
FAMILY_PREFIXES = ('msyh', 'deng', 'yugoth', 'meiryo', 'segoeui', 'arial', 'bahnschrift', 'simhei', 'simsun')


def hex_rgb(value, palette):
    if isinstance(value, str) and value in palette:
        value = palette[value]
    if not (isinstance(value, str) and len(value) == 7 and value[0] == '#'):
        raise ValueError(f'Colors must be #rrggbb or a palette name: {value}')
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def hsv(rgb):
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))


def vivid(rgb):
    _, s, v = hsv(rgb)
    return s > .5 and v > .45  # same thresholds as atlas_palette.py


def fill_colors(fill):
    if fill is None:
        return []
    if not isinstance(fill, dict):
        return [fill]
    if 'gradient' in fill:
        return list(fill['gradient']['colors'])
    return [fill['color']] if 'color' in fill else []


class Report:
    def __init__(self):
        self.hits = []

    def add(self, level, code, where, why, fix):
        self.hits.append(dict(level=level, code=code, where=where, why=why, fix=fix))


def hue_families(hues):
    """Group hues (degrees) whose circular gap is under 30 degrees."""
    if not hues:
        return []
    order = sorted(set(round(h) % 360 for h in hues))
    gaps = [((order[(i + 1) % len(order)] - order[i]) % 360 or 360, i) for i in range(len(order))]
    widest = max(gaps)[1] if len(order) > 1 else 0
    start = (widest + 1) % len(order)
    families, current = [], [order[start]]
    for k in range(1, len(order)):
        h = order[(start + k) % len(order)]
        if (h - current[-1]) % 360 < 30:
            current.append(h)
        else:
            families.append(current)
            current = [h]
    families.append(current)
    return families


def check_colors(design, palette, report):
    uses = []  # (where, rgb, kind)
    for name, value in palette.items():
        uses.append((f'palette.{name}', hex_rgb(value, palette), 'palette'))
    for layer in design.get('layers', []):
        for item in layer.get('items', []):
            for c in fill_colors(item.get('fill')):
                uses.append((item.get('id', layer.get('name')), hex_rgb(c, palette), 'fill'))
            gradient = item.get('fill', {}).get('gradient') if isinstance(item.get('fill'), dict) else None
            if gradient:
                (h0, s0, v0), (h1, s1, v1) = (hsv(hex_rgb(c, palette)) for c in gradient['colors'])
                shift = min(abs(h0 - h1), 1 - abs(h0 - h1)) * 360
                if s0 > .25 and s1 > .25 and shift > 25:
                    report.add('warn', 'hue-shift-gradient', item.get('id'), f'gradient turns {shift:.0f} degrees of hue',
                               'Keep one hue and change only value (10-20%) along the flow; blue-to-purple sunsets read as stock art.')
        for spec in layer.get('images', []):
            if 'text' in spec:
                uses.append((spec.get('id', layer.get('name')), hex_rgb(spec.get('color', '#ffffff'), palette), 'text'))
    by_rgb = {}
    for where, rgb, kind in uses:
        by_rgb.setdefault(rgb, []).append(where)
    for rgb, wheres in by_rgb.items():
        h, s, v = hsv(rgb)
        where = wheres[0] + (f' (+{len(wheres) - 1} more)' if len(wheres) > 1 else '')
        code = f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}'
        if max(rgb) <= 8:
            report.add('warn', 'pure-black', where, f'{code}: pure black has no depth and swallows panel lines',
                       'Use a near-neutral charcoal (#2b2b2c-#424347); the deepest channel colour is 8-12 below the base.')
        elif min(rgb) >= 247:
            report.add('warn', 'pure-white', where, f'{code}: pure white glares and looks unprinted',
                       'Use near-white #e7e7e7-#f4f4f4 (text without a color is #ffffff).')
        elif s >= .97 and v >= .97:
            report.add('warn', 'neon-primary', where, f'{code}: a screen primary, not a sampled colour',
                       'Sample the signature colour from the character art (sample_color radius 4-8 px) instead of naming a colour.')
    vivid_uses = {}
    for where, rgb, kind in uses:
        if kind != 'palette' and vivid(rgb):
            vivid_uses.setdefault(round(hsv(rgb)[0] * 360) % 360, set()).add(where)
    families = hue_families(list(vivid_uses))
    if len(families) > 1:
        detail = []
        for fam in families:
            items = sorted(set().union(*(vivid_uses[h] for h in fam)))
            detail.append(f'{fam[0]}-{fam[-1]} deg: {len(items)} items')
        level = 'error' if len(families) > 2 else 'warn'
        report.add(level, 'several-vivid-hues', 'design', f'{len(families)} saturated hue families in use ({"; ".join(detail)})',
                   'Keep one signature family; a second saturated hue only as a <=2% accent (check with atlas_palette.py), never as equal stripes.')
    return families


def glyph_missing(font, ch):
    """True when the font draws the same box for ch as for an unassigned private-use code point."""
    if ch.isspace():
        return False
    probe = font.getmask(ch)
    blank = font.getmask('\U0010fffd')
    return probe.size == blank.size and bytes(probe) == bytes(blank)


def check_text(design, palette, report):
    try:
        from PIL import ImageFont
    except ImportError:  # glyph checks need Pillow; the rest does not
        ImageFont = None
    texts = []
    for layer in design.get('layers', []):
        for spec in layer.get('images', []):
            if 'text' in spec:
                texts.append(spec)
    styles, families, heights = set(), set(), []
    fonts = {}
    for spec in texts:
        where, text = spec.get('id', '?'), spec['text']
        font_path = spec.get('font', DEFAULT_FONT)
        stem = Path(font_path).stem.lower()
        families.add(next((p for p in FAMILY_PREFIXES if stem.startswith(p)), stem))
        styles.add((stem, spec.get('variation')))
        height = float(spec.get('height', 0))
        heights.append((height, where))
        if stem in DISCOURAGED_FONTS:
            report.add('warn', 'stock-font', where, f'{Path(font_path).name}: {DISCOURAGED_FONTS[stem]}',
                       'Use one geometric or square sans for the whole airframe (Bahnschrift for Latin; Microsoft YaHei Bold, '
                       'DengXian Bold or SimHei for Chinese; Yu Gothic Bold or Meiryo Bold for Japanese).')
        if CJK.search(text) and 'font' not in spec:
            report.add('error', 'cjk-without-font', where, 'CJK text on the default Latin font',
                       'Give an explicit CJK font (C:/Windows/Fonts/msyhbd.ttc, Dengb.ttf, simhei.ttf, YuGothB.ttc).')
        if not Path(font_path).is_file():
            report.add('error', 'font-not-found', where, f'{font_path} does not exist, so vector_paint.py cannot render this text',
                       'Point font at an installed .ttf/.ttc (or set WT_SKIN_FONT for the default) and rerun.')
        elif ImageFont is not None:
            key = (font_path, spec.get('variation'))
            if key not in fonts:
                fonts[key] = ImageFont.truetype(font_path, 48)
                if spec.get('variation'):
                    try:
                        fonts[key].set_variation_by_name(spec['variation'])
                    except (OSError, ValueError):
                        pass
            missing = sorted({ch for ch in text if glyph_missing(fonts[key], ch)})
            if missing:
                report.add('error', 'missing-glyphs', where, f'{Path(font_path).name} has no glyph for {"".join(missing)!r}: it renders as boxes',
                           'Pick a font that covers every character and render it once to check.')
        if FILLER.search(text):
            report.add('warn', 'filler-text', where, f'{text!r} is filler, not information',
                       'Every line of type must name its source: character, work, faction, aircraft or a real technical marking.')
        latin = re.sub(r'[^A-Za-z]', '', text)
        if len(latin) >= 4 and latin.isupper() and float(spec.get('tracking', 0)) < .03:
            report.add('warn', 'caps-without-tracking', where, 'all-caps word set solid',
                       'Track capitals: +0.05-0.12 for names, +0.2-0.3 for small sub-lines.')
        if (LIGHT.search(str(spec.get('variation') or '')) or stem in LIGHT_FILES) and height < .08:
            report.add('warn', 'thin-small-type', where, f'light weight at {height:.2f} m cap height disappears in game',
                       'Small type uses Regular or Bold; keep Light for large sub-lines only.')
    if len(families) > 2:
        report.add('warn', 'too-many-fonts', 'design', f'{len(families)} font families: {sorted(families)}',
                   'One family for the airframe (plus one CJK face when needed), two weights.')
    if len(styles) > 3:
        report.add('warn', 'too-many-styles', 'design', f'{len(styles)} font/weight combinations',
                   'Two weights carry the hierarchy: Bold for names, Light or Regular for sub-lines.')
    # The size ladder is read within one surface: compare only placements on the same chart.
    per_chart = {}
    for (h, where), spec in zip(heights, texts):
        per_chart.setdefault(spec.get('chart'), []).append((h, where))
    for chart, entries in per_chart.items():
        tiers = []
        for h, where in sorted(entries):
            if tiers and h <= tiers[-1][0] * 1.04:
                tiers[-1][1].append(where)
            else:
                tiers.append((h, [where]))
        for (h0, w0), (h1, w1) in zip(tiers, tiers[1:]):
            if h1 / h0 < 1.5:
                report.add('warn', 'near-equal-sizes', f'{w0[0]} / {w1[0]} (chart {chart})',
                           f'cap heights {h0:.2f} m and {h1:.2f} m differ by only {h1 / h0:.2f}x',
                           'Make sizes either equal or clearly different: name : sub-line : note about 1 : 1/3 : 1/8 (adjacent tiers >= 2x).')
    if len(texts) > 16:
        report.add('warn', 'too-much-text', 'design', f'{len(texts)} text placements',
                   'Main name once per side and at most 5-6 lockups on the whole airframe; cluster technical text.')
    return [dict(id=s.get('id'), text=s['text'], font=Path(s.get('font', DEFAULT_FONT)).name,
                 variation=s.get('variation'), height=s.get('height')) for s in texts]


def direction_families(segments):
    """Length-weighted direction histogram (mod 180 deg) merged into 6-degree families."""
    bins = {}
    total = 0.
    for (x0, y0), (x1, y1) in segments:
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1e-6:
            continue
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180
        bins[round(angle) % 180] = bins.get(round(angle) % 180, 0.) + length
        total += length
    families = []
    for angle in sorted(bins, key=bins.get, reverse=True):
        for fam in families:
            if min(abs(angle - fam[0]), 180 - abs(angle - fam[0])) <= 6:
                fam[1] += bins[angle]
                break
        else:
            families.append([angle, bins[angle]])
    return [(a, w / total) for a, w in families] if total else []


def check_shapes(design, report):
    by_chart, strokes = {}, {}
    for layer in design.get('layers', []):
        for item in layer.get('items', []):
            pts = [tuple(map(float, p)) for p in item.get('points', [])]
            where, chart = item.get('id', layer.get('name')), item.get('chart')
            closed = item.get('type') == 'polygon'
            segments = list(zip(pts, pts[1:] + (pts[:1] if closed else [])))
            # Mosaic fields are areas, not lines; only edges of line-like items count toward the angle family.
            if not (isinstance(item.get('fill'), dict) and item['fill'].get('pattern')):
                by_chart.setdefault(chart, []).extend(segments)
            if item.get('type') != 'stroke':
                continue
            key = (chart, tuple(pts))
            strokes.setdefault(key, []).append(where)
            if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6 and 'echo' not in str(where).lower():
                report.add('warn', 'outline-frame', where, 'closed outline on its own reads as a sticker frame',
                           'Make it a solid wedge or a negative cut, or an echo of a neighbouring solid shape (same angle, smaller; put "echo" in the id).')
            if float(item.get('width', 0)) >= .06 and item.get('taper', 'none') == 'none':
                report.add('warn', 'equal-width-band', where, f'{float(item["width"]):.2f} m stroke with no taper looks like a marker line',
                           'Draw wide bands as polygons that widen and narrow, or taper the stroke.')
    for (chart, _), wheres in strokes.items():
        if len(wheres) > 1:
            report.add('warn', 'stacked-strokes', ', '.join(wheres), 'the same path is stroked more than once (glow or outline imitation)',
                       'No glow or outline effects; one stroke per path. Separation comes from a dark channel beside the line.')
    angles = {}
    for chart, segments in by_chart.items():
        families = direction_families(segments)
        major = [(round(a), round(w, 3)) for a, w in families if w >= .05]
        angles[chart] = major
        if len(major) > 4:
            report.add('warn', 'too-many-angles', f'chart {chart}', f'{len(major)} line directions each carry >=5% of the edge length: {major}',
                       'Use the airframe axis, the leading-edge sweep and the trailing-edge sweep (plus at most one diagonal).')
    return angles


def check_images(design, design_dir, report):
    seen = {}
    for layer in design.get('layers', []):
        for spec in layer.get('images', []):
            if 'source' not in spec:
                continue
            path = (design_dir / spec['source']).resolve()
            key = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else str(path)
            seen.setdefault(key, []).append(spec.get('id', spec['source']))
    for key, wheres in seen.items():
        if len(wheres) > 1:
            report.add('error', 'repeated-art', ', '.join(wheres), 'one character image is placed more than once (mirroring or recropping counts too)',
                       'Give every portrait position its own source image; find more official art if needed.')


def lint(design_path):
    design_path = Path(design_path)
    design = json.loads(design_path.read_text(encoding='utf-8'))
    palette = design.get('palette', {})
    report = Report()
    families = check_colors(design, palette, report)
    texts = check_text(design, palette, report)
    angles = check_shapes(design, report)
    check_images(design, design_path.parent, report)
    order = {'error': 0, 'warn': 1}
    report.hits.sort(key=lambda h: order[h['level']])
    return dict(schema_version=1, design=str(design_path), errors=sum(h['level'] == 'error' for h in report.hits),
                warnings=sum(h['level'] == 'warn' for h in report.hits), hits=report.hits,
                vivid_hue_families=[[f[0], f[-1]] for f in families], line_angle_families=angles, text_inventory=texts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--design', type=Path, required=True, help='vector_paint design JSON')
    parser.add_argument('--out', type=Path, help='Write the full report here (new file)')
    parser.add_argument('--strict', action='store_true', help='Exit 1 on warnings too')
    args = parser.parse_args(argv)
    result = lint(args.design)
    if args.out:
        if args.out.exists():
            raise SystemExit(f'Refusing to overwrite {args.out}')
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(errors='backslashreplace')  # legacy Windows consoles cannot print CJK text
    for h in result['hits']:
        out.write(f"{h['level'].upper():5} {h['code']:22} {h['where']}: {h['why']}\n      -> {h['fix']}\n")
    out.write(f"{result['errors']} errors, {result['warnings']} warnings; text to check line by line:\n")
    for t in result['text_inventory']:
        out.write(f"  {t['id']}: {t['text']!r} ({t['font']} {t['variation'] or ''} {t['height']} m)\n")
    return 1 if result['errors'] or (args.strict and result['warnings']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
