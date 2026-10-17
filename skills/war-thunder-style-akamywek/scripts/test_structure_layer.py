from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from PIL import Image

import structure_layer


class StructureLayerTests(unittest.TestCase):
    def test_grooves_kept_broad_shading_and_color_grime_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            normal = np.full((256, 256, 4), 128, np.uint8)
            ramp = np.linspace(100, 156, 256).astype(np.uint8)
            normal[:, :, 1] = ramp[None, :]                  # broad shading in G
            normal[:, 120, 3], normal[:, 122, 3] = 90, 166   # one groove as paired edges in A
            normal[60, 60, 1] = 40                           # one rivet
            Image.fromarray(normal, 'RGBA').save(root / 'n.png')
            color = np.full((256, 256, 3), 120, np.uint8); color[180:220, 180:220] = 40   # grime blob
            Image.fromarray(color).save(root / 'c.png')
            structure_layer.main(['--normal', str(root / 'n.png'), '--color', str(root / 'c.png'), '--size', '512', '--out', str(root / 'o')])
            alpha = np.asarray(Image.open(root / 'o/structure.png'))[:, :, 3].astype(int)
            self.assertEqual(alpha.shape, (512, 512))
            self.assertGreater(alpha[:, 240:246].mean(), 60)      # groove survives (scaled x2)
            self.assertLess(alpha[:, 20:200].mean(), 3)          # ramp ignored
            self.assertGreater(alpha[116:124, 116:124].max(), 60)   # rivet
            self.assertLess(alpha[380:420, 380:420].mean(), 3)   # grime ignored at color weight 0
            self.assertLessEqual(alpha.max(), round(.55 * 255) + 1)
            receipt = json.loads((root / 'o/receipt.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['color_weight'], 0)
            with self.assertRaises(ValueError):
                structure_layer.main(['--normal', str(root / 'n.png'), '--channels', 'gx', '--out', str(root / 'p')])


if __name__ == '__main__':
    unittest.main()
