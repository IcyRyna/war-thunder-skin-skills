"""Ground input, native RGB export, and actual OpenGL preview regressions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from export_uv_reference import export_rgb
from inspect_skin import inspect
from tank_core import load_image, load_obj, save_dds


class GroundInputTests(unittest.TestCase):
    def test_dds_round_trip_preserves_rgb_hidden_under_alpha_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'color.dds'
            data = np.array([[(255, 223, 12, 0), (16, 99, 219, 128)], [(2, 4, 6, 255), (0, 255, 0, 1)]], dtype=np.uint8)
            save_dds(Image.fromarray(data), path)
            self.assertEqual(load_image(path).tobytes(), data.tobytes())
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, 'Truncated DDS'):
                load_image(path)

    def test_obj_negative_indices_comments_and_quad_triangulation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mesh.obj'
            path.write_text('v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nusemtl armor\nf -4 -3 -2 -1 # panel\n', encoding='utf-8')
            model = load_obj(path)
            self.assertEqual(model['positions'].shape, (2, 3, 3))
            self.assertEqual(model['uvs'].shape, (2, 3, 2))
            self.assertEqual(str(model['material_names'][model['material_ids'][0]]), 'armor')
            self.assertTrue(np.isfinite(model['normals']).all())

    def test_inspection_uses_explicit_semantics_and_rejects_escaping_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'skin'
            folder.mkdir()
            save_dds(Image.new('RGBA', (2, 2), (221, 187, 40, 0)), folder / 'hull.dds')
            blk = folder / 'tank.blk'
            blk.write_text('replace_tex { from:t="hull*" to:t="hull.dds" }\n', encoding='utf-8')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'textures': [{'file': 'hull.tga', 'role': 'color', 'alpha_semantics': 'fixed_rgb', 'color_space': 'srgb'}]}), encoding='utf-8')
            result = inspect(folder, manifest=manifest)
            self.assertTrue(result['passed'], result)
            texture = result['textures'][0]
            self.assertEqual(texture['alpha_semantics'], 'fixed_rgb')
            self.assertEqual(texture['channel_extrema']['A'], (0, 0))
            self.assertEqual(texture['role_source'], 'manifest')
            self.assertEqual(texture['mip_count'], 1)
            blk.write_text('replace_tex { from:t="hull*" to:t="../hull.dds" }', encoding='utf-8')
            self.assertFalse(inspect(folder)['passed'])
            self.assertIn('inside the skin folder', inspect(folder)['issues'][0])


class NativeExportTests(unittest.TestCase):
    def test_native_rgb_export_is_exact_and_read_only_and_nonoverwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'skin.dds'
            save_dds(Image.new('RGBA', (7, 5), (233, 27, 146, 0)), source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            output = root / 'rgb'
            result = export_rgb([source], output)
            self.assertTrue(result['all_rgb_exact'])
            with Image.open(output / 'skin-rgb-native.png') as image:
                self.assertEqual(image.size, (7, 5))
                self.assertEqual(image.mode, 'RGB')
                self.assertEqual(image.getpixel((0, 0)), (233, 27, 146))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                export_rgb([source], output)

    def test_failure_after_first_staged_export_does_not_publish_a_partial_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good, bad = root / 'good.dds', root / 'bad.dds'
            save_dds(Image.new('RGBA', (2, 2), (50, 100, 150, 0)), good)
            bad.write_bytes(b'DDS broken')
            output = root / 'rgb'
            with self.assertRaises(ValueError):
                export_rgb([good, bad], output)
            self.assertFalse((output / 'good-rgb-native.png').exists())
            self.assertFalse((output / 'rgb-export.json').exists())
            self.assertEqual(len(list((output / '.artifact-failures').glob('*.json'))), 1)


@unittest.skipUnless(importlib.util.find_spec('moderngl'), 'ModernGL is required for actual preview rendering')
class PreviewIntegrationTests(unittest.TestCase):
    def test_real_renderer_keeps_zero_alpha_fixed_rgb_visible_and_reports_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'model'
            model.mkdir()
            (model / 'assembly.obj').write_text('v -1 0 -1\nv 1 0 -1\nv 0 1 1\nvt 0 0\nvt 1 0\nvt .5 1\nusemtl hull\nf 1/1 2/2 3/3\n', encoding='utf-8')
            (model / 'materials.json').write_text(json.dumps({'materials': [{'obj_name': 'hull', 'texture_slots': ['body*']}]}), encoding='utf-8')
            color = root / 'color.dds'
            save_dds(Image.new('RGBA', (16, 16), (255, 196, 0, 0)), color)
            config = root / 'preview.json'
            config.write_text(json.dumps({'textures': {'body': {'color': 'color.dds'}}}), encoding='utf-8')
            profile = root / 'profile.json'
            profile.write_text(json.dumps({'texture_alpha_semantics': {'color': 'fixed_rgb', 'normal': 'packed_data', 'ao': 'scalar_data'}}), encoding='utf-8')
            output = root / 'out'
            command = [sys.executable, '-B', str(SCRIPTS / 'tank_preview.py'), '--model', str(model), '--config', str(config), '--profile', str(profile), '--out', str(output), '--views', 'iso', '--width', '128', '--height', '128']
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / 'preview-report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['texture_filtering'][0]['alpha_semantics'], 'fixed_rgb')
            self.assertEqual(report['texture_filtering'][0]['color_space'], 'srgb')
            self.assertFalse(report['missing_stock_preview_materials'])
            with Image.open(output / 'iso.png') as image:
                pixels = np.asarray(image).astype(np.int16)
            visible = (pixels[:, :, 0] > pixels[:, :, 2] + 20) & (pixels[:, :, 1] > pixels[:, :, 2] + 20)
            self.assertTrue(np.any(visible))
            linear_output = root / 'linear-out'
            config.write_text(json.dumps({'textures': {'body': {'color': 'color.dds', 'color_space': {'color': 'linear'}}}}), encoding='utf-8')
            linear_command = [str(linear_output) if argument == str(output) else argument for argument in command]
            linear = subprocess.run(linear_command, capture_output=True, text=True, timeout=90)
            self.assertEqual(linear.returncode, 0, linear.stdout + linear.stderr)
            with Image.open(linear_output / 'iso.png') as image:
                linear_pixels = np.asarray(image).astype(np.int16)
            self.assertGreater(linear_pixels[:, :, 1][visible].mean(), pixels[:, :, 1][visible].mean() + 1)
            linear_report = json.loads((linear_output / 'preview-report.json').read_text(encoding='utf-8'))
            self.assertEqual(linear_report['texture_filtering'][0]['color_space'], 'linear')
            before = hashlib.sha256((output / 'iso.png').read_bytes()).hexdigest()
            retry = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(hashlib.sha256((output / 'iso.png').read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
