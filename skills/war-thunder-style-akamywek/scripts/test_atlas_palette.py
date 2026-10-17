from pathlib import Path
import json
import tempfile
import unittest

from PIL import Image, ImageDraw

import atlas_palette


class AtlasPaletteTests(unittest.TestCase):
    def test_matching_regions_across_resolutions_and_ignored_padding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, size in (('a', 256), ('b', 512)):
                image = Image.new('RGB', (size, size), (57, 207, 231))       # author padding
                draw = ImageDraw.Draw(image)
                draw.rectangle([0, 0, size // 2 - 1, size // 2 - 1], fill=(66, 67, 71))
                draw.rectangle([0, 0, size // 8 - 1, size // 2 - 1], fill=(255, 22, 99))
                image.save(root / f'{name}.png')
            atlas_palette.main(['--atlas', f'a={root / "a.png"}', '--atlas', f'b={root / "b.png"}',
                                '--region', 'top=0,0,0.5,0.5', '--region', 'all=0,0,1,1', '--ignore-color', '#39cfe7',
                                '--out', str(root / 'out')])
            data = json.loads((root / 'out/atlas-palette.json').read_text(encoding='utf-8'))
            for name in 'ab':
                top = data['atlases'][name]['regions']['top']
                self.assertAlmostEqual(top['vivid_share'], .25, places=2)
                self.assertAlmostEqual(top['quiet_base_share'], .75, places=2)
                self.assertEqual(top['hue_families_over_2pct'], ['rose'])
                # padding ignored, so the whole atlas reads like the painted quarter
                self.assertAlmostEqual(data['atlases'][name]['regions']['all']['vivid_share'], .25, places=2)
            self.assertTrue((root / 'out/atlas-palette.png').is_file())

    def test_families_split_neutrals_by_value(self):
        import numpy as np
        labels = atlas_palette.families(np.array([[20, 20, 22], [120, 120, 120], [235, 235, 230], [255, 22, 99], [60, 90, 106]]))
        self.assertEqual(list(labels[:4]), ['dark', 'mid', 'light', 'rose'])
        with self.assertRaises(ValueError):
            atlas_palette.parse_box('0.5,0,0.4,1')


if __name__ == '__main__':
    unittest.main()
