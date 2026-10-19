import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

import panel_lines


def template(path):
    """Grey skin with one panel outline, a rivet row, a light marking and a soft stain."""
    im = Image.new('RGB', (256, 256), (170, 175, 178))
    d = ImageDraw.Draw(im)
    d.rectangle((40, 40, 200, 120), outline=(120, 124, 126), width=1)       # panel outline
    for x in range(50, 190, 6):                                             # rivet row
        d.point((x, 150), fill=(118, 120, 122))
    d.rectangle((60, 180, 140, 230), fill=(235, 236, 236))                  # light marking: its edges are not lines
    im.save(path)


class PanelLineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        template(self.root / 't.png')

    def tearDown(self):
        self.temp.cleanup()

    def trace(self, **extra):
        args = panel_lines.argparse.Namespace(color=self.root / 't.png', protect=None, threshold=6, max_fill=.55, max_rivet=6,
                                             min_length=18, tolerance=1.0, min_segment=3.0, join_gap=8, rivet_spacing=7,
                                             out=self.root / 'trace', **extra)
        panel_lines.trace(args)
        return json.loads((self.root / 'trace/lines.json').read_text(encoding='utf-8'))

    def test_trace_keeps_the_panel_outline_and_rivet_row_but_not_marking_edges(self):
        data = self.trace()
        pts = np.array([p for line in data['lines'] for p in line]) * 256
        self.assertTrue(len(data['lines']) >= 1)
        near_panel = (np.abs(pts[:, 0] - 40) < 2) | (np.abs(pts[:, 0] - 200) < 2) | (np.abs(pts[:, 1] - 40) < 2) | (np.abs(pts[:, 1] - 120) < 2)
        self.assertTrue(near_panel.all(), 'every traced vertex lies on the panel outline')
        rivets = np.array(data['rivets']) * 256
        self.assertGreater(len(rivets), 15)
        self.assertTrue((np.abs(rivets[:, 1] - 150.5) < 1.5).all())
        self.assertTrue((self.root / 'trace/trace-preview.png').is_file())

    def test_apply_lightens_dark_coat_darkens_light_paint_and_skips_excluded_texels(self):
        data = self.trace()
        paint = np.zeros((512, 512, 4), np.uint8)
        paint[..., 3] = 255
        paint[:, :256, :3] = 46          # dark coat on the left half
        paint[:, 256:, :3] = 180         # light paint on the right half
        Image.fromarray(paint, 'RGBA').save(self.root / 'c.png')
        art = np.zeros((512, 512, 4), np.uint8)
        art[230:250, :, 3] = 255          # an art layer over the panel's bottom edge row (y=120 of 256 -> 240)
        Image.fromarray(art, 'RGBA').save(self.root / 'art.png')
        args = panel_lines.argparse.Namespace(lines=self.root / 'trace/lines.json', color=self.root / 'c.png', exclude=[str(self.root / 'art.png')],
                                             protect=None, width=8.0, rivet_size=8.0, rivet_strength=.6, on_dark='light', dark_below=60,
                                             light_shift=30, dark_shift=24, accept_failed_trace=False, out=self.root / 'apply')
        panel_lines.apply(args)
        out = np.asarray(Image.open(self.root / 'apply/color.png').convert('RGB')).astype(int)
        self.assertGreater(out[80, 150, 0], 46 + 10)        # top edge (y=40 -> 80) over the dark coat: lighter
        self.assertLess(out[80, 350, 0], 180 - 10)          # same edge over light paint: darker
        self.assertEqual(out[240, 150, 0], 46)              # under the art layer: untouched
        self.assertEqual(out[400, 100, 0], 46)              # away from any line: untouched


    def test_trace_records_quality_and_apply_refuses_a_failed_trace(self):
        data = self.trace()
        self.assertTrue(data['quality']['passed'], data['quality'])     # one long clean panel outline
        stubs = Image.new('RGB', (1024, 1024), (170, 175, 178))
        d = ImageDraw.Draw(stubs)
        for i in range(24):                                             # short broken dashes (~70 px at 8192), like a weathered template
            x, y = 40 + (i % 6) * 150, 60 + (i // 6) * 200
            d.line((x, y, x + 8, y + 3), fill=(120, 124, 126), width=1)
        stubs.save(self.root / 's.png')
        args = panel_lines.argparse.Namespace(color=self.root / 's.png', protect=None, threshold=6, max_fill=.55, max_rivet=6,
                                             min_length=6, tolerance=1.0, min_segment=3.0, join_gap=8, rivet_spacing=7,
                                             out=self.root / 'trace-stubs')
        panel_lines.trace(args)
        bad = json.loads((self.root / 'trace-stubs/lines.json').read_text(encoding='utf-8'))
        self.assertFalse(bad['quality']['passed'], bad['quality'])
        Image.new('RGBA', (512, 512), (46, 46, 48, 255)).save(self.root / 'c2.png')
        apply = dict(lines=self.root / 'trace-stubs/lines.json', color=self.root / 'c2.png', exclude=[], protect=None, width=2.0,
                     rivet_size=2.5, rivet_strength=.6, on_dark='light', dark_below=60, light_shift=30, dark_shift=24)
        with self.assertRaises(ValueError):
            panel_lines.apply(panel_lines.argparse.Namespace(**apply, accept_failed_trace=False, out=self.root / 'a1'))
        receipt = panel_lines.apply(panel_lines.argparse.Namespace(**apply, accept_failed_trace=True, out=self.root / 'a2'))
        self.assertTrue(receipt['accepted_failed_trace'])


if __name__ == '__main__':
    unittest.main()
