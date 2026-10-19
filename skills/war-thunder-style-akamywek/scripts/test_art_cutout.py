import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import art_cutout


class ArtCutoutTests(unittest.TestCase):
    def test_enclosed_backdrop_is_removed_and_the_rim_is_unmixed(self):
        rgb = np.full((200, 200, 3), 127., np.float32)
        rgb[40:160, 40:160] = (200, 30, 40)            # the figure: a red ring ...
        rgb[80:120, 80:120] = 127.                      # ... enclosing backdrop (an arm's gap)
        rgb[95:105, 39] = (127 + 0.5 * (200 - 127), 127 + 0.5 * (30 - 127), 127 + 0.5 * (40 - 127))   # half-covered edge pixels
        rgb[60:63, 60:63] = (120, 120, 118)             # a small grey detail inside the figure stays
        out, bg, stats = art_cutout.cutout(rgb, min_area=200)
        self.assertEqual(int(out[10, 10, 3]), 0)
        self.assertEqual(int(out[100, 100, 3]), 0)      # enclosed backdrop removed
        self.assertEqual(int(out[50, 50, 3]), 255)
        self.assertGreater(int(out[61, 61, 3]), 0)      # small grey detail kept
        rim = out[100, 39]
        self.assertAlmostEqual(int(rim[3]), 128, delta=8)    # half covered, not opaque
        self.assertAlmostEqual(int(rim[0]), 200, delta=12)   # un-mixed colour, no grey fringe
        self.assertAlmostEqual(int(rim[1]), 30, delta=12)

    def test_cli_writes_cutout_sheet_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); rgb = np.full((60, 60, 3), 128, np.uint8); rgb[20:40, 20:40] = (10, 200, 30)
            Image.fromarray(rgb).save(d / 'src.png')
            art_cutout.main(['--src', str(d / 'src.png'), '--out', str(d / 'cut.png'), '--min-area', '50'])
            self.assertTrue((d / 'cut.png').is_file() and (d / 'cut-on-coat.png').is_file() and (d / 'cut.json').is_file())


if __name__ == '__main__':
    unittest.main()
