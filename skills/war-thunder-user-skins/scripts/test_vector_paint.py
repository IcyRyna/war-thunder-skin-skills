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


if __name__ == '__main__':
    unittest.main()
