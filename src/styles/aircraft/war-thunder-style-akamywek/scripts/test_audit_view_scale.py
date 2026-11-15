import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import detail_sheet
import legacy_dds
import scene_preview as scene


class InspectionTests(unittest.TestCase):
    def test_fast_review_decode_preserves_every_channel_and_orientation(self):
        width, height = 37, 263
        rng = np.random.default_rng(832)
        pixels = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
        payload = pixels[:, :, [2, 1, 0, 3]].tobytes()
        raw = legacy_dds.header(width, height) + payload
        with Image.open(BytesIO(raw)) as conventional, legacy_dds.decode_review_image(BytesIO(raw)) as fast:
            np.testing.assert_array_equal(np.asarray(conventional), pixels)
            np.testing.assert_array_equal(np.asarray(fast), pixels)
        # Pillow still owns decoding for other DDS layouts and for ordinary art.
        stream = BytesIO()
        Image.fromarray(pixels).save(stream, 'PNG')
        self.assertIsNone(legacy_dds.decode_review_image(stream))
        self.assertEqual(stream.tell(), 0)
        self.assertIsNone(legacy_dds.decode_review_image(BytesIO(raw[:-4])))

    def test_final_dds_edges_match_atlas_and_editor_alpha(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pixels = np.zeros((48, 64, 4), np.uint8)
            pixels[:, 1::2] = [235, 225, 245, 201]
            pixels[:, ::2] = [51, 51, 52, 14]
            atlas, ref = root / 'main.dds', root / 'reference.dds'
            Image.fromarray(pixels).save(atlas)
            Image.fromarray(pixels[::-1, :, :]).save(ref)
            out = root / 'detail'
            detail_sheet.main(['--color', str(atlas), '--region', 'echo=10,6,24',
                               '--ref', str(ref), '--ref-region', 'echo=0,0,48',
                               '--px-per-m', '100', '--ref-px-per-m', '200', '--zoom', '1',
                               '--composa-copy', '--out', str(out)])
            with Image.open(out / 'crops/echo.png') as own:
                np.testing.assert_array_equal(own, pixels[6:22, 10:34, :3])
            with Image.open(out / 'ref-native/echo.png') as raw:
                np.testing.assert_array_equal(raw, pixels[:32, :48, :3])
            with Image.open(out / 'crops/echo-ref.png') as metric:
                self.assertEqual(metric.size, (24, 16))
            with Image.open(out / 'color.png') as editor:
                np.testing.assert_array_equal(editor, pixels)
            receipt = json.loads((out / 'regions.json').read_text())
            self.assertEqual(receipt['color_sha256'], hashlib.sha256(atlas.read_bytes()).hexdigest())
            self.assertTrue(receipt['metric_comparison'])

    def test_outside_atlas_cannot_create_padding_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            atlas = root / 'atlas.png'
            Image.new('RGB', (48, 48), 'white').save(atlas)
            for name, coords in [('left', '-4,0,48'), ('right', '4,0,48'),
                                 ('bottom', '0,18,48')]:
                out = root / name
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'outside texture'):
                    detail_sheet.main(['--color', str(atlas), '--region', 'edge=' + coords, '--out', str(out)])
                self.assertFalse(out.exists())

    def test_auto_can_inspect_a_region_that_touches_both_limits(self):
        image = Image.new('RGB', (19, 12), 'white')
        self.assertEqual(detail_sheet.auto_regions(image, 1, 19), [('auto-1', (0, 0, 19))])

    def test_four_model_metres_cover_400_rendered_pixels_obliquely(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a, b, c, d = [-2, -.25, 0], [2, -.25, 0], [2, .25, 0], [-2, .25, 0]
            geo = root / 'quad.npz'
            np.savez_compressed(geo, triangles=np.array([[a, b, c], [a, c, d]], np.float32),
                                uvs=np.array([[[0, 0], [1, 0], [1, 1]], [[0, 0], [1, 1], [0, 1]]], np.float32),
                                names=np.array(['test-panel']), node_ids=np.zeros(2, np.int32),
                                material_names=np.array(['paint']), material_ids=np.zeros(2, np.int32),
                                material_resources=np.array(['[]']))
            ruler = dict(start_world_m=[-2, 0, 0], end_world_m=[2, 0, 0], target_px_per_m=100)
            camera = dict(eye=[.6, 0, .8], up=[0, 1, 0], target_world=[0, 0, 0], meter_ruler=ruler)
            manifest = dict(schema_version=1, geometry=dict(path=geo.name, sha256=scene.file_hash(geo)),
                            width=600, height=180, display_state=dict(description='metric sample'),
                            materials=[dict(id=0, name='paint', base_color=[1, 1, 1, 1], double_sided=True)],
                            cameras=dict(check=camera))
            path = root / 'scene.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            receipt = scene.render(path, 'check', 'layout', root / 'view.png')
            with Image.open(root / 'view-mask.png') as mask:
                self.assertEqual(np.count_nonzero(np.asarray(mask)[90]), 400)
            measured = receipt['ruler_measurement']
            self.assertTrue(measured['endpoints_in_frame'])
            self.assertAlmostEqual(measured['length_px'], 400)
            self.assertAlmostEqual(measured['px_per_m'], 100)
            self.assertAlmostEqual(receipt['scale'], 125, places=4)
            # Reuse a frozen camera to measure an existing render without changing its framing.
            fixed = {k: receipt[k] for k in ('basis', 'scale', 'center', 'width', 'height')}
            fixed['meter_ruler'] = dict(start_world_m=ruler['start_world_m'], end_world_m=ruler['end_world_m'])
            measured_path = root / 'measure-only.json'
            measured_path.write_text(json.dumps(fixed), encoding='utf-8')
            existing = scene.render(path, 'check', 'layout', root / 'measured.png', measured_path)
            self.assertEqual(existing['image_sha256'], receipt['image_sha256'])
            self.assertEqual(existing['camera_sha256'], receipt['camera_sha256'])
            self.assertAlmostEqual(existing['ruler_measurement']['length_px'], 400)

    def test_conflicting_zoom_and_parallel_segment_are_rejected(self):
        meta = dict(basis=np.eye(3).tolist(), center=[0., 0.], scale=20., width=128, height=128)
        ruler = dict(start_world_m=[0, 0, 0], end_world_m=[0, 0, 2], target_px_per_m=100)
        with self.assertRaisesRegex(ValueError, 'zoom'):
            scene.measure_ruler(dict(zoom=2, meter_ruler=ruler), meta)
        with self.assertRaisesRegex(ValueError, 'segment'):
            scene.measure_ruler(dict(meter_ruler=ruler), meta)
        ruler.pop('target_px_per_m')
        ruler['end_world_m'] = [10, 0, 0]
        scene.measure_ruler(dict(meter_ruler=ruler), meta)
        self.assertFalse(meta['ruler_measurement']['endpoints_in_frame'])


if __name__ == '__main__':
    unittest.main()
