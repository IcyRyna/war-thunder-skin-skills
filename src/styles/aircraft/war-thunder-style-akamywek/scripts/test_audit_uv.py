"""Pixel contracts at the clean-base, shared surface and island-padding boundaries."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image

import airframe_setup
import surface_map
import vector_paint
from test_vector_paint import islands


class NativeAtlasAudit(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.geo = self.root / 'airframe.npz'

    def shared_wings(self):
        # Two physical wings in one chart, mirrored U, identical atlas footprint.
        islands(self.geo, [(-3, -1, -1, 1, 0, 1, 0, 1), (1, 3, -1, 1, 1, 0, 0, 1)])
        Image.new('RGBA', (32, 32), (200, 80, 50, 128)).save(self.root / 'art.png')
        design = dict(schema_version=1, supersample=1, bleed_px=0, atlas=dict(width=64, height=64),
                      charts=[dict(id='both', u='x', v='z')], layers=[
                          dict(name='left', images=[dict(id='left', chart='both', source='art.png',
                                                         center=[-2, 0], width=1)]),
                          dict(name='right', images=[dict(id='right', chart='both', source='art.png',
                                                          center=[2, 0], width=1)]),
                          dict(name='right-type', images=[dict(id='right-type', chart='both', text='JET',
                                                               center=[2, 0], height=0.3)]),
                      ])
        path = self.root / 'design.json'
        path.write_text(json.dumps(design), encoding='utf-8')
        return path

    def test_mirrored_wings_have_one_writer_for_images_and_type(self):
        args = SimpleNamespace(geometry=self.geo, design=self.shared_wings(), base=None,
                               protect=None, out=self.root / 'paint')
        receipt = vector_paint.run(args)
        left, right, text = receipt['images']
        left_image = np.asarray(Image.open(args.out / 'layers/01-left.png'))
        self.assertEqual(left_image[32, 32, 3], 128)
        self.assertGreater(left['sample_hits'], 500)
        self.assertEqual(right['sample_hits'], 0)
        self.assertEqual(text['sample_hits'], 0)
        self.assertGreater(right['nonowner_samples'], 500)
        self.assertGreater(text['nonowner_samples'], 0)
        for path in ('02-right.png', '03-right-type.png'):
            self.assertFalse(np.any(np.asarray(Image.open(args.out / 'layers' / path))[:, :, 3]))

    def test_visible_map_flags_the_mirrored_wing_that_cannot_write(self):
        args = SimpleNamespace(geometry=self.geo, design=self.shared_wings(), protect=None, chart=[],
                               scale=32., threshold=.15, out=self.root / 'map')
        report = surface_map.run(args)
        risks = {item['id']: item['risky_share'] for item in report['risky_items']}
        self.assertNotIn('left', risks)
        self.assertGreater(risks.get('right', 0), .95)
        self.assertGreater(risks.get('right-type', 0), .95)

    def test_masked_clean_preserves_stock_rgb_and_data_alpha(self):
        islands(self.geo, [(-3, -1, -1, 1, .1, .4, .2, .8), (1, 3, -1, 1, .6, .9, .2, .8)])
        yy, xx = np.indices((64, 64))
        src = np.zeros((64, 64, 4), np.uint8)
        src[:, :32, :3] = [130, 131, 130]
        src[:, 32:, :3] = [130, 18, 23]
        src[:, :, 3] = (xx * 2 + yy * 3) % 256
        template = self.root / 'stock.png'
        Image.fromarray(src).save(template)
        for atlas in (64, 128):
            with self.subTest(atlas=atlas):
                out = self.root / f'clean-{atlas}'
                airframe_setup.main(['clean', '--geometry', str(self.geo), '--template', str(template),
                                     '--work', '64', '--atlas', str(atlas), '--out', str(out)])
                mask = np.array(Image.open(out / 'mechanical-mask.png')) > 0
                self.assertTrue(mask[atlas // 2, 3 * atlas // 4])
                self.assertFalse(mask[atlas // 2, atlas // 4])
                actual = np.array(Image.open(out / 'clean-base.png').convert('RGBA'))
                expected_alpha = np.array(Image.fromarray(src[:, :, 3]).resize((atlas, atlas), Image.Resampling.NEAREST))
                np.testing.assert_array_equal(actual[:, :, 3], expected_alpha)
                if atlas == 64:
                    np.testing.assert_array_equal(actual[mask], src[mask])
                np.testing.assert_array_equal(actual[atlas // 2, atlas // 4, :3], [51, 51, 52])

    def test_data_alpha_does_not_change_paint_opacity(self):
        islands(self.geo, [(-1, 1, -1, 1, 0, 1, 0, 1)])
        stock = np.empty((64, 64, 4), np.uint8)
        stock[:, :, :3] = (20, 40, 60)
        stock[:, :, 3] = np.arange(64, dtype=np.uint8) * 4
        template = self.root / 'base.png'
        Image.fromarray(stock).save(template)
        polygon = dict(id='coat', type='polygon', chart='wing', points=[[-2,-2], [2,-2], [2,2], [-2,2]],
                       fill=dict(color='#c88056', opacity=.5))
        design = dict(schema_version=1, supersample=1, bleed_px=0, charts=[dict(id='wing', u='x', v='z')],
                      layers=[dict(name='coat', items=[polygon])])
        path = self.root / 'design.json'
        path.write_text(json.dumps(design), encoding='utf-8')
        out = self.root / 'result'
        vector_paint.run(SimpleNamespace(geometry=self.geo, design=path, base=template, protect=None, out=out))
        actual = np.array(Image.open(out / 'composite.png'))
        reference = Image.alpha_composite(Image.new('RGBA', (1,1), (20,40,60,255)),
                                          Image.new('RGBA', (1,1), (200,128,86,128))).getpixel((0,0))
        np.testing.assert_array_equal(actual[:, :, 3], stock[:, :, 3])
        self.assertTrue(np.all(actual[:, :, :3] == reference[:3]))

    def test_explicit_mechanical_nodes_override_skin_seed_at_native_resolution(self):
        islands(self.geo, [(-1, 1, -1, 1, .1, .45, .2, .8), (1, 3, -1, 1, .65, .94, .15, .71)])
        with np.load(self.geo) as model:
            data = dict(model)
        data['names'] = np.asarray(['body', 'nozzle_panel'])
        data['node_ids'] = np.array([0, 0, 1, 1], np.int32)
        np.savez(self.geo, **data)
        template = self.root / 'original.png'
        Image.new('RGBA', (128, 128), (130, 131, 132, 113)).save(template)
        args = ['clean', '--geometry', str(self.geo), '--template', str(template), '--work', '32',
                '--atlas', '128', '--skin-seed', '100', '64']
        expected = np.zeros((128, 128), bool)
        vector_paint._used(data['uvs'][2:].astype(np.float64), 128, 128, expected)
        for pattern in ('nozzle_panel', 'nozzle_*'):
            out = self.root / ('exact' if pattern == 'nozzle_panel' else 'wildcard')
            airframe_setup.main([*args, '--protect-node', pattern, '--out', str(out)])
            mask = np.array(Image.open(out / 'mechanical-mask.png')) > 0
            np.testing.assert_array_equal(mask, expected)
            base = np.array(Image.open(out / 'clean-base.png'))
            self.assertTrue(np.all(base[mask] == [130, 131, 132, 113]))
            self.assertTrue(np.all(base[~mask] == [51, 51, 52, 113]))
            receipt = json.loads((out / 'islands.json').read_text('utf-8'))['node_protection']
            self.assertEqual(receipt['nodes'], ['nozzle_panel'])
            self.assertEqual(receipt['native_added'], expected.sum())
            self.assertGreater(receipt['work_classified_as_skin'], 0)
        bad = self.root / 'bad'
        with self.assertRaisesRegex(ValueError, 'matches no node'):
            airframe_setup.main([*args, '--protect-node', 'nozzle_*', '--protect-node', 'typo', '--out', str(bad)])
        self.assertFalse(bad.exists())

    def test_bleed_cannot_jump_from_atlas_or_crop_edge(self):
        layer = np.zeros((8, 10, 4), np.uint8)
        layer[4, 0] = [201, 30, 80, 255]
        layer[0, 7] = [12, 160, 80, 170]
        protected = np.zeros(layer.shape[:2], bool)
        protected[4, 1] = True
        actual = vector_paint.bleed(layer, protected, 1)
        yy, xx = np.indices(layer.shape[:2])
        reachable = ((np.maximum(abs(yy - 4), xx) <= 1) | (np.maximum(yy, abs(xx - 7)) <= 1)) & ~protected
        np.testing.assert_array_equal(actual[:, :, 3] > 0, reachable)
        np.testing.assert_array_equal(actual[3, 1], layer[4, 0])


if __name__ == '__main__':
    unittest.main()
