import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import vector_paint


def plane(path, mirrored=False):
    """A 2 x 2 m plate in X/Z (normal +Y); UV follows X and Z linearly."""
    quads = [(-1., 1., -1., 1.)] if not mirrored else [(-1., 1., -1., 0.), (-1., 1., 0., 1.)]
    tris, uvs = [], []
    for x0, x1, z0, z1 in quads:
        corners = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
        for a, b, c in ((0, 2, 1), (0, 3, 2)):
            tri = [corners[a], corners[b], corners[c]]
            tris.append([[x, 0., z] for x, z in tri])
            uvs.append([[(x + 1) / 2, (z + 1) / 2] for x, z in tri])
    np.savez(path, triangles=np.asarray(tris, np.float32), uvs=np.asarray(uvs, np.float32),
             node_ids=np.zeros(len(tris), np.int32), names=np.asarray(['plate']))


def islands(path, boxes):
    """Separate plates: each (x0, x1, z0, z1, u0, u1, v0, v1) maps a world box in X/Z to its own UV box."""
    tris, uvs = [], []
    for x0, x1, z0, z1, u0, u1, v0, v1 in boxes:
        corners = [(x0, z0, u0, v0), (x1, z0, u1, v0), (x1, z1, u1, v1), (x0, z1, u0, v1)]
        for a, b, c in ((0, 2, 1), (0, 3, 2)):
            tri = [corners[a], corners[b], corners[c]]
            tris.append([[x, 0., z] for x, z, _, _ in tri])
            uvs.append([[u, v] for _, _, u, v in tri])
    np.savez(path, triangles=np.asarray(tris, np.float32), uvs=np.asarray(uvs, np.float32),
             node_ids=np.zeros(len(tris), np.int32), names=np.asarray(['plate']))


class VectorPaintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        plane(self.root / 'g.npz')

    def tearDown(self):
        self.temp.cleanup()

    def run_design(self, layers, chart=None, name='out', protect=None, size=64):
        design = dict(schema_version=1, supersample=4, atlas=dict(width=size, height=size),
                      palette=dict(signature='#ff1663', accent='#e7e7e7'),
                      charts=[chart or dict(id='top', u='x', v='z', normal=dict(axis='y', min=.5))], layers=layers)
        (self.root / f'{name}.json').write_text(json.dumps(design), encoding='utf-8')
        args = ['--geometry', str(self.root / 'g.npz'), '--design', str(self.root / f'{name}.json'), '--out', str(self.root / name)]
        if protect is not None:
            Image.fromarray(protect).save(self.root / 'protect.png')
            args += ['--protect', str(self.root / 'protect.png')]
        parser_args = vector_paint.argparse.Namespace(geometry=Path(args[1]), design=Path(args[3]), out=Path(args[5]),
                                                       base=None, protect=Path(args[7]) if protect is not None else None)
        receipt = vector_paint.run(parser_args)
        return receipt, [np.asarray(Image.open(self.root / name / layer['file'])) for layer in receipt['layers']]

    def test_polygon_is_antialiased_not_stair_stepped(self):
        # Diagonal half-plane: edge texels must carry fractional coverage.
        receipt, (layer,) = self.run_design([dict(name='field', items=[dict(type='polygon', chart='top',
                                               points=[[-1.2, -1.2], [1.2, -1.2], [-1.2, 1.2]], fill='signature')])])
        alpha = layer[:, :, 3]
        self.assertEqual(int(alpha[63, 0]), 255)   # x=-1, z=-1 corner (v=0 at the bottom row)
        self.assertEqual(int(alpha[0, 63]), 0)
        partial = ((alpha > 20) & (alpha < 235)).sum()
        self.assertGreater(partial, 40)
        self.assertEqual(tuple(layer[63, 0, :3]), (255, 22, 99))
        self.assertEqual(receipt['zero_hit_items'], [])

    def test_stroke_tapers_to_a_point_without_round_cap(self):
        _, (layer,) = self.run_design([dict(name='line', items=[dict(type='stroke', chart='top', points=[[-.9, 0], [.9, 0]],
                                              width=.4, taper='end', fill='accent')])])
        alpha = layer[:, :, 3].astype(int)
        column = lambda x: alpha[:, int(round((x + 1) / 2 * 63))].sum()
        self.assertGreater(column(-.8), column(0) * .95)
        self.assertGreater(column(0), column(.7) * 2)
        self.assertEqual(column(.97), 0)          # nothing beyond the tip
        self.assertGreater(column(-.88), 0)
        self.assertEqual(alpha[:, :2].sum(), 0)  # butt start, no cap

    def test_halftone_marks_shrink_along_ramp_and_mosaic_stays_near_base(self):
        _, (half, mosaic) = self.run_design([
            dict(name='half', items=[dict(type='polygon', chart='top', points=[[-1, -1], [1, -1], [1, 1], [-1, 1]],
                                          fill=dict(pattern='tri-halftone', color='signature', cell=.12, **{'from': [-1, 0], 'to': [1, 0]}))]),
            dict(name='mosaic', items=[dict(type='polygon', chart='top', points=[[-1.2, -1.2], [1.2, -1.2], [1.2, 1.2], [-1.2, 1.2]],
                                            fill=dict(pattern='tri-mosaic', color='signature', cell=.25, jitter=.08))])])
        a = half[:, :, 3].astype(float)
        self.assertGreater(a[:, 5:15].mean(), a[:, 30:34].mean() + 20)
        self.assertGreater(a[:, 30:34].mean(), a[:, 55:60].mean() + 5)
        rgb = mosaic[:, :, :3].astype(float)
        self.assertGreater(rgb[:, :, 0].std() + rgb[:, :, 1].std() + rgb[:, :, 2].std(), 1)
        self.assertLess(np.abs(rgb[:, :, 1] - 22).max(), 22 * .08 + 3)
        self.assertEqual(int(mosaic[:, :, 3].min()), 255)

    def test_field_ending_at_surface_edge_leaves_partial_edge_texels(self):
        # Fields need bleed past the real surface edge, otherwise island borders darken.
        _, (layer,) = self.run_design([dict(name='field', items=[dict(type='polygon', chart='top',
                                              points=[[-1, -1], [1, -1], [1, 1], [-1, 1]], fill='accent')])])
        self.assertLess(int(layer[0, 0, 3]), 255)
        self.assertEqual(int(layer[32, 32, 3]), 255)

    def test_abs_axis_mirrors_one_shape_to_both_sides(self):
        mirrored = self.root / 'm.npz'
        plane(mirrored, mirrored=True)
        (self.root / 'g.npz').unlink(); mirrored.rename(self.root / 'g.npz')
        _, (layer,) = self.run_design([dict(name='wedge', items=[dict(type='polygon', chart='top',
                                              points=[[-.5, .3], [.5, .3], [.5, .7], [-.5, .7]], fill='accent')])],
                                      chart=dict(id='top', u='x', v='abs_z'))
        alpha = layer[:, :, 3]
        self.assertTrue(np.array_equal(alpha, alpha[::-1, :]))
        self.assertGreater(int(alpha.sum()), 0)

    def test_foreshortened_chart_warns_and_protect_mask_is_respected(self):
        protect = np.zeros((64, 64), np.uint8); protect[:, :32] = 255
        receipt, (layer,) = self.run_design([dict(name='field', items=[dict(type='polygon', chart='side',
                                                points=[[-2, -1], [2, -1], [2, 1], [-2, 1]], fill='accent')])],
                                            chart=dict(id='side', u='x', v='y'), protect=protect)
        self.assertTrue(any('foreshortened' in w for w in receipt['warnings']))
        self.assertEqual(int(layer[:, :32, 3].sum()), 0)

    def test_zero_hit_item_and_bad_design_are_reported(self):
        receipt, _ = self.run_design([dict(name='field', items=[
            dict(id='lost', type='polygon', chart='top', points=[[5, 5], [6, 5], [6, 6]], fill='accent'),
            dict(type='polygon', chart='top', points=[[-1, -1], [0, -1], [0, 0]], fill='accent')])])
        self.assertEqual(receipt['zero_hit_items'], ['lost'])
        with self.assertRaises(ValueError):
            self.run_design([dict(name='x', items=[dict(type='stroke', chart='top', points=[[0, 0], [1, 0]], width=.1,
                                                         taper='end', taper_length=5, fill='accent')])], name='bad')
        with self.assertRaises(ValueError):
            self.run_design([dict(name='x', items=[dict(type='polygon', chart='top', points=[[0, 0], [1, 0], [1, 1]],
                                                         fill=dict(pattern='tri-halftone', color='accent', cell=.1))])], name='bad2')

    def test_image_and_text_layers_place_mirror_fade_and_report(self):
        art = np.zeros((40, 80, 4), np.uint8)
        art[:, :40] = (255, 0, 0, 255)      # left half red
        art[:, 40:] = (0, 0, 255, 255)      # right half blue
        Image.fromarray(art, 'RGBA').save(self.root / 'art.png')
        layers = [dict(name='art', images=[
                      dict(id='panel', chart='top', source='art.png', width=1.6, center=[0, 0]),
                      dict(id='lost', chart='top', source='art.png', width=.2, center=[9, 9])]),
                  dict(name='type', images=[dict(id='word', chart='top', text='HI', height=.3, center=[0, .6], color='#ffffff')])]
        receipt, (image, text) = self.run_design(layers)
        # u=x runs along atlas columns, v=z along rows (bottom = -1).
        self.assertGreater(int(image[32, 20, 0]), 200)    # x<0 -> image left -> red
        self.assertGreater(int(image[32, 44, 2]), 200)    # x>0 -> blue
        self.assertEqual(int(image[32, 2, 3]), 0)         # outside the 1.6 m panel
        self.assertGreater(int(text[:, :, 3].sum()), 0)
        self.assertEqual(receipt['zero_hit_items'], ['lost'])
        self.assertTrue(any(r['id'] == 'panel' and r['sample_hits'] > 0 for r in receipt['images']))
        flipped, (image2, _) = self.run_design([dict(name='art', images=[dict(id='p', chart='top', source='art.png', width=1.6, center=[0, 0], flip=True)]),
                                                dict(name='type', images=[dict(chart='top', text='X', height=.2, center=[0, 0])])], name='flip')
        self.assertGreater(int(image2[32, 20, 2]), 200)   # mirrored: blue on the left
        faded, (image3, _) = self.run_design([dict(name='art', images=[dict(chart='top', source='art.png', width=1.6, center=[0, 0],
                                                                            fade={'from': [-.8, 0], 'to': [.8, 0]})]),
                                              dict(name='type', images=[dict(chart='top', text='X', height=.2, center=[0, 0])])], name='fade')
        self.assertGreater(int(image3[32, 12, 3]), int(image3[32, 50, 3]) + 100)
        with self.assertRaises(ValueError):
            self.run_design([dict(name='bad', images=[dict(chart='top', source='art.png', text='X', width=1, center=[0, 0])])], name='bad3')

    def test_shade_multiplies_brightness_across_the_shape(self):
        _, (layer,) = self.run_design([dict(name='bar', items=[dict(type='polygon', chart='top', points=[[-1.2, -1.2], [1.2, -1.2], [1.2, 1.2], [-1.2, 1.2]],
                                              fill=dict(color='#c8c8c8', shade={'from': [0, -1], 'to': [0, 1], 'stops': [[0, 1], [.5, 1], [1, .5]]}))])])
        r = layer[:, :, 0].astype(int)
        self.assertLessEqual(abs(int(r[63, 32]) - 200), 1)     # z=-1: full
        self.assertLessEqual(abs(int(r[40, 32]) - 200), 2)     # first half held at 1
        self.assertLessEqual(abs(int(r[0, 32]) - 100), 2)      # z=+1: x0.5
        self.assertTrue(np.array_equal(layer[:, 10, :3], layer[:, 50, :3]))   # constant along the other axis
        with self.assertRaises(ValueError):
            self.run_design([dict(name='x', items=[dict(type='polygon', chart='top', points=[[0, 0], [1, 0], [1, 1]],
                                                         fill=dict(color='#ffffff', shade={'from': [0, 0], 'to': [0, 1], 'stops': [[.6, 1], [.2, .5]]}))])], name='bad')

    def test_frame_places_design_units_on_atlas_pixels(self):
        # 4 atlas px per design unit from atlas pixel (10, 20): a 5 x 2 rectangle covers columns 10-30, rows 20-28.
        chart = dict(id='top', u='x', v='z', frame=dict(origin=[10, 20], x=[4, 0], y=[0, 4]))
        _, (layer,) = self.run_design([dict(name='r', items=[dict(type='polygon', chart='top', points=[[0, 0], [5, 0], [5, 2], [0, 2]], fill='accent')])],
                                      chart=chart)
        a = layer[:, :, 3]
        self.assertEqual(int(a[24, 20]), 255)
        self.assertEqual(int(a[24, 35]), 0)
        self.assertEqual(int(a[31, 20]), 0)
        self.assertEqual(int(a[24, 6]), 0)
        self.assertGreater(int(a[24, 11]), 200)

    def test_polygon_holes_leave_the_inside_open(self):
        _, (layer,) = self.run_design([dict(name='o', items=[dict(type='polygon', chart='top', points=[[-.8, -.8], [.8, -.8], [.8, .8], [-.8, .8]],
                                            holes=[[[-.4, -.4], [.4, -.4], [.4, .4], [-.4, .4]]], fill='accent')])])
        a = layer[:, :, 3]
        self.assertEqual(int(a[32, 32]), 0)
        self.assertEqual(int(a[32, 12]), 255)
        self.assertEqual(int(a[12, 32]), 255)

    def test_mosaic_levels_darken_by_multiplying_and_lighten_toward_white(self):
        _, (layer,) = self.run_design([dict(name='m', items=[dict(type='polygon', chart='top', points=[[-1.2, -1.2], [1.2, -1.2], [1.2, 1.2], [-1.2, 1.2]],
                                            fill=dict(pattern='tri-mosaic', color='#c80000', cell=.4, levels=[[.9, 1], [1.1, 1]]))])])
        g = layer[:, :, 1].astype(int)
        r = layer[:, :, 0].astype(int)
        light = g >= 24
        self.assertGreater(light.mean(), .2)
        self.assertLess(light.mean(), .8)
        self.assertLessEqual(int(g.max()), 26)                  # 10 % toward white from 0
        self.assertGreaterEqual(int(r[g == 0].min()), 179)     # dark step is 200 x 0.9

    def test_mosaic_mirror_repeats_the_same_triangles_across_the_axis(self):
        def field(mirror):
            fill = dict(pattern='tri-mosaic', color='#c80000', cell=.37, angle=11, levels=[[.8, 1], [1, 1], [1.2, 1]])
            if mirror:
                fill['mirror'] = {'from': [-2, 0], 'to': [2, 0]}
            return [dict(name='m', items=[dict(type='polygon', chart='top', points=[[-1.2, -1.2], [1.2, -1.2], [1.2, 1.2], [-1.2, 1.2]], fill=fill)])]
        _, (plain,) = self.run_design(field(False), name='plain')
        _, (mirrored,) = self.run_design(field(True), name='mirrored')
        inside = mirrored[:, :, 3] == 255
        rows = np.flatnonzero(inside.any(1))
        top, bottom = rows.min(), rows.max()
        def flip_match(layer):
            body = layer[top:bottom + 1, :, :3].astype(int)
            same = np.abs(body - body[::-1]).max(-1) <= 2
            return same[inside[top:bottom + 1]].mean()
        self.assertGreater(flip_match(mirrored), .9)
        self.assertLess(flip_match(plain), .7)
        with self.assertRaises(ValueError):
            vector_paint.compile_fill(dict(color='#c80000', mirror={'from': [0, 0], 'to': [1, 0]}), {})

    def test_island_seed_limits_the_chart_and_bleed_fills_only_unused_texels(self):
        islands(self.root / 'g.npz', [(-1, 0, -1, 1, .1, .4, .1, .9), (0, 1, -1, 1, .6, .9, .1, .9)])
        field = [dict(name='f', items=[dict(type='polygon', chart='top', points=[[-1.5, -1.5], [1.5, -1.5], [1.5, 1.5], [-1.5, 1.5]], fill='accent')])]
        _, (both,) = self.run_design(field, name='both')
        _, (left,) = self.run_design(field, chart=dict(id='top', u='x', v='z', island=[[16, 32]]), name='left')
        self.assertGreater(int(both[32, 48, 3]), 0)
        self.assertEqual(int(left[32, 48, 3]), 0)              # the other island is not painted
        self.assertEqual(int(left[32, 16, 3]), 255)
        # default bleed: a few texels past the island edge (u = 0.4 -> column 25.2) take the colour; far texels stay empty
        self.assertEqual(int(left[32, 28, 3]), 255)
        self.assertEqual(int(left[32, 34, 3]), 0)


if __name__ == '__main__':
    unittest.main()
