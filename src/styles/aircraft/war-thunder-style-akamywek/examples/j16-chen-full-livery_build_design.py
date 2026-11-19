# Example: complete J-16 livery generator (Chen Qianyu, dark base / saturated blue signature), version 10
# of the first piece made with this style, checked with surface_map.py for visibility.  Shows per-side
# charts in priority order (belly before body, up-facing body chart limited to normal y >= 0.3),
# mirrored shapes, image/text layers, outer-fin portrait panels with a frame layer, the inner-fin wedge
# kept forward of the UV strip the left inner fin shares with the right outer fin, belly and side lines
# only on visible flat zones, and six different character sources.  Since the Skill's revision 10 the
# thin lines that v10 drew in white (belly needle, inner-fin lance, outer-fin edge) are signature colour.  Asset paths point to that task;
# replace them, the node names and the coordinates for a new livery.
"""J-16 Chen Qianyu, Akamywek dark-base branch with a saturated blue signature.

Writes design.json for vector_paint.py.  Coordinates are metres on the
original model: x forward (nose ~ +13), y up, z to the aircraft's right.
Every chart is signed per side; shapes are authored for the right side and
mirrored, so text reads correctly on both sides.

Orientation rules (from the calibration render):
- top/bottom charts (u=x, v=z): screen-up = +x, screen-right = +z when seen
  from above; a placement reads upright at screen angle phi with
  rotation = -90 - phi and flip = true.
- side/fin charts (u=x, v=y): right-side faces read with rotation 0;
  left-side faces need flip = true.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAT = ['j_16_aircraft_normal_detail_lo']
BODY = ['fuse', 'tail', 'airbrake_l', 'blister1']

PALETTE = {
    'base': '#2c2e32', 'deep': '#1b1d20',
    'sig': '#3f7fc0', 'sig_hi': '#64a3de', 'sig_deep': '#1f5486', 'sig_tint': '#7f9cb9',
    'white': '#eef0f2', 'pink': '#d0174f', 'grey': '#5d6168',
}


def side_charts():
    charts = []
    for side, sign in (('r', 1), ('l', -1)):
        zr = [0.0, 10] if sign > 0 else [-10, 0.0]
        fin_z = [1.5, 10] if sign > 0 else [-10, -1.5]
        charts += [
            dict(id=f'fin-out-{side}', u='x', v='y', nodes=['tail', 'rudder*'], materials=MAT,
                 where={'y': [0.9, 10], 'z': fin_z}, normal={'axis': 'z' if sign > 0 else '-z', 'min': .55}, facing='abs_z'),
            dict(id=f'fin-in-{side}', u='x', v='y', nodes=['tail', 'rudder*'], materials=MAT,
                 where={'y': [0.9, 10], 'z': fin_z}, normal={'axis': '-z' if sign > 0 else 'z', 'min': .55}, facing='abs_z'),
            dict(id=f'side-{side}', u='x', v='y', nodes=BODY, materials=MAT, where={'z': zr},
                 normal={'axis': 'z' if sign > 0 else '-z', 'min': .62}, facing='abs_z'),
            # Inward-facing walls (between the engines); left plain, charted only to avoid top-chart streaks.
            dict(id=f'tunnel-{side}', u='x', v='y', nodes=BODY, materials=MAT, where={'z': zr},
                 normal={'axis': '-z' if sign > 0 else 'z', 'min': .62}, facing='abs_z'),
            # Belly before body: where the original UV shares texels between the large belly
            # panel and small upper pieces, the belly design wins.
            dict(id=f'belly-{side}', u='x', v='z', nodes=BODY, materials=MAT, where={'z': zr},
                 normal={'axis': 'y', 'max': -0.25}, facing='-y'),
        ]
    for side, sign in (('r', 1), ('l', -1)):
        zr = [0.0, 10] if sign > 0 else [-10, 0.0]
        charts += [
            # Only faces that really look up; the chine slope stays quiet base instead of streaking.
            dict(id=f'body-{side}', u='x', v='z', nodes=BODY, materials=MAT, where={'z': zr},
                 normal={'axis': 'y', 'min': 0.3}, facing='y'),
            dict(id=f'wing-{side}', u='x', v='z', nodes=[f'wing_{side}', f'slat_{side}', f'flaperon_{side}', f'flaperon1_{side}'],
                 materials=MAT, normal={'axis': 'y', 'min': .2}, facing='y'),
            dict(id=f'wingu-{side}', u='x', v='z', nodes=[f'wing_{side}', f'slat_{side}', f'flaperon_{side}', f'flaperon1_{side}'],
                 materials=MAT, normal={'axis': 'y', 'max': -.2}, facing='-y'),
            dict(id=f'stab-{side}', u='x', v='z', nodes=['elevator0' if sign < 0 else 'elevator1'], materials=MAT,
                 normal={'axis': 'y', 'min': .2}, facing='y'),
            dict(id=f'stabu-{side}', u='x', v='z', nodes=['elevator0' if sign < 0 else 'elevator1'], materials=MAT,
                 normal={'axis': 'y', 'max': -.2}, facing='-y'),
        ]
    return charts


def mirror(points):
    return [[x, -z] for x, z in points]


class Layer:
    def __init__(self, name):
        self.name, self.items = name, []

    def add(self, ident, chart, kind, points, fill, both=True, **extra):
        """Author on the right side; for top/bottom charts mirror z, for side/fin charts copy."""
        for side in (('r', 'l') if both else ('r',)):
            pts = points
            if side == 'l' and not chart.startswith(('side', 'fin')):
                pts = mirror(points)
            self.items.append(dict(id=f'{ident}-{side}', type=kind, chart=f'{chart}-{side}', points=pts, fill=fill, **extra))

    def dict(self):
        return dict(name=self.name, items=self.items)


class ImageLayer:
    def __init__(self, name):
        self.name, self.images = name, []

    def top(self, ident, chart_side, center, phi, **spec):
        """Upright at screen angle phi (deg, CCW) seen from above."""
        self.images.append(dict(id=ident, chart=chart_side, center=center, rotation=-90 - phi, flip=True, **spec))

    def side(self, ident, chart_base, center, both=True, **spec):
        for side in (('r', 'l') if both else ('r',)):
            self.images.append(dict(id=f'{ident}-{side}', chart=f'{chart_base}-{side}', center=center,
                                    rotation=0, flip=(side == 'l'), **spec))

    def text_top(self, ident, chart, center_r, phi_r, **spec):
        """Text with letters' up pointing outboard on both sides."""
        self.top(f'{ident}-r', f'{chart}-r', center_r, phi_r, **spec)
        self.top(f'{ident}-l', f'{chart}-l', [center_r[0], -center_r[1]], -phi_r, **spec)

    def dict(self):
        return dict(name=self.name, images=self.images)


