from pathlib import Path
import json
import tempfile
import unittest

from PIL import Image, ImageDraw

import style_board


def render(path, fields):
    image = Image.new('RGB', (400, 300), (238, 238, 238))
    draw = ImageDraw.Draw(image)
    draw.polygon([(40, 150), (360, 110), (360, 190)], fill=(66, 67, 71))
    for box, color in fields:
        draw.rectangle(box, fill=color)
    image.save(path)


class StyleBoardTests(unittest.TestCase):
    def test_board_measures_value_and_signature_area_on_airframe_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            render(root / 'plain.png', [])
            render(root / 'signature.png', [((200, 130, 300, 170), (255, 22, 99))])
            style_board.main(['--candidate', str(root / 'plain.png'), '--reference', str(root / 'signature.png'),
                              '--size', '320', '--out', str(root / 'board')])
            data = json.loads((root / 'board/style-board.json').read_text(encoding='utf-8'))
            plain, signature = data['images']
            self.assertTrue(plain['flat_background_detected'])
            self.assertEqual(plain['saturated_share'], 0)
            self.assertGreater(signature['saturated_share'], .2)
            self.assertEqual(signature['saturated_hue_families'], 1)
            self.assertGreater(plain['mid_share'], .9)
            self.assertTrue((root / 'board/style-board.png').is_file())
            with self.assertRaises(Exception):
                style_board.main(['--candidate', str(root / 'plain.png'), '--reference', str(root / 'signature.png'), '--out', str(root / 'board')])

    def test_scene_background_is_flagged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            noise = Image.effect_noise((300, 200), 90).convert('RGB')
            noise.save(root / 'scene.png')
            render(root / 'plain.png', [])
            style_board.main(['--candidate', str(root / 'plain.png'), '--reference', str(root / 'scene.png'), '--out', str(root / 'b')])
            data = json.loads((root / 'b/style-board.json').read_text(encoding='utf-8'))
            self.assertFalse(data['images'][1]['flat_background_detected'])


if __name__ == '__main__':
    unittest.main()
