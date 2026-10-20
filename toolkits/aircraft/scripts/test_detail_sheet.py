import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

import detail_sheet


class DetailSheetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        ours = Image.new('RGB', (512, 512), (46, 46, 48))
        d = ImageDraw.Draw(ours)
        d.line((300, 60, 480, 120), fill=(240, 240, 240), width=2)       # the only detail: auto must find it
        ours.save(self.root / 'ours.png')
        ref = Image.new('RGB', (1024, 1024), (51, 51, 52))
        ImageDraw.Draw(ref).rectangle((100, 100, 140, 160), fill=(183, 48, 60))
        ref.save(self.root / 'ref.png')

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, *extra):
        detail_sheet.main(['--color', str(self.root / 'ours.png'), '--out', str(self.root / 'out'), *extra])
        return json.loads((self.root / 'out/regions.json').read_text(encoding='utf-8'))

    def test_crops_are_nearest_neighbour_enlargements_of_the_full_size_map(self):
        receipt = self.run_tool('--region', 'edge=290,50,48', '--zoom', '3')
        crop = np.asarray(Image.open(self.root / 'out/crops/edge.png'))
        self.assertEqual(crop.shape[:2], (32 * 3, 48 * 3))
        self.assertEqual(len(np.unique(crop.reshape(-1, 3), axis=0)) <= 3 + 2, True)   # no new blended colours from resampling
        self.assertEqual(receipt['regions'][0]['box'], dict(x=290, y=50, width=48, height=32))
        calls = json.loads((self.root / 'out/composa-calls.json').read_text(encoding='utf-8'))
        self.assertEqual(calls[0]['name'], 'open_document')
        self.assertEqual(calls[1]['arguments'], dict(x=290, y=50, width=48, height=32, maxSide=48))

    def test_auto_finds_detail_and_reference_matches_metric_scale(self):
        receipt = self.run_tool('--auto', '1', '--auto-width', '64', '--px-per-m', '250', '--ref', f'F2A={self.root / "ref.png"}',
                                '--ref-px-per-m', '500', '--region', 'field=0,0,64', '--ref-region', 'field=80,80,128')
        auto = next(r for r in receipt['regions'] if r['name'] == 'auto-1')
        self.assertTrue(250 <= auto['box']['x'] <= 480 and auto['box']['y'] <= 130, auto)
        ref = Image.open(self.root / 'out/crops/field-ref.png')
        self.assertEqual(ref.size, (64 * 2, 42 * 2))     # 128 px at 500 px/m shown at our 250 px/m, then x2
        self.assertTrue((self.root / 'out/sheet.png').is_file())

    def test_reference_region_without_matching_region_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_tool('--region', 'a=0,0,32', '--ref', str(self.root / 'ref.png'), '--ref-region', 'b=0,0,32')


if __name__ == '__main__':
    unittest.main()
