import json
import math
from pathlib import Path
import tempfile
import unittest
import argparse

import numpy as np
from PIL import Image, ImageDraw

import replica_measure as rm

COAT = (51, 51, 52)


def save(path, arr):
    Image.fromarray(np.asarray(arr, np.uint8)).save(path)
    rm._IMAGES.pop(str(Path(path).resolve()), None)
    return path


def supersampled_polygon(size, verts, colour, base=COAT, ss=8):
    big = Image.new('RGB', (size[0] * ss, size[1] * ss), base)
    ImageDraw.Draw(big).polygon([(x * ss + ss / 2 - .5, y * ss + ss / 2 - .5) for x, y in verts], fill=colour)
    return np.asarray(big.resize(size, Image.BOX))


class ReplicaMeasureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_trace_finds_straight_edges_within_a_texel(self):
        truth = [(40.3, 50.2), (150.6, 70.4), (130.1, 160.8), (30.7, 140.5)]
        path = save(self.root / 'a.png', supersampled_polygon((200, 200), truth, (183, 54, 66)))
        rep = rm.trace(path, (0, 0, 200, 200), 'red', min_area=100, eps=2)
        self.assertEqual(len(rep['shapes']), 1)
        verts = rep['shapes'][0]['vertices']
        self.assertEqual(len(verts), 4)
        for t in truth:
            self.assertLess(min(math.dist(t, v) for v in verts), .75)

    def test_trace_keeps_curved_outlines_full_size(self):
        # curves are many short runs that are not refitted; their vertices still sit on the 50 % edge, not half a
        # texel inside it (that made traced letters and thin rings look half a pixel thinner than the author's)
        circle = [(100 + 40 * math.cos(t), 100 + 40 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 400, endpoint=False)]
        path = save(self.root / 'c.png', supersampled_polygon((200, 200), circle, (183, 54, 66)))
        rep = rm.trace(path, (0, 0, 200, 200), 'red', min_area=100, eps=.8)
        # within 1.5 %: the red class starts at about 35 % coverage, so its mask edge sits ~0.15 px outside the 50 % line
        # (without the half-texel push the circle came out 1.4 % small)
        self.assertLess(abs(rep['shapes'][0]['area_px'] / (math.pi * 40 ** 2) - 1), .015)

    def test_fill_holes_fills_lettering_but_keeps_coat_slots_open(self):
        img = np.zeros((120, 220, 3)); img[:] = COAT
        img[20:100, 20:200] = (183, 54, 66)
        img[40:60, 40:70] = (236, 237, 236)                  # a letter cut into the field
        img[70:80, 90:180] = COAT                            # a dark slot the author left in the field
        img[62:88, 120:135] = (236, 237, 236)                # a letter running over the slot (one hole with it)
        path = save(self.root / 'h.png', img)
        rep = rm.trace(path, (0, 0, 220, 120), 'red', min_area=100, eps=1, fill_holes=True)
        holes = rep['shapes'][0]['holes']
        xs = [x for h in holes for x, _ in h]
        self.assertTrue(holes)
        self.assertGreater(min(xs), 85)                      # only slot texels stay open; both letters were filled
        self.assertLess(max(y for h in holes for _, y in h), 82)

    def test_ramp_recovers_two_stops_and_colours(self):
        img = np.zeros((60, 200, 3)); img[:] = COAT
        c0, c1 = np.array([141, 42, 40]), np.array([189, 55, 68])
        for x in range(10, 190):
            t = min(1, max(0, (x - 50) / 100))
            img[10:50, x] = c0 * (1 - t) + c1 * t
        path = save(self.root / 'r.png', np.round(img))
        g = rm.ramp(path, (0, 0, 200, 60), 'red', angle=0)
        self.assertLess(abs(g['stops'][0] - 50), 6)
        self.assertLess(abs(g['stops'][1] - 150), 6)
        self.assertEqual(g['colors'][0], '#8d2a28')
        self.assertEqual(g['colors'][1], '#bd3744')

    def _mosaic_field(self, cell, angle, origin, size=360):
        V, U = np.mgrid[0:size, 0:size].astype(float)
        i, j, up, m = rm.lattice_coords(U, V, origin, cell, angle)
        rng = np.random.default_rng(3)
        key = (i * 1000 + j) * 2 + up
        uniq, inv = np.unique(key, return_inverse=True)
        k = rng.choice([.86, .93, 1., 1.06, 1.12], len(uniq))[inv.reshape(key.shape)]
        base = np.array([183, 54, 66], float)
        img = np.where(k[..., None] <= 1, base * k[..., None], base + (255 - base) * (k[..., None] - 1))
        img[m * cell * math.sqrt(3) / 2 < 1.5] = base                       # 1.5 px gap of the base colour
        return np.clip(np.round(img), 0, 255)

    def test_mosaic_recovers_the_lattice_and_reports_edge_evidence(self):
        path = save(self.root / 'm.png', self._mosaic_field(70, 12, (13.0, 21.0)))
        fit = rm.mosaic(path, (0, 0, 360, 360), 'redall', erode=2, cell_range=(50, 120))
        lat = fit['lattice']
        self.assertLess(abs(lat['cell_px'] - 70), 1.5)
        self.assertLess(abs(((lat['angle_deg'] - 12 + 30) % 60) - 30), .6)
        self.assertGreater(fit['edge_ratio'], 2)
        # a smooth ramp has a tiny score with large triangles but no step edges on the lattice lines
        img = np.zeros((360, 360, 3)); x = np.arange(360) / 359
        img[:] = (np.array([141, 42, 40]) * (1 - x)[:, None] + np.array([189, 55, 68]) * x[:, None])[None]
        flat = save(self.root / 'f.png', np.round(img))
        fit = rm.mosaic(flat, (0, 0, 360, 360), 'redall', erode=2, init_cell=150, init_angle=10, fix_cell=True)
        self.assertLess(fit['edge_ratio'], 1.6)

    def test_icon_registers_bitmap_and_finds_the_drop_shadow(self):
        icon = Image.new('RGBA', (400, 200), (0, 0, 0, 0))
        arrow = [(0, 100), (120, 20), (120, 70), (400, 70), (400, 130), (120, 130), (120, 180)]
        ImageDraw.Draw(icon).polygon(arrow, fill=(255, 255, 255, 255))
        icon.save(self.root / 'icon.png')
        img = np.zeros((160, 260, 3)); img[:] = COAT
        shape = [(30 + x * .5, 30 + y * .5) for x, y in arrow]
        shadow = supersampled_polygon((260, 160), [(x, y + 6) for x, y in shape], (82, 49, 49))
        body = supersampled_polygon((260, 160), shape, (255, 255, 255), base=(0, 0, 0)).astype(float) / 255
        xs = np.arange(260)
        t = np.clip((xs - 60) / 120, 0, 1)
        ramp = np.array([141, 42, 40]) * (1 - t)[:, None] + np.array([189, 55, 68]) * t[:, None]
        img = shadow * (1 - body) + ramp[None] * body
        path = save(self.root / 'i.png', np.round(img))
        rep, placed, _ = rm.icon(path, (0, 0, 260, 160), self.root / 'icon.png')
        self.assertGreater(rep['iou'], .93)
        self.assertLess(abs(rep['scale'] - .5), .02)
        self.assertTrue(rep['shadow']['used'])
        dx, dy = rep['shadow']['offset_px']
        self.assertLessEqual(abs(dx), 1)             # the arrow is symmetric about its axis: +-1 px is a tie
        self.assertEqual(dy, 6)
        self.assertEqual(placed.size, (260, 160))

    def test_region_skips_flat_game_red_off_the_coat_but_keeps_author_marks(self):
        rng = np.random.default_rng(0)
        img = np.zeros((200, 300, 3)); img[:] = COAT
        img[20:120, 160:290] = rng.integers(10, 90, (100, 130, 3))             # mechanical detail
        img[50:80, 190:250] = (143, 44, 41)                                    # the game's own red tag in it
        img[40:100, 20:120] = (183, 54, 66)                                    # an author mark on the coat
        path = save(self.root / 'g.png', img)
        a = argparse.Namespace(author=str(path), box=[0, 0, 300, 200], name='t', classes=['red'], rings=[], min_area=40, eps=1.,
                               close=0, exclude=[], ramp_area=1200, solid_below=6, mosaic_area=10 ** 9, mosaic_score=6, edge_ratio=2.,
                               coat=[51, 51, 52], coat_tol=8, context_min=.6, context_min_large=.15, context_area=30000,
                               mechanical_rgb=[143, 44, 41], seed_start=100, out=str(self.root / 'wb'))
        path, plan = rm.region(a)
        self.assertEqual(len(plan['elements']), 1)
        self.assertTrue(any('mechanical' in n for n in plan['notes']))
        self.assertEqual(len(plan['skipped_boxes']), 1)
        # without a measured mechanical colour nothing red is skipped
        a.mechanical_rgb, a.name = None, 't2'
        _, plan = rm.region(a)
        self.assertEqual(len(plan['elements']), 2)


    def test_region_keeps_real_mosaics_and_rejects_flat_fields(self):
        img = np.zeros((380, 760, 3)); img[:] = COAT
        img[10:370, 10:370] = self._mosaic_field(110, 12, (13.0, 21.0), size=380)[10:370, 10:370]
        rng = np.random.default_rng(5)
        img[10:370, 390:750] = np.array([183, 54, 66]) + rng.integers(-1, 2, (360, 360, 1))   # flat with 1-level noise
        path = save(self.root / 'mf.png', np.clip(img, 0, 255))
        a = argparse.Namespace(author=str(path), box=[0, 0, 760, 380], name='m', classes=['red'], rings=[], min_area=400, eps=1.,
                               close=0, exclude=[], include=[], ramp_area=1200, solid_below=6, mosaic_area=50000, mosaic_score=6,
                               edge_ratio=2., level_dev=.01, coat=[51, 51, 52], coat_tol=8, context_min=.6, context_min_large=.15,
                               context_area=30000, mechanical_rgb=None, seed_start=100, out=str(self.root / 'wb2'))
        _, plan = rm.region(a)
        by_x = sorted(plan['elements'], key=lambda e: rm.shape_of(e['polygon'])['vertices'][0][0])
        self.assertIn('mosaic', by_x[0]['fill'])
        self.assertNotIn('mosaic', by_x[1]['fill'])


if __name__ == '__main__':
    unittest.main()
