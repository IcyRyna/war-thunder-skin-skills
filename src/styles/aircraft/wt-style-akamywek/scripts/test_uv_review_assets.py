"""Critical UV orientation/material-domain and source-preservation checks."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from uv_review_assets import export, sha


class UVReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.geo = self.root / 'geometry.npz'
        self.base = self.root / 'base.png'
        Image.new('RGBA', (64, 64), (12, 30, 50, 47)).save(self.base)
        uv = np.asarray([[[0, 0], [.5, 0], [0, .5]], [[1, 1], [.7, 1], [1, .7]]], float)
        self.write_geometry(uv)

    def write_geometry(self, uv):
        np.savez_compressed(self.geo, uvs=uv, node_ids=np.array([0, 1]), names=np.array(['wing', 'glass']),
                            material_ids=np.array([0, 1]), material_names=np.array(['colour', 'glass']))

    def test_unit_orientation_and_material_domain(self):
        rec = export(self.geo, self.base, self.root / 'out', ['colour'])
        self.assertEqual(rec['selected_triangles'], 1)
        mask = Image.open(self.root / 'out/selected-carrier.png')
        self.assertEqual(mask.getpixel((2, 61)), 255)  # v=0 appears at the lower edge.
        self.assertEqual(mask.getpixel((61, 2)), 0)   # Other material must not contaminate the guide.
        with Image.open(self.root / 'out/UV_GUIDE_HIDE_FOR_EXPORT.png') as wire:
            self.assertEqual(wire.mode, 'RGBA')

    def test_original_colour_alpha_and_sources_preserved(self):
        before = [sha(self.geo), sha(self.base)]
        rec = export(self.geo, self.base, self.root / 'out', ['colour'])
        self.assertTrue(np.array_equal(np.asarray(Image.open(self.base)), np.asarray(Image.open(self.root / 'out/base-colour.png'))))
        self.assertEqual(before, [sha(self.geo), sha(self.base)])
        self.assertTrue(rec['source_files_unchanged'])

    def test_empty_domain_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            export(self.geo, self.base, self.root / 'out', ['missing'])

    def test_outside_unit_tile_is_reported_without_clamping_input(self):
        uv = np.asarray([[[0, 0], [1.2, 0], [0, .5]], [[1, 1], [.7, 1], [1, .7]]], float)
        self.write_geometry(uv)
        before = sha(self.geo)
        rec = export(self.geo, self.base, self.root / 'out', ['colour'])
        self.assertEqual(rec['out_of_tile_triangles'], [0])
        self.assertEqual(before, sha(self.geo))


if __name__ == '__main__':
    unittest.main()
