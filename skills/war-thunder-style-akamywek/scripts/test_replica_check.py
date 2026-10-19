import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import replica_check as rc
import replica_measure as rm
import vector_paint
from test_vector_paint import islands


class ReplicaCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        polys = dict(shapes=[dict(index=0, vertices=[[4, 4], [28, 4], [28, 28], [4, 28]], holes=[]),
                             dict(index=1, vertices=[[36, 10], [60, 10], [60, 30], [36, 30]], holes=[])])
        (self.root / 'polygons.json').write_text(json.dumps(polys), encoding='utf-8')
        fit = dict(lattice=dict(origin=[3., 5.], cell_px=12., angle_deg=10., score=1.), edge_ratio=3.,
                   gap=dict(inset=.04), levels=[[.9, .5], [1.1, .5]],
                   base_ramp=dict(direction_deg=0., at_origin=[150., 40., 40.], per_px=[.5, 0., 0.]))
        (self.root / 'fit.json').write_text(json.dumps(fit), encoding='utf-8')
        plan = dict(layer='g', elements=[dict(id='a', polygon='polygons.json:0', fill=dict(color='#b7303c')),
                                         dict(id='b', polygon='polygons.json:1', fill=dict(color='#e7e3e7'))])
        (self.root / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_edit_drops_attaches_mosaic_with_gap_base_and_mirror(self):
        plan = rc.edit(self.root / 'plan.json', self.root / 'plan2.json', drop=['b'], mosaics=[('a', self.root / 'fit.json')],
                       mirrors=[('a', 0, 16, 64, 16)], base_from_fit=True)
        self.assertEqual([e['id'] for e in plan['elements']], ['a'])
        fill = plan['elements'][0]['fill']
        self.assertIn('ramp_px', fill)                      # the base is the fitted gap colour, not the field median
        self.assertEqual(fill['ramp_px']['colors'], ['#982828', '#a42828'])
        self.assertEqual(fill['mirror_px'], {'from': [0., 16.], 'to': [64., 16.]})
        design_fill = rc._fill(fill, self.root, 8.)
        self.assertEqual(design_fill['pattern'], 'tri-mosaic')
        self.assertEqual(design_fill['cell'], 1.5)
        self.assertEqual(design_fill['mirror'], {'from': [0., 2.], 'to': [8., 2.]})
        vector_paint.compile_fill(design_fill, {})          # the converted fill is a valid vector_paint fill

    def test_edit_refuses_a_mosaic_fitted_on_another_shape(self):
        fit = json.loads((self.root / 'fit.json').read_text(encoding='utf-8'))
        fit['shapes'] = [dict(ref=None, extent=[36, 10, 60, 30])]          # measured on shape 1, not on element a
        (self.root / 'fit-b.json').write_text(json.dumps(fit), encoding='utf-8')
        with self.assertRaises(SystemExit):
            rc.edit(self.root / 'plan.json', self.root / 'plan3.json', mosaics=[('a', self.root / 'fit-b.json')])
        rc.edit(self.root / 'plan.json', self.root / 'plan3.json', mosaics=[('b', self.root / 'fit-b.json')])

    def test_straighten_joins_two_vertices_and_drops_the_bump_between(self):
        bumpy = dict(shapes=[dict(index=0, vertices=[[0, 0], [20, 0], [24, -3], [27, 0], [60, 0], [60, 20], [0, 20]], holes=[])])
        (self.root / 'bumpy.json').write_text(json.dumps(bumpy), encoding='utf-8')
        plan = dict(layer='b', elements=[dict(id='f', polygon='bumpy.json:0', fill=dict(color='#b7303c'))])
        (self.root / 'bplan.json').write_text(json.dumps(plan), encoding='utf-8')
        out = rc.edit(self.root / 'bplan.json', self.root / 'bplan2.json', straights=[('f', 0, 0, 60, 0)])
        self.assertEqual(out['elements'][0]['points_px'], [[0., 0.], [60., 0.], [60., 20.], [0., 20.]])

    def test_plan_spreads_seeds_so_a_shape_crossing_islands_paints_both(self):
        # two plates side by side in UV: u 0-0.5 and 0.5-1 of a 64 px atlas; one shape spans both
        islands(self.root / 'g.npz', [(-1, 0, -1, 1, 0., .5, 0., 1.), (0, 1, -1, 1, .5, 1., 0., 1.)])
        polys = dict(shapes=[dict(index=0, vertices=[[8, 20], [56, 20], [56, 40], [8, 40]], holes=[])])
        (self.root / 'wide.json').write_text(json.dumps(polys), encoding='utf-8')
        plan = dict(layer='w', elements=[dict(id='w', polygon='wide.json:0', fill=dict(color='#b7303c'))])
        (self.root / 'wplan.json').write_text(json.dumps(plan), encoding='utf-8')
        design = rc.plan_design([self.root / 'wplan.json'], self.root / 'g.npz', None, size=(64, 64), S=8.)
        seeds = design['charts'][0]['island']
        self.assertTrue(any(s[0] < 31 for s in seeds) and any(s[0] > 33 for s in seeds))
        design['atlas'] = dict(width=64, height=64)
        (self.root / 'd.json').write_text(json.dumps(design), encoding='utf-8')
        args = vector_paint.argparse.Namespace(geometry=self.root / 'g.npz', design=self.root / 'd.json', out=self.root / 'out', base=None, protect=None)
        vector_paint.run(args)
        layer = np.asarray(Image.open(self.root / 'out/composite.png').convert('RGBA'))
        self.assertGreater(int(layer[30, 12, 3]), 200)
        self.assertGreater(int(layer[30, 52, 3]), 200)

    def test_mechanical_mask_keeps_game_red_parts_and_clears_author_marks(self):
        rng = np.random.default_rng(1)
        img = np.zeros((120, 200, 3), np.uint8); img[:] = (51, 51, 52)
        img[10:110, 110:190] = rng.integers(10, 90, (100, 80, 3))
        img[40:60, 130:170] = (143, 44, 41)          # flat game red inside detail: original
        img[39, 130:170] = (97, 47, 46); img[60, 130:170] = (97, 47, 46)   # its anti-aliased rim
        img[30:70, 10:60] = (183, 54, 66)            # author red on the coat
        img[80:90, 10:60] = (143, 44, 41)            # the darkest ramp step, on the coat: design
        keep, listed = rc.mechanical_mask(img, (51, 51, 52), (143, 44, 41))
        self.assertTrue(keep[50, 150])
        self.assertFalse(keep[50, 30])
        self.assertFalse(keep[85, 30])
        self.assertEqual(len(listed), 1)
        keep, listed = rc.mechanical_mask(img, (51, 51, 52), None)
        self.assertFalse(keep.any())

    def test_skin_materials_keep_only_the_colour_map_the_skin_replaces(self):
        main, nozzle = self.root / 'main_c.tga', self.root / 'nozzle_rgb.png'
        mat = lambda name, path: dict(name=name, color=dict(path=str(path), sha256='0')) if path else dict(name=name)
        scene = dict(materials=[mat('skin', main), mat('glass', None), mat('mechanics', main), mat('nozzle', nozzle)])
        (self.root / 's.json').write_text(json.dumps(scene), encoding='utf-8')
        with self.assertRaises(SystemExit):             # two colour maps: the tool does not guess
            rc.skin_materials(self.root / 's.json')
        self.assertEqual(rc.skin_materials(self.root / 's.json', 'main_c'), ['skin', 'mechanics'])
        self.assertEqual(rc.skin_materials(self.root / 's.json', 'skin'), ['skin', 'mechanics'])
        self.assertEqual(rc.skin_materials(self.root / 's.json', 'nozzle'), ['nozzle'])
        with self.assertRaises(SystemExit):
            rc.skin_materials(self.root / 's.json', '.')    # matches both
        scene['materials'].pop()
        (self.root / 's.json').write_text(json.dumps(scene), encoding='utf-8')
        self.assertEqual(rc.skin_materials(self.root / 's.json'), ['skin', 'mechanics'])

    def test_used_mask_ignores_a_helper_box_with_whole_atlas_uvs(self):
        # skin plates cover the left half of the atlas; a 1 cm helper square maps 0-1 UVs like the J-10C tail cube
        boxes = [(-1, 0, -1, 1, 0., .25, 0., 1.), (0, 1, -1, 1, .25, .5, 0., 1.), (2, 2.01, 0, .01, 0., 1., 0., 1.)]
        islands(self.root / 'h.npz', boxes)
        used = rc.used_mask(self.root / 'h.npz', ['*'], (64, 64))
        self.assertLess(used.mean(), .6)
        self.assertTrue(used[:, :30].all() and not used[:, 36:].any())

    def test_plan_takes_a_mosaic_written_directly_and_its_own_provenance(self):
        islands(self.root / 'g.npz', [(-1, 1, -1, 1, 0., 1., 0., 1.)])
        polys = dict(shapes=[dict(index=0, vertices=[[8, 8], [56, 8], [56, 56], [8, 56]], holes=[])])
        (self.root / 'sq.json').write_text(json.dumps(polys), encoding='utf-8')
        plan = dict(layer='d', elements=[dict(id='m', polygon='sq.json:0', fill=dict(color='#b23532', mosaic=dict(cell_px=16, angle_deg=90)))])
        (self.root / 'dplan.json').write_text(json.dumps(plan), encoding='utf-8')
        design = rc.plan_design([self.root / 'dplan.json'], self.root / 'g.npz', None, size=(64, 64), S=8., provenance='independent construction')
        fill = design['layers'][0]['items'][0]['fill']
        self.assertEqual(fill['pattern'], 'tri-mosaic')
        self.assertAlmostEqual(fill['cell'], 2.0)
        self.assertEqual(fill['angle'], 90.)
        self.assertEqual(len(fill['levels']), 6)
        self.assertEqual(design['provenance'], 'independent construction')


if __name__ == '__main__':
    unittest.main()
