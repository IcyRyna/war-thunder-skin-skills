"""Numerical, scene-contract and non-overwriting finish-preview regressions."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
import sys
from unittest import mock

import numpy as np
from PIL import Image

import finish_preview as finish
import scene_preview as scene


class FinishTests(unittest.TestCase):
    def fixture(self, root):
        triangles = np.array([[[-1., -1., 0.], [1., -1., 0.], [-1., 1., 0.]],
                              [[1., -1., 0.], [1., 1., 0.], [-1., 1., 0.]]], np.float32)
        uv = np.array([[[0., 0.], [1., 0.], [0., 1.]],
                       [[1., 0.], [1., 1.], [0., 1.]]], np.float32)
        geometry = root/'geometry.npz'
        np.savez_compressed(geometry, triangles=triangles, uvs=uv,
                            node_ids=np.zeros(2, np.int32), names=np.array(['body']),
                            material_ids=np.zeros(2, np.int32), material_names=np.array(['paint']),
                            material_resources=np.array(['[]']))
        color, packed = root/'color.png', root/'packed.png'
        Image.new('RGBA', (8, 8), (140, 110, 85, 255)).save(color)
        Image.new('RGBA', (8, 8), (100, 128, 100, 128)).save(packed)
        camera = dict(basis=np.eye(3).tolist(), center=[0., 0.], scale=20., width=64, height=48)
        raw = dict(schema_version=1, geometry=self.ref(geometry), width=64, height=48,
                   display_state=dict(description='two-triangle finish sample'), cameras=dict(test=camera),
                   materials=[dict(id=0, name='paint', source_shader='dynamic_masked_chrome_bump',
                                   color=self.ref(color), packed=self.ref(packed), normal_convention='ag_xy')])
        path = root/'scene.json'
        self.write(path, raw)
        return path, raw, color, packed

    @staticmethod
    def ref(path):
        return dict(path=path.name, sha256=scene.file_hash(path))

    @staticmethod
    def write(path, raw):
        path.write_text(json.dumps(raw), encoding='utf-8')

    @staticmethod
    def pixels(path):
        with Image.open(path) as image:
            return np.asarray(image).copy()

    def run_render(self, path, output, **kwargs):
        options = dict(profile='dynamic_masked_chrome_public', view='test', size=64)
        options.update(kwargs)
        return finish.render(path, output, **options)

    def test_channel_numeric_decode_and_profile_boundary(self):
        data = np.array([.25, .9, .4, .1])
        self.assertEqual(finish.packed_parameters(data, False), (.75, .4))
        self.assertAlmostEqual(finish.packed_parameters(data, True)[1], .64)
        self.assertEqual(finish.packed_parameters(np.array([1., 0., 0., 0.]), False), (.04, 0.))
        raw = dict(materials=[dict(id=1, name='aux', source_shader='chrome_like_name', packed={}),
                              dict(id=0, name='body', source_shader='dynamic_masked_chrome_bump', packed={})])
        self.assertEqual(finish.profile_flags(raw, 'generic').tolist(), [False, False])
        self.assertEqual(finish.profile_flags(raw, 'dynamic_masked_chrome_public').tolist(), [True, False])
        raw['materials'].append(dict(id=2, name='constant proxy', source_shader='dynamic_masked_chrome_bump'))
        self.assertEqual(finish.profile_flags(raw, 'dynamic_masked_chrome_public').tolist(), [True, False, False])
        for profile in ['dynamic_masked_chrome_bump', 'automatic', '']:
            with self.assertRaises(ValueError):
                finish.profile_flags(raw, profile)
        raw['materials'][1]['source_shader'] = 'body_chrome'
        with self.assertRaises(ValueError):
            finish.profile_flags(raw, 'dynamic_masked_chrome_public')
        raw['materials'][1]['source_shader'] = 'dynamic_masked_chrome_bump'
        raw['materials'][1].pop('packed')
        with self.assertRaises(ValueError):
            finish.profile_flags(raw, 'dynamic_masked_chrome_public')

    def test_environment_changes_complete_field_and_direct_light(self):
        zero, lights0, power0 = finish.environment_settings('outdoor')
        one, lights1, power1 = finish.environment_settings('studio')
        self.assertEqual((zero, one), (0, 1))
        self.assertFalse(np.array_equal(lights0, lights1))
        self.assertFalse(np.array_equal(power0, power1))
        self.assertTrue(np.allclose(np.linalg.norm(lights0, axis=1), 1.))
        for direction in ([0., 1., 0.], [0., -1., 0.], [1., 0., 0.]):
            first = finish.environment_radiance(np.asarray(direction), 0)
            second = finish.environment_radiance(np.asarray(direction), 1)
            self.assertTrue(np.isfinite(first).all() and (first >= 0).all())
            self.assertFalse(np.allclose(first, second))
        with self.assertRaises(ValueError):
            finish.environment_settings('unknown')

    def test_chrome_brdf_matches_frozen_source_lab_radiance_samples(self):
        # Captured independently from the retained source-matched laboratory
        # driver, before substituting this implementation. These are radiance,
        # before exposure/tone mapping, with identical base/view/light fields.
        base, view = np.array([.12, .24, .4]), np.array([0., 0., 1.])
        samples = [
            ('outdoor', .25, 0., [0., 0., 1.], [.08523770765796243, .16941801271794593, .3092501291468826]),
            ('outdoor', .6, .65, [.2, .3, .9], [.0836408238888734, .18163963704344938, .3563328267785026]),
            ('outdoor', .9, 1., [-.4, .2, .8], [.04500113400192957, .09790943280335024, .18522554439459632]),
            ('studio', .25, 0., [0., 0., 1.], [.029874324793156666, .05438805896897333, .08394025755240267]),
            ('studio', .6, .65, [.2, .3, .9], [.046190821192509134, .08267529004700645, .12125530561450842]),
            ('studio', .9, 1., [-.4, .2, .8], [.02383587142596471, .045147817753351804, .06831683767858097]),
        ]
        for name, rough, metal, normal, expected in samples:
            with self.subTest(environment=name, roughness=rough, metal=metal):
                eid, lights, powers = finish.environment_settings(name)
                actual = finish.ggx_ibl(base, np.asarray(normal), view, rough, metal, True, lights, powers, eid)
                np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-12)

    def test_aligned_low_roughness_direct_peak_matches_analytic_ggx(self):
        base = np.array([.12, .24, .4])
        direction = np.array([0., 0., 1.])
        lights = direction.reshape(1, 3)
        for chrome in [False, True]:
            previous = None
            for rough in [.04, .06, .1, .25]:
                ambient = finish.ggx_ibl(base, direction, direction, rough, 0., chrome, lights, np.zeros(1), 0)
                lit = finish.ggx_ibl(base, direction, direction, rough, 0., chrome, lights, np.ones(1), 0)
                direct = lit-ambient
                diffuse = (.45*rough-.475)*rough+1 if chrome else 1.
                expected = (base*diffuse+.04/(4*rough**4))/math.pi
                np.testing.assert_allclose(direct, expected, rtol=1e-10, atol=1e-10)
                if previous is not None:
                    self.assertTrue(np.all(previous > direct))
                previous = direct

    def test_real_scene_two_environments_and_profile_are_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            before = {p: scene.file_hash(p) for p in (path, color, packed, root/'geometry.npz')}
            first = self.run_render(path, root/'outdoor.png')
            again = self.run_render(path, root/'repeat.png')
            second = self.run_render(path, root/'studio.png', environment='studio')
            generic = self.run_render(path, root/'generic.png', profile='generic')
            self.assertGreater(first['covered_pixels'], 0)
            self.assertEqual(first['image_sha256'], again['image_sha256'])
            self.assertEqual(first['camera_sha256'], second['camera_sha256'])
            self.assertEqual(first['camera_sha256'], generic['camera_sha256'])
            self.assertFalse(np.array_equal(self.pixels(root/'outdoor.png'), self.pixels(root/'studio.png')))
            self.assertFalse(np.array_equal(self.pixels(root/'outdoor.png'), self.pixels(root/'generic.png')))
            self.assertEqual(first['camera']['width'], 64)
            self.assertEqual(first['camera']['height'], 48)
            self.assertEqual(first['image_sha256'], scene.file_hash(root/'outdoor.png'))
            recorded = json.loads((root/'outdoor.json').read_text(encoding='utf-8'))
            self.assertEqual(recorded, first)
            self.assertFalse(first['game_verified'])
            self.assertEqual(first['lighting']['exposure'], second['lighting']['exposure'])
            self.assertEqual(first['normal_mapping']['materials'][0]['convention'], 'ag_xy')
            self.assertTrue(first['material_decoding'][0]['chrome_profile_applied'])
            self.assertFalse(generic['material_decoding'][0]['chrome_profile_applied'])
            for p, digest in before.items():
                self.assertEqual(scene.file_hash(p), digest)
                self.assertIn(dict(path=str(p.resolve()), sha256=digest), first['source_inputs'])
            self.assertFalse(list(root.glob('*-depth*')))
            self.assertFalse(list(root.glob('.artifact-*')))

    def test_normal_convention_and_explicit_off_change_only_normal_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            Image.new('RGBA', (8, 8), (100, 185, 100, 110)).save(packed)
            raw['materials'][0]['packed'] = self.ref(packed)
            self.write(path, raw)
            first = self.run_render(path, root/'ag.png')
            off = self.run_render(path, root/'off.png', normal=False)
            raw['materials'][0]['normal_convention'] = 'ga_xy'
            alternate = root/'ga-scene.json'
            self.write(alternate, raw)
            second = self.run_render(alternate, root/'ga.png')
            self.assertFalse(np.array_equal(self.pixels(root/'ag.png'), self.pixels(root/'ga.png')))
            self.assertFalse(np.array_equal(self.pixels(root/'ag.png'), self.pixels(root/'off.png')))
            self.assertEqual(first['material_decoding'], off['material_decoding'])
            self.assertEqual(second['normal_mapping']['materials'][0]['convention'], 'ga_xy')
            self.assertFalse(off['normal_mapping']['materials'][0]['active'])
            self.assertEqual(off['normal_mapping']['materials'][0]['convention'], 'ag_xy')

    def test_same_name_materials_keep_independent_id_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            geometry = root/'geometry.npz'
            with np.load(geometry, allow_pickle=False) as stored:
                arrays = {key: stored[key] for key in stored.files}
            arrays['material_ids'][1] = 1
            arrays['material_names'] = np.array(['paint', 'paint'])
            arrays['material_resources'] = np.array(['[]', '[]'])
            np.savez_compressed(geometry, **arrays)
            raw['geometry'] = self.ref(geometry)
            raw['materials'].append({**raw['materials'][0], 'id': 1})
            self.write(path, raw)
            report = self.run_render(path, root/'out.png')
            coverage = report['material_coverage_by_id']
            self.assertEqual(set(coverage), {'0', '1'})
            self.assertEqual(coverage['0']['name'], coverage['1']['name'])
            self.assertGreater(coverage['0']['pixels'], 0)
            self.assertGreater(coverage['1']['pixels'], 0)
            self.assertEqual(sum(item['pixels'] for item in coverage.values()), report['covered_pixels'])

    def test_camera_long_edge_preserves_framing_and_external_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            external = root/'camera.json'
            self.write(external, raw['cameras']['test'])
            loaded = scene.load_scene(path)
            screen0, camera0, _ = finish.scaled_camera(loaded, 'test', None, 64)
            screen1, camera1, inputs = finish.scaled_camera(loaded, 'custom', external, 128)
            self.assertEqual((camera1['width'], camera1['height']), (128, 96))
            self.assertTrue(np.allclose(screen1[:, :, :2], screen0[:, :, :2]*2))
            self.assertTrue(np.array_equal(screen1[:, :, 2], screen0[:, :, 2]))
            self.assertEqual(camera0['center'], camera1['center'])
            self.assertEqual(inputs[external.resolve()], scene.file_hash(external))
            for size in [True, 0, 4097, 64.5]:
                with self.assertRaises(ValueError):
                    finish.scaled_camera(loaded, 'test', None, size)

    def test_zbuffer_uses_visible_triangle_and_face_culling(self):
        screen = np.array([[[2., 2., 0.], [14., 2., 0.], [2., 14., 0.]],
                           [[2., 2., .01], [14., 2., .01], [2., 14., .01]]], np.float32)
        ids = np.zeros(2, np.int32)
        owners = finish.raster_owners(screen, ids, np.ones(1, np.bool_), np.eye(3, dtype=np.float32), 16, 16)
        self.assertEqual(set(owners[owners >= 0].tolist()), {1})
        culled = finish.raster_owners(screen, ids, np.zeros(1, np.bool_), np.eye(3, dtype=np.float32), 16, 16)
        self.assertTrue(np.all(culled == -1))

    def test_existing_main_or_receipt_never_overwrites_input_or_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            before = scene.file_hash(color)
            with self.assertRaises((RuntimeError, OSError)):
                self.run_render(path, color)
            self.assertEqual(scene.file_hash(color), before)
            protected = root/'out.json'
            protected.write_bytes(b'previous receipt')
            with self.assertRaises((RuntimeError, OSError)):
                self.run_render(path, root/'out.png')
            self.assertEqual(protected.read_bytes(), b'previous receipt')
            self.assertFalse((root/'out.png').exists())

    def test_changed_input_cancels_pair_with_failure_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            original = finish.shade
            def changed(*args, **kwargs):
                result = original(*args, **kwargs)
                Image.new('RGBA', (8, 8), 'blue').save(color)
                return result
            with mock.patch.object(finish, 'shade', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'input changed during rendering'):
                    self.run_render(path, root/'out.png')
            self.assertFalse((root/'out.png').exists())
            self.assertFalse((root/'out.json').exists())
            failures = list((root/'.artifact-failures').glob('*.failure.json'))
            self.assertEqual(len(failures), 1)
            receipt = json.loads(failures[0].read_text(encoding='utf-8'))
            self.assertEqual(receipt['state'], 'failed')
            self.assertEqual(len(receipt['outputs']), 2)

    def test_scene_hash_mismatch_and_empty_camera_publish_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, raw, color, packed = self.fixture(root)
            raw['materials'][0]['color']['sha256'] = '0'*64
            self.write(path, raw)
            with self.assertRaises(ValueError):
                self.run_render(path, root/'out.png')
            raw['materials'][0]['color'] = self.ref(color)
            raw['cameras']['test']['center'] = [100., 100.]
            self.write(path, raw)
            with self.assertRaisesRegex(ValueError, 'no visible triangles'):
                self.run_render(path, root/'out.png')
            self.assertFalse((root/'out.png').exists())
            self.assertFalse((root/'out.json').exists())

    def test_loaded_renderer_rejects_changed_source_before_using_scene(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy = root/'finish_preview_copy.py'
            copy.write_bytes(Path(finish.__file__).read_bytes())
            spec = importlib.util.spec_from_file_location('finish_preview_identity_test_copy', copy)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                spec.loader.exec_module(module)
                copy.write_text(copy.read_text(encoding='utf-8')+'\n# later revision\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'source changed after module import'):
                    module.render(root/'unused-scene.json', root/'out.png', profile='generic')
                self.assertFalse((root/'out.png').exists())
                self.assertFalse((root/'out.json').exists())
            finally:
                sys.modules.pop(spec.name, None)


if __name__ == '__main__':
    unittest.main()
