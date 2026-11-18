from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from PIL import Image

import coat_material


class CoatMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        n = np.zeros((64, 64, 4), np.uint8)
        n[:, :, 0] = np.linspace(40, 140, 64).astype(np.uint8)[None, :]   # worn, varied roughness
        n[:, :, 1], n[:, :, 2], n[:, :, 3] = 125, 200, 127
        n[:, 30, 1], n[:, 31, 3] = 85, 167                                  # one groove
        self.original = n
        Image.fromarray(n, 'RGBA').save(self.root / 'n.png')

    def tearDown(self):
        self.temp.cleanup()

    def load(self, name):
        return np.asarray(Image.open(self.root / name / 'material.png').convert('RGBA'))

    def test_default_is_one_flat_glossy_coat(self):
        coat_material.main(['--normal', str(self.root / 'n.png'), '--out', str(self.root / 'o')])
        m = self.load('o')
        self.assertTrue((m[:, :, 0] == 173).all())
        self.assertTrue((m[:, :, 2] == 0).all())
        self.assertTrue((m[:, :, 1] == 125).all() and (m[:, :, 3] == 127).all())   # groove flattened
        receipt = json.loads((self.root / 'o/receipt.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['coat']['flat_G'], 125)
        r = np.asarray(Image.open(self.root / 'o/material_R.png'))
        self.assertEqual(r.shape, (64, 64))

    def test_structure_share_and_protect(self):
        mask = np.zeros((32, 32), np.uint8); mask[:, :8] = 255                 # left quarter after resize
        Image.fromarray(mask).save(self.root / 'p.png')
        coat_material.main(['--normal', str(self.root / 'n.png'), '--r', '228', '--b', '56', '--structure', '.25',
                            '--protect', str(self.root / 'p.png'), '--out', str(self.root / 'o')])
        m = self.load('o')
        self.assertEqual(int(m[5, 31, 3]), 137)                                 # 127 + 0.25 * 40
        self.assertEqual(int(m[5, 30, 1]), 115)                                 # 125 - 0.25 * 40
        self.assertTrue((m[:, :16] == self.original[:, :16]).all())             # protected texels untouched
        self.assertTrue((m[:, 16:, 0] == 228).all() and (m[:, 16:, 2] == 56).all())

    def test_metallic_satin_preset_and_flat_detail(self):
        detail = self.root / 'detail_lo_n.png'
        coat_material.main(['--normal', str(self.root / 'n.png'), '--preset', 'metallic-satin',
                            '--flat-detail-out', str(detail), '--out', str(self.root / 'o')])
        m = self.load('o')
        self.assertTrue((m[:, :, 0] == 163).all())
        self.assertTrue((m[:, :, 2] == 188).all())
        self.assertTrue((m[:, :, 1] == 128).all() and (m[:, :, 3] == 128).all())
        d = np.asarray(Image.open(detail).convert('RGBA'))
        self.assertEqual(d.shape, (512, 512, 4))
        self.assertTrue((d == np.array([198, 128, 255, 128], np.uint8)).all())

    def test_exhaust_3stage_finish(self):
        color = np.full((12, 12, 4), (160, 150, 140, 255), np.uint8)
        packed = np.full((6, 6, 4), (120, 125, 165, 131), np.uint8)
        cm_s = np.zeros((12, 12), bool); cm_s[:4, :] = True
        cm_o = np.zeros((12, 12), bool); cm_o[4:8, :] = True
        cm_i = np.zeros((12, 12), bool); cm_i[8:, :] = True
        nm_s = np.zeros((6, 6), bool); nm_s[:2, :] = True
        nm_o = np.zeros((6, 6), bool); nm_o[2:4, :] = True
        nm_i = np.zeros((6, 6), bool); nm_i[4:, :] = True
        coat_material.apply_exhaust_finish(color, packed, cm_s, cm_o, cm_i, nm_s, nm_o, nm_i)
        self.assertLess(int(color[0, 0, 0]), 80)   # dark gunmetal shroud, not bright 160 silver
        self.assertEqual((int(packed[0, 0, 0]), int(packed[0, 0, 2])), (150, 224))
        self.assertEqual((int(packed[2, 0, 0]), int(packed[2, 0, 2])), (138, 240))
        self.assertEqual((int(packed[4, 0, 0]), int(packed[4, 0, 2])), (86, 36))
        self.assertTrue((packed[:, :, 1] == 125).all() and (packed[:, :, 3] == 131).all())

    def test_refuses_bad_input(self):
        with self.assertRaises(ValueError):
            coat_material.main(['--normal', str(self.root / 'n.png'), '--structure', '1.5', '--out', str(self.root / 'o')])
        (self.root / 'full').mkdir(); (self.root / 'full/x').write_text('x')
        with self.assertRaises(Exception):
            coat_material.main(['--normal', str(self.root / 'n.png'), '--out', str(self.root / 'full')])


if __name__ == '__main__':
    unittest.main()