def mosaic(color='sig', cell=.24, jitter=.1, gradient=None):
    fill = dict(pattern='tri-mosaic', cell=cell, jitter=jitter)
    if gradient:
        fill['gradient'] = gradient
    else:
        fill['color'] = color
    return fill


def key_sequence(apex_x, base_x, z_in, z_out_aft, pieces, gap, lean):
    """Cut the triangle (apex_x, z_in) - (base_x, z_in) - (base_x, z_out_aft) into pieces.

    lengths: fractions along x from the apex; gap metres; cuts lean by
    `lean` metres of x per metre of z (parallel cuts)."""
    total = apex_x - base_x
    usable = total - gap * (len(pieces) - 1)
    scale = usable / sum(pieces)
    edges, x = [], apex_x
    for i, length in enumerate(pieces):
        start, end = x, x - length * scale
        edges.append((start, end))
        x = end - gap
    def outer(xx):
        return z_in + (z_out_aft - z_in) * (apex_x - xx) / total
    shapes = []
    for start, end in edges:
        # Cut lines are leaned: the outer corner sits `lean * width` further aft.
        zs, ze = outer(start), outer(end)
        shapes.append([[start, z_in], [start - lean * (zs - z_in), zs], [end - lean * (ze - z_in), ze], [end, z_in]])
    return shapes


