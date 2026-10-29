"""Actual A7HU regression plus independent pixel/channel boundary cases."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image

ROOT = (Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0, str(ROOT / 'scripts'))
from native_detail_probe import measure, probe, rgba
from production_tools import spec


class NativeDetailProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-detail-probe-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = np.array([[[120, 10, 15, 90], [30, 40, 50, 180]],
                           [[80, 90, 100, 190], [110, 120, 130, 220]]], dtype=np.uint8)
        self.mask = np.ones((2, 2), bool)

    def test_exact_retention(self):
        self.assertTrue(measure(self.a, self.a.copy(), self.mask, 'RGBA')['within_tolerance'])

    def test_anisotropic_uv_center_sampling(self):
        current = np.repeat(self.a, 2, axis=1)
        self.assertTrue(measure(self.a, current, self.mask, 'RGBA')['within_tolerance'])

    def test_one_changed_pixel_is_not_hidden_by_average(self):
        b = self.a.copy(); b[0, 1, 0] += 1
        report = measure(self.a, b, self.mask, 'R')
        self.assertEqual(report['outside_tolerance_pixels'], 1)
        self.assertFalse(report['within_tolerance'])
        self.assertTrue(measure(self.a, b, self.mask, 'R', 1)['within_tolerance'])

    def test_normal_GA_retention_does_not_prove_RB(self):
        b = self.a.copy(); b[..., 0] = 132; b[..., 2] = 144
        self.assertTrue(measure(self.a, b, self.mask, 'GA')['within_tolerance'])
        self.assertFalse(measure(self.a, b, self.mask, 'RB')['within_tolerance'])

    def test_empty_mask_and_invalid_channel_fail(self):
        for mask, channels in [(np.zeros((2, 2), bool), 'RGB'), (self.mask, 'RR'), (self.mask, 'X'), (self.mask, '')]:
            with self.assertRaises(ValueError): measure(self.a, self.a, mask, channels)

    def manifest(self, action='retain'):
        for name, array in [('reference', self.a), ('current', np.zeros_like(self.a))]:
            Image.fromarray(array).save(self.root / (name + '.png'))
        Image.fromarray(self.mask.astype(np.uint8) * 255).save(self.root / 'mask.png')
        return {'schema_version': 1, 'samples': [{'id': 'one', 'action': action,
                'mapping': 'same_normalized_uv_texel_centers', 'physical_location': 'synthetic fixture',
                'reference': spec(self.root / 'reference.png'), 'current': spec(self.root / 'current.png'),
                'mask': spec(self.root / 'mask.png'), 'channels': 'RGB'}]}

    def test_recolor_is_measurement_not_false_preservation(self):
        result = probe(self.root, self.manifest('recolor'))
        self.assertFalse(result['samples'][0]['within_tolerance'])
        self.assertEqual(result['samples'][0]['retention_claim'], 'not_asserted')
        self.assertEqual(result['retention_failures'], [])

    def test_stale_file_and_duplicate_id_fail(self):
        data = self.manifest()
        other = copy.deepcopy(data); other['samples'] *= 2
        with self.assertRaises(ValueError): probe(self.root, other)
        (self.root / 'current.png').write_bytes(b'changed')
        with self.assertRaises(ValueError): probe(self.root, data)

    def test_alpha_is_not_fabricated_from_RGB(self):
        path = self.root / 'rgb.png'; Image.new('RGB', (2, 2)).save(path)
        with self.assertRaises(ValueError): rgba(path, 'GA')

    def test_actual_A7HU_native_red_detail_lost(self):
        folder = Path(__file__).resolve().parent / 'fixtures/a7hu-native-round'
        with Image.open(folder / 'sample-mask.png') as im: mask = np.array(im) != 0
        report = measure(rgba(folder / 'native.png'), rgba(folder / 'current.png'), mask, 'RGB')
        self.assertEqual(report['sampled_reference_pixels'], 197)
        self.assertEqual(report['outside_tolerance_pixels'], 197)
        self.assertGreater(report['reference_mean_chroma'], 100)
        self.assertEqual(report['current_mean_chroma'], 0)

    def test_actual_A7HU_repair_restores_native_color(self):
        folder = Path(__file__).resolve().parent / 'fixtures/a7hu-native-round'
        with Image.open(folder / 'sample-mask.png') as im: mask = np.array(im) != 0
        report = measure(rgba(folder / 'native.png'), rgba(folder / 'repaired.png'), mask, 'RGB')
        self.assertEqual(report['sampled_reference_pixels'], 197)
        self.assertEqual(report['outside_tolerance_pixels'], 0)
        self.assertGreater(report['current_mean_chroma'], 100)
        self.assertTrue(np.all(rgba(folder / 'repaired.png')[..., 3] == 255))

    def test_actual_A7HU_repair_restores_material_and_normal_data(self):
        folder = Path(__file__).resolve().parent / 'fixtures/a7hu-native-round'
        with Image.open(folder / 'sample-mask.png') as im: mask = np.array(im) != 0
        native, repaired = rgba(folder / 'native-n.png'), rgba(folder / 'repaired-n.png')
        self.assertTrue(measure(native, repaired, mask, 'RGBA')['within_tolerance'])
        self.assertFalse(np.all(repaired[..., 0][mask] == 132))
        self.assertFalse(np.all(repaired[..., 2][mask] == 144))


if __name__ == '__main__':
    unittest.main()
