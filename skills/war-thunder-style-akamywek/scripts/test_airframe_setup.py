import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import airframe_setup as af


def grid(x0, x1, z0, z1, nx, nz, uv_of, y_of=lambda x, z: 0.):
    """Triangulated X/Z patch; uv_of(x, z) -> (u, v) in 0..1 (v up), y_of(x, z) -> height."""
    tris, uvs = [], []
    xs, zs = np.linspace(x0, x1, nx + 1), np.linspace(z0, z1, nz + 1)
    for i in range(nx):
        for j in range(nz):
            c = [(xs[i], zs[j]), (xs[i + 1], zs[j]), (xs[i + 1], zs[j + 1]), (xs[i], zs[j + 1])]
            for a, b, d in ((0, 2, 1), (0, 3, 2)):
                tri = [c[a], c[b], c[d]]
                tris.append([[x, y_of(x, z), z] for x, z in tri])
                uvs.append([list(uv_of(x, z)) for x, z in tri])
    return tris, uvs


def save(path, parts, names=('plate',)):
    tris = sum((p[0] for p in parts), []); uvs = sum((p[1] for p in parts), [])
    np.savez(path, triangles=np.asarray(tris, np.float32), uvs=np.asarray(uvs, np.float32),
             node_ids=np.zeros(len(tris), np.int32), names=np.asarray(list(names)))


class AirframeSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_frame_recovers_the_flat_part_and_ignores_a_distorted_fillet_in_the_same_island(self):
        # wing: atlas px = (1000, 7000) + x * (500 cos 10, -500 sin 10) + z * (500 sin 10, 500 cos 10) on a 8192 atlas
        A = 8192 - 1
        c, s = np.cos(np.radians(10)), np.sin(np.radians(10))
        px = lambda x, z: (1000 + 500 * (c * x + s * z), 7000 + 500 * (-s * x + c * z))
        to_uv = lambda p: (p[0] / A, 1 - p[1] / A)
        wing = grid(0, 4, 0, 2, 16, 8, lambda x, z: to_uv(px(x, z)))
        # fillet sharing the wing's z = 0 edge: gently curved, its UV stretched (an unrolled fairing)
        fillet = grid(0, 4, -.6, 0, 16, 3, lambda x, z: to_uv((px(x, z)[0], px(x, z)[1] + 150 * z * z)), lambda x, z: .25 * z * z)
        # a separate flat island elsewhere: canard at 600 px/m
        canard = grid(0, 1, 0, 1, 4, 4, lambda x, z: to_uv((5000 + 600 * x, 1000 + 600 * z)))
        # a 1 cm helper box with whole-atlas UVs (vector_paint.helper_triangles drops it)
        helper = ([[[9, 0, 9], [9.01, 0, 9], [9.01, 0, 9.01]], [[9, 0, 9], [9.01, 0, 9.01], [9, 0, 9.01]]],
                  [[[0, 0], [1, 0], [1, 1]], [[0, 0], [1, 1], [0, 1]]])
        save(self.root / 'g.npz', [wing, fillet, canard, helper])
        g, keep = af.skin(self.root / 'g.npz')
        self.assertEqual(int((~keep).sum()), 2)
        rows = af.fit_frames(g, keep, atlas=8192, min_area=.05)
        self.assertEqual(len(rows), 2)                       # wing + fillet are one UV island, the canard another
        wing_row = max(rows, key=lambda r: r['area_m2'])
        f = wing_row['frame']
        # trimming keeps fillet triangles distorted by less than its 4 px floor, so about 1 px of bias remains
        np.testing.assert_allclose(f['origin'], [1000, 7000], atol=2.)
        np.testing.assert_allclose(f['x'], [500 * c, -500 * s], atol=1.)
        np.testing.assert_allclose(f['y'], [500 * s, 500 * c], atol=2.)
        # on the flat wing itself the frame is within about a pixel everywhere
        err = [np.hypot(*(np.add(f['origin'], np.add(np.multiply(f['x'], x), np.multiply(f['y'], z))) - px(x, z)))
               for x in np.linspace(0, 4, 9) for z in np.linspace(0, 2, 5)]
        self.assertLess(max(err), 2.)
        self.assertGreater(wing_row['residual_px']['island'][2], 10.)   # the fillet is reported, not hidden
        canard_row = min(rows, key=lambda r: r['area_m2'])
        np.testing.assert_allclose(canard_row['frame']['x'], [600, 0], atol=.5)
        self.assertEqual(canard_row['plane'], ['x', 'z'])
        # the seed lies inside one of the island's triangles (vector_paint tests seeds that way)
        u, v = canard_row['seed']
        self.assertTrue(5000 <= u <= 5600 and 1000 <= v <= 1600)

    def test_classify_keeps_dark_islands_and_repaints_grey_ones_unless_forced(self):
        used = np.zeros((40, 40), bool); used[2:18, 2:18] = True; used[22:38, 22:38] = True; used[22:38, 2:18] = True
        stock = np.zeros((40, 40, 3), np.float32)
        stock[2:18, 2:18] = (128, 130, 133)                # camouflage grey: skin
        stock[22:38, 22:38] = (40, 40, 42)                 # dark radome-like island
        stock[22:38, 2:18] = (150, 30, 30)                 # red service part: mechanical
        lab, skin, share, px = af.classify(stock, used)
        self.assertTrue(skin[lab[10, 10]])
        self.assertFalse(skin[lab[30, 30]])
        self.assertFalse(skin[lab[30, 10]])
        lab, skin, share, px = af.classify(stock, used, forced=[lab[30, 30]])
        self.assertTrue(skin[lab[30, 30]])
        self.assertFalse(skin[lab[30, 10]])

    def test_shares_count_the_four_base_layout_classes_inside_the_mask(self):
        rgb = np.zeros((10, 10, 3), np.uint8)
        rgb[:, :4] = (51, 51, 52); rgb[:, 4:7] = (178, 53, 50); rgb[:, 7:8] = (179, 99, 107); rgb[:, 8:] = (244, 244, 244)
        mask = np.ones((10, 10), bool); mask[:, 9] = False
        s = af.shares(rgb, mask)
        self.assertAlmostEqual(s['dark'], 100 * 40 / 90, places=1)
        self.assertAlmostEqual(s['signature'], 100 * 30 / 90, places=1)
        self.assertAlmostEqual(s['tint'], 100 * 10 / 90, places=1)
        self.assertAlmostEqual(s['white'], 100 * 10 / 90, places=1)

    def test_cli_map_and_frames_write_their_tables(self):
        A = 8191
        plate = grid(-1, 1, -1, 1, 4, 4, lambda x, z: ((2000 + 400 * x) / A, 1 - (3000 + 400 * z) / A))
        save(self.root / 'p.npz', [plate])
        af.main(['map', '--geometry', str(self.root / 'p.npz'), '--size', '512', '--out', str(self.root / 'map')])
        table = json.loads((self.root / 'map/islands.json').read_text(encoding='utf-8'))
        self.assertEqual(len(table['islands']), 1)
        self.assertEqual(table['islands'][0]['facing'], 'y+')
        coords = np.load(self.root / 'map/coords.npz')
        y, x = np.argwhere(coords['used'])[len(np.argwhere(coords['used'])) // 2]
        u_atlas = x * 8192 / 512
        self.assertAlmostEqual(float(coords['x'][y, x]), (u_atlas - 2000) / 400, delta=.06)
        af.main(['frames', '--geometry', str(self.root / 'p.npz'), '--out', str(self.root / 'frames.json')])
        rows = json.loads((self.root / 'frames.json').read_text(encoding='utf-8'))['islands']
        np.testing.assert_allclose(rows[0]['frame']['x'], [400, 0], atol=.5)
        np.testing.assert_allclose(rows[0]['frame']['y'], [0, 400], atol=.5)


if __name__ == '__main__':
    unittest.main()