def build():
    deep, sigf, branch, keys, lines, halftone, art_echo, art, decals, structure = (
        Layer('02-deep-fields'), Layer('03-signature-fields'), Layer('04-branches-tint'), Layer('05-white-keys'),
        Layer('06-companion-lines'), Layer('07-halftone'), ImageLayer('08-character-echo'), ImageLayer('09-characters'),
        ImageLayer('11-type-and-decals'), None)
    fin_frame = Layer('10-fin-frame')
    grad_body = dict({'from': [9.5, 0.6], 'to': [-4.5, 2.0], 'colors': ['sig_deep', 'sig']})

    # --- dorsal -----------------------------------------------------------
    deep.add('spine-channel', 'body', 'polygon', [[5.2, -0.01], [5.2, 0.16], [1.0, 0.30], [-3.0, 0.40], [-6.6, 0.30], [-8.6, 0.12], [-8.6, -0.01]], 'deep')
    sigf.add('shoulder-parent', 'body', 'polygon',
             [[10.2, 0.40], [7.6, 0.66], [5.0, 0.98], [3.0, 1.30], [1.4, 1.62], [-0.8, 1.86], [-3.4, 1.96], [-5.6, 1.92],
              [-5.9, 2.6], [-3.0, 2.7], [0.0, 2.7], [2.4, 2.4], [4.4, 1.7], [7.0, 1.2], [10.0, 0.62]],
             mosaic(cell=.22, gradient=grad_body))
    # Two slanted key groups: long pieces first, heights growing aft, ends cut at one lean.
    def key_row(ident, x0, z0, lengths, h0, h1, gap, lean, drift):
        x = x0
        for i, length in enumerate(lengths):
            h = h0 + (h1 - h0) * i / max(1, len(lengths) - 1)
            z = z0 + drift * (x0 - x)
            keys.add(f'{ident}-{i}', 'body', 'polygon',
                     [[x, z], [x - length, z + drift * length], [x - length - lean * h, z + drift * length + h], [x - lean * h, z + h]], 'white')
            x -= length + gap
    # The first key piece (x 1.85-3.4) sat on hidden geometry under the airbrake since v3: dropped.
    key_row('key-a', 1.69, 0.511, [1.15, .8, .5, .3], .185, .26, .16, 1.1, .03)
    key_row('key-b', 2.2, 0.95, [1.0, .7, .45], .10, .16, .14, 1.1, .05)
    # No hollow echoes: surface_map shows no visible flat pocket for them on the J-16 dorsal.
    # Companion pair along the parent's inner edge.
    for i, off in enumerate([0.14, 0.24]):
        lines.add(f'companion-{i}', 'body', 'stroke', [[4.9, 1.025 - off], [3.0, 1.24 - off], [0.0, 1.70 - off], [-3.2, 1.86 - off]],
                  'sig_hi', width=.028, taper='end', taper_length=2.0)
    # (The dorsal halftone was on hidden geometry behind the wing root; fin and belly keep theirs.)

    # --- wings (top) --------------------------------------------------------
    le = [[2.9, 1.9], [-2.0, 7.5]]
    sigf.add('wing-le-band', 'wing', 'polygon', [[3.2, 1.6], [-2.2, 7.6], [-2.75, 7.6], [1.2, 3.3], [2.0, 1.6]],
             mosaic(cell=.28, gradient=dict({'from': [2.5, 2.2], 'to': [-2.0, 7.0], 'colors': ['sig', 'sig_deep']})))
    lines.add('wing-le-companion', 'wing', 'stroke', [[1.0, 3.25], [-2.3, 6.95]], 'sig_hi', width=.03, taper='end', taper_length=1.5)
    deep.add('wing-tip-band', 'wing', 'polygon', [[-1.0, 6.05], [-6.0, 6.05], [-6.0, 7.6], [-1.0, 7.6]], 'deep')
    branch.add('wing-tip-stripe-0', 'wing', 'polygon', [[-1.0, 6.30], [-6.0, 6.30], [-6.0, 6.55], [-1.0, 6.55]], 'sig_tint')
    branch.add('wing-tip-stripe-1', 'wing', 'polygon', [[-1.0, 6.85], [-6.0, 6.85], [-6.0, 7.10], [-1.0, 7.10]], 'sig_tint')
    # Thin signature edge between character and flaperon.
    branch.add('wing-te-edge', 'wing', 'polygon', [[-2.35, 2.2], [-3.55, 6.05], [-3.70, 6.05], [-2.50, 2.2]], 'sig')

    # --- wing undersides ------------------------------------------------------
    sigf.add('wingu-le-band', 'wingu', 'polygon', [[3.2, 1.6], [-2.2, 7.6], [-2.9, 7.6], [1.0, 3.1], [1.9, 1.6]], 'sig_deep')
    branch.add('wingu-stripe-0', 'wingu', 'polygon', [[-1.0, 6.30], [-6.0, 6.30], [-6.0, 6.55], [-1.0, 6.55]], 'sig_tint')
    branch.add('wingu-stripe-1', 'wingu', 'polygon', [[-1.0, 6.85], [-6.0, 6.85], [-6.0, 7.10], [-1.0, 7.10]], 'sig_tint')

    # --- stabilisers ------------------------------------------------------------
    sigf.add('stab-le-band', 'stab', 'polygon', [[-3.3, 2.0], [-6.3, 5.1], [-6.75, 4.85], [-4.2, 2.0]], mosaic(cell=.22))
    keys.add('stab-white', 'stab', 'polygon', [[-4.35, 2.0], [-6.8, 4.75], [-6.93, 4.68], [-4.55, 2.0]], 'white')
    for i in range(3):
        x0 = -5.25 - .34 * i
        branch.add(f'stab-arrow-{i}', 'stab', 'polygon', [[x0, 2.55], [x0 - .38, 2.72], [x0, 2.89], [x0 - .14, 2.72]], 'sig_hi')
    sigf.add('stabu-le-band', 'stabu', 'polygon', [[-3.3, 2.0], [-6.3, 5.1], [-6.75, 4.85], [-4.2, 2.0]], 'sig_deep')

    # --- belly -----------------------------------------------------------------
    # Organised like the author's Flanker bellies: quiet dark centre, signature mosaic sweeping in
    # from the intake/chine edges and tapering to long spears aft, one white key-comb arrow
    # (a wedge cut by parallel gaps, mirrored into a forward-pointing V) and a long needle pair in
    # the signature colour (white stays on the wide comb: thin white lines read as scratches).  Every end is a real point.
    belly_grad = dict({'from': [12.5, 0.5], 'to': [-7.0, 1.6], 'colors': ['sig_deep', 'sig']})
    sigf.add('belly-chine-sweep', 'belly', 'polygon',
             [[12.9, 0.02], [11.0, 0.42], [8.0, 0.86], [5.0, 1.30], [3.2, 1.95], [2.4, 2.35], [0.0, 2.35], [-2.6, 2.35],
              [-5.0, 2.30], [-7.6, 2.25], [-5.0, 1.98], [-2.6, 1.84], [0.0, 1.82], [2.2, 1.62], [4.4, 1.08], [7.4, 0.70], [10.6, 0.34]],
             mosaic(cell=.26, jitter=.1, gradient=belly_grad))
    # Nacelle spear on the flattest strip of each engine nacelle bottom (|z| ~ 1.25).
    sigf.add('belly-nacelle-spear', 'belly', 'polygon',
             [[2.4, 1.12], [0.0, 1.10], [-3.0, 1.14], [-7.4, 1.22], [-3.0, 1.38], [0.0, 1.40], [2.4, 1.38]],
             mosaic(cell=.22, jitter=.1, color='sig'))
    lines.add('belly-nacelle-companion', 'belly', 'stroke', [[1.8, 1.50], [-2.0, 1.52], [-6.0, 1.50]], 'sig_hi',
              width=.026, taper='both', taper_length=1.4)
    # (No belly halftone: both the sweep's aft end and its inner edge are hidden on the J-16.)
    # Key comb on the flat forward belly between the nose-gear bay (x 5-7.5) and the intake
    # grilles (x < 2.5): one forward-pointing wedge, mirrored into a V, cut by parallel gaps.
    tip_x, base_x, z_base = 4.95, 2.7, 0.92
    def edge(x):
        return z_base * (tip_x - x) / (tip_x - base_x)
    lean = .35
    for i, (x0, x1) in enumerate([(4.95, 4.35), (4.18, 3.68), (3.52, 3.12), (2.97, 2.70)]):
        keys.add(f'belly-comb-{i}', 'belly', 'polygon',
                 [[x0, 0.0], [x0 - lean * edge(x0), edge(x0)], [x1 - lean * edge(x1), edge(x1)], [x1, 0.0]], 'white')
    # Centre needle in the flat tunnel between the nacelles, tapered at both ends.
    lines.add('belly-needle-0', 'belly', 'stroke', [[2.2, 0.36], [-2.0, 0.36], [-6.8, 0.32]], 'sig_hi',
              width=.06, taper='both', taper_length=2.2)
    lines.add('belly-needle-1', 'belly', 'stroke', [[1.4, 0.48], [-1.8, 0.48], [-4.6, 0.46]], 'sig_hi',
              width=.026, taper='both', taper_length=1.4)
    # Small arrow trio at the tail cone, pointing aft.
    for i in range(3):
        x0 = -5.2 - .32 * i  # visible flat strip z .22-.46; the tail cone aft of x -6 is mostly hidden
        branch.add(f'belly-arrow-{i}', 'belly', 'polygon', [[x0, 0.22], [x0 - .32, 0.34], [x0, 0.46], [x0 - .12, 0.34]], 'sig_hi')

    # --- sides (right-handed coordinates, copied to the left) ---------------------
    sigf.add('side-crescent', 'side', 'polygon', [[12.9, -0.05], [10.0, 0.20], [7.0, 0.46], [4.2, 0.72], [1.4, 0.90],
                                                   [-1.0, 0.96], [1.6, 0.76], [4.4, 0.58], [7.2, 0.30], [10.2, 0.05]],
             mosaic(cell=.2, gradient=dict({'from': [12.5, 0], 'to': [0, 0.9], 'colors': ['sig_deep', 'sig']})))
    # Companions run parallel below the crescent's lower edge and never cross it.
    for i, o in enumerate([0.10, 0.17]):
        lines.add(f'side-companion-{i}', 'side', 'stroke', [[8.4, 0.17 - o], [7.2, 0.30 - o], [4.4, 0.58 - o], [1.6, 0.76 - o]],
                  'sig_hi', width=.026, taper='both', taper_length=1.2)
    for i in range(3):
        x0 = -3.3 - .36 * i  # visible flat side above the stabiliser root (aft of x -5 is hidden)
        branch.add(f'side-arrow-{i}', 'side', 'polygon', [[x0, 0.10], [x0 - .40, 0.24], [x0, 0.38], [x0 - .15, 0.24]], 'sig_hi')

    # --- fins ----------------------------------------------------------------------
    def fin_band(offset, width):
        # Parallel to the leading edge (-2.1, 0.9) -> (-4.6, 3.85).
        dx, dy = -2.5, 2.95
        n = math.hypot(dx, dy)
        nx, ny = -dy / n, dx / n  # points aft/inward
        a, b = [-2.1 - .2 * dx / n, 0.9 - .2 * dy / n], [-4.6 + .3 * dx / n, 3.85 + .3 * dy / n]
        p = lambda q, o: [q[0] + nx * o, q[1] + ny * o]
        return [p(a, offset), p(b, offset), p(b, offset + width), p(a, offset + width)]
    # Inner faces: the dorsal language instead of flag stripes.  A signature mosaic wedge hugs the
    # leading edge, wide at the root and tapering to the tip; two signature companions run
    # inside it, converging toward the tip; a halftone dissolves the wedge into the dark field.
    def fin_pt(y, aft):  # `aft` metres behind the leading edge at height y
        return [-2.1 - 2.5 * (y - 0.9) / 2.95 - aft, y]
    sigf.add('fin-in-wedge', 'fin-in', 'polygon',
             [fin_pt(0.75, -0.15), fin_pt(4.0, -0.15), fin_pt(3.75, 0.05), fin_pt(0.75, 1.3)],
             mosaic(cell=.2, jitter=.1, gradient=dict({'from': [-2.6, 0.9], 'to': [-4.6, 3.8], 'colors': ['sig_deep', 'sig']})))
    halftone.add('fin-in-dissolve', 'fin-in', 'polygon',
                 [fin_pt(0.75, 1.3), fin_pt(2.4, 0.6), fin_pt(2.4, 0.95), fin_pt(0.75, 1.65)],
                 dict(pattern='tri-halftone', color='sig', cell=.07, **{'from': [-2.1 - 2.5 * .6 / 2.95 - 0.95, 1.5],
                                                                         'to': [-2.1 - 2.5 * .6 / 2.95 - 1.35, 1.5]}))
    lines.add('fin-in-lance', 'fin-in', 'stroke', [fin_pt(1.15, 1.75), fin_pt(3.35, 0.55)], 'sig_hi',
              width=.04, taper='both', taper_length=.8)
    # Kept forward of the rudder-hinge strip: on the J-16 the left inner fin shares that strip's
    # texels with the right outer fin, whose portrait wins them (v9 lost this line on the left).
    lines.add('fin-in-companion', 'fin-in', 'stroke', [fin_pt(1.3, 1.7), fin_pt(2.6, 0.95)], 'sig_hi',
              width=.03, taper='both', taper_length=.6)
    deep.add('fin-out-root-under', 'fin-out', 'polygon', [[-1.9, 0.80], [-5.7, 0.80], [-5.7, 1.4], [-1.9, 1.4]], 'deep')
    # Frame drawn above the portraits: signature leading-edge strip, dark cap and root band.
    fin_frame.add('fin-out-le-strip', 'fin-out', 'polygon', fin_band(-0.20, 0.30), 'sig')
    fin_frame.add('fin-out-le-white', 'fin-out', 'polygon', fin_band(0.13, 0.035), 'sig_hi')  # id kept from v10; was white
    fin_frame.add('fin-out-cap', 'fin-out', 'polygon', [[-3.9, 3.15], [-5.7, 3.15], [-5.7, 4.1], [-3.9, 4.1]], 'deep')
    fin_frame.add('fin-out-cap-line', 'fin-out', 'polygon', [[-3.9, 3.10], [-5.7, 3.10], [-5.7, 3.15], [-3.9, 3.15]], 'sig_hi')
    fin_frame.add('fin-out-root', 'fin-out', 'polygon', [[-1.9, 0.80], [-5.7, 0.80], [-5.7, 1.16], [-1.9, 1.16]], 'deep')
    fin_frame.add('fin-out-root-line', 'fin-out', 'polygon', [[-1.9, 1.16], [-5.7, 1.16], [-5.7, 1.20], [-1.9, 1.20]], 'sig')

    # --- character art ---------------------------------------------------------------
    art_src = '../assets/artwork/'
    # Right wing: sword pose.  Face at source (720, 420) of 1254 -> target (-0.5, 3.6).
    w = 6.2
    face_r = (720 / 1254 - .5) * w, (.5 - 420 / 1254) * w
    art.top('chen-sword', 'wing-r', [-0.45 - face_r[1], 3.55 - face_r[0]], 0, source=art_src + 'chen-sword-edge-clean-v1.png', width=w,
            fade={'from': [-2.2, 0], 'to': [-3.6, 0]})
    w2 = 6.2
    face_l = (530 / 1254 - .5) * w2, (.5 - 400 / 1254) * w2
    art.top('chen-gesture', 'wing-l', [-0.45 - face_l[1], -3.55 - face_l[0]], 0, source=art_src + 'chen-gesture-edge-clean-v1.png', width=w2,
            fade={'from': [-2.2, 0], 'to': [-3.6, 0]})
    # Echo faces: enlarged, low opacity, outboard behind the main figures; each from its own source.
    derived = '../assets/derived/'
    art_echo.top('echo-r', 'wing-r', [-1.6, 5.3], 0, source=derived + 'echo-stand-face.png', width=3.4,
                 opacity=.22, fade={'from': [-1.0, 5.0], 'to': [-3.6, 6.4]})
    art_echo.top('echo-l', 'wing-l', [-1.6, -5.3], 0, source=derived + 'echo-dash-face.png', width=3.4,
                 opacity=.24, fade={'from': [-1.0, -5.0], 'to': [-3.6, -6.4]})

    # Outer fin portraits: one new official illustration per side, filling the fin as a panel.
    dl = '../assets/downloads/'
    # Right: Snapshot 3 crop (1000x1080), face at (450, 430); reads unflipped on the right side.
    w = 3.9; h = w * 1080 / 1000
    dx, dy = (450 / 1000 - .5) * w, (.5 - 430 / 1080) * h
    art.images.append(dict(id='fin-portrait-r', chart='fin-out-r', source=dl + 'Snapshot_Chen_Qianyu_3/Snapshot_Chen_Qianyu_3.png',
                           crop=[800, 0, 1800, 1080], width=w, center=[-3.9 - dx, 1.95 - dy], rotation=0, flip=False,
                           fade={'from': [-3.8, 1.45], 'to': [-3.8, 1.05]}))
    # Left: Snapshot 1 crop (1200x1080), face at (520, 250); flipped so it reads correctly from the left.
    w = 4.6; h = w * 1080 / 1200
    dx, dy = (520 / 1200 - .5) * w, (.5 - 250 / 1080) * h
    art.images.append(dict(id='fin-portrait-l', chart='fin-out-l', source=dl + 'Snapshot_Chen_Qianyu_1/Snapshot_Chen_Qianyu_1.png',
                           crop=[200, 0, 1400, 1080], width=w, center=[-3.85 + dx, 2.2 - dy], rotation=0, flip=True,
                           fade={'from': [-3.8, 1.45], 'to': [-3.8, 1.05]}))

    # --- type -----------------------------------------------------------------------------
    bold = dict(variation='Bold', font='C:/Windows/Fonts/bahnschrift.ttf')
    light = dict(variation='Light', font='C:/Windows/Fonts/bahnschrift.ttf')
    # Wing name along the trailing edge (right: phi -18; left mirrored).
    decals.top('wing-name-r', 'wing-r', [-2.95, 4.55], -17.5, text='CHEN QIANYU', height=.30, color='white', tracking=.08, **bold)
    decals.top('wing-sub-r', 'wing-r', [-2.52, 4.22], -17.5, text='ARKNIGHTS : ENDFIELD', height=.11, color='sig_hi', tracking=.2, **light)
    decals.top('wing-name-l', 'wing-l', [-2.95, -4.55], 17.5, text='CHEN QIANYU', height=.30, color='white', tracking=.08, **bold)
    decals.top('wing-sub-l', 'wing-l', [-2.52, -4.22], 17.5, text='ENDFIELD INDUSTRIES', height=.11, color='sig_hi', tracking=.2, **light)
    # Dorsal lockups in the dark lane, letters' up pointing outboard.
    decals.text_top('dorsal-name', 'body', [-4.4, 0.95], -90, text='CHEN QIANYU', height=.24, color='white', tracking=.1, **bold)
    decals.text_top('dorsal-sub', 'body', [-4.4, 1.22], -90, text='SHENYANG  J-16', height=.10, color='sig_hi', tracking=.25, **light)
    # Side technical type.
    decals.side('side-model', 'side', [9.7, -0.08], text='J-16', height=.22, color='white', tracking=.05, **bold)
    # Fin type on the dark root band and cap, below and above the portrait.
    decals.side('fin-model', 'fin-out', [-4.35, 0.98], text='J-16', height=.20, color='white', tracking=.06, **bold)
    decals.side('fin-model-sub', 'fin-out', [-3.35, 0.98], text='ENDFIELD INDUSTRIES', height=.06, color='sig_hi', tracking=.3, **light)
    decals.side('fin-cap-name', 'fin-out', [-4.95, 3.42], text='CHEN', height=.12, color='white', tracking=.2, **bold)

    layers = [deep, sigf, branch, keys, lines, halftone, art_echo, art, fin_frame, decals]
    design = dict(schema_version=1, supersample=4, text_pixels_per_metre=500, palette=PALETTE, charts=side_charts(),
                  layers=[layer.dict() for layer in layers])
    (HERE / 'design.json').write_text(json.dumps(design, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(sum(len(l.items) if hasattr(l, 'items') else len(l.images) for l in layers), 'items/placements')


if __name__ == '__main__':
    build()
