import json
from pathlib import Path
import tempfile
import unittest

import design_lint

FONTS = Path('C:/Windows/Fonts')
CHART = dict(id='top', u='x', v='z')


def text(id_, value, height, **extra):
    return dict(id=id_, chart='top', text=value, height=height, center=[0, 0], **extra)


class DesignLintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def lint(self, design):
        path = self.root / f'd{len(list(self.root.glob("d*.json")))}.json'
        path.write_text(json.dumps(design), encoding='utf-8')
        result = design_lint.lint(path)
        return result, {h['code'] for h in result['hits']}

    def test_default_model_taste_is_caught(self):
        (self.root / 'a.png').write_bytes(b'same art')
        design = dict(schema_version=1, charts=[CHART], palette=dict(base='#000000', hi='#ffffff', cyan='#00ffff'), layers=[
            dict(name='fields', items=[
                dict(id='sunset', type='polygon', chart='top', points=[[0, 0], [2, 0], [2, 1]],
                     fill=dict(gradient={'from': [0, 0], 'to': [2, 0], 'colors': ['#2f6fd0', '#9b3fd0']})),
                dict(id='magenta-band', type='polygon', chart='top', points=[[0, 1], [2, 1], [2, 2]], fill='#ff00ff'),
                dict(id='gold-band', type='polygon', chart='top', points=[[0, 2], [2, 2], [2, 3]], fill='#e0a020'),
                dict(id='cyan-line', type='stroke', chart='top', points=[[0, 3], [3, 3]], width=.02, taper='both', fill='cyan')]),
            dict(name='lines', items=[
                dict(id='frame', type='stroke', chart='top', points=[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], width=.03, fill='hi'),
                dict(id='marker', type='stroke', chart='top', points=[[0, 5], [4, 5.3]], width=.12, fill='hi'),
                dict(id='glow-1', type='stroke', chart='top', points=[[0, 6], [4, 6]], width=.05, taper='both', fill='hi'),
                dict(id='glow-2', type='stroke', chart='top', points=[[0, 6], [4, 6]], width=.15, taper='both', fill='cyan')]),
            dict(name='art', images=[dict(id='wing-r', chart='top', source='a.png', width=4, center=[0, 0]),
                                     dict(id='wing-l', chart='top', source='a.png', width=4, center=[0, 0], flip=True)]),
            dict(name='type', images=[
                text('slogan', 'CYBER SQUADRON', .3, font=str(FONTS / 'impact.ttf')),
                text('sub', 'TACTICAL UNIT', .26, font=str(FONTS / 'arial.ttf')),
                text('cn-default', '陈千语', .3),
            ])])
        result, codes = self.lint(design)
        for code in ('pure-black', 'pure-white', 'neon-primary', 'several-vivid-hues', 'hue-shift-gradient', 'outline-frame',
                     'equal-width-band', 'stacked-strokes', 'repeated-art', 'filler-text', 'cjk-without-font', 'near-equal-sizes',
                     'caps-without-tracking'):
            self.assertIn(code, codes)
        if (FONTS / 'impact.ttf').is_file():
            self.assertIn('stock-font', codes)
        self.assertGreater(result['errors'], 0)
        self.assertEqual(len(result['text_inventory']), 3)

    @unittest.skipUnless((FONTS / 'bahnschrift.ttf').is_file(), 'needs Windows fonts')
    def test_missing_glyphs_are_errors(self):
        design = dict(schema_version=1, charts=[CHART], layers=[dict(name='type', images=[
            text('cn', '陈千语', .3, font=str(FONTS / 'bahnschrift.ttf'), color='#eeeeee')])])
        _, codes = self.lint(design)
        self.assertIn('missing-glyphs', codes)

    def test_absent_font_file_is_an_error(self):
        design = dict(schema_version=1, charts=[CHART], layers=[dict(name='type', images=[
            text('gone', 'CHEN', .3, font=str(FONTS / 'no-such-font-file.ttf'), color='#eeeeee')])])
        _, codes = self.lint(design)
        self.assertIn('font-not-found', codes)

    def test_thin_white_pinstripes_are_flagged(self):
        design = dict(schema_version=1, charts=[CHART], palette=dict(hi='#eef0f2', sig='#3f7fc0'), layers=[dict(name='lines', items=[
            dict(id='spine-needle', type='stroke', chart='top', points=[[0, 0], [6, 0]], width=.06, taper='both', fill='hi'),
            dict(id='le-sliver', type='polygon', chart='top', points=[[0, 1], [4, 1], [4, 1.035], [0, 1.035]], fill='hi'),
            dict(id='main-v-echo-1', type='stroke', chart='top', points=[[0, 2], [2, 2.5], [0, 3]], width=.03, fill='hi'),
            dict(id='blade', type='polygon', chart='top', points=[[0, 4], [1.6, 4.1], [0, 4.3]], fill='hi'),
            dict(id='sig-companion', type='stroke', chart='top', points=[[0, 5], [6, 5]], width=.03, taper='end', fill='sig')])])
        result, _ = self.lint(design)
        flagged = {h['where'] for h in result['hits'] if h['code'] == 'thin-white-line'}
        self.assertEqual(flagged, {'spine-needle', 'le-sliver'})

    def test_considered_design_is_quiet(self):
        design = dict(schema_version=1, charts=[CHART], palette=dict(base='#2c2e32', sig='#3f7fc0', sig_deep='#2f639a', hi='#eeeeee'), layers=[
            dict(name='fields', items=[
                dict(id='parent', type='polygon', chart='top', points=[[0, 0], [6, 0.4], [6, 0.9], [0, 0.6]],
                     fill=dict(pattern='tri-mosaic', cell=.2, jitter=.1, gradient={'from': [0, 0], 'to': [6, 0], 'colors': ['sig_deep', 'sig']})),
                dict(id='split', type='polygon', chart='top', points=[[1, 0.6], [5, 0.86], [5, 0.95], [1, 0.7]], fill='sig')]),
            dict(name='lines', items=[
                dict(id='lance', type='stroke', chart='top', points=[[0.5, 1.2], [5.5, 1.53]], width=.03, taper='both', fill='sig'),
                dict(id='white-wedge', type='polygon', chart='top', points=[[1, 1.6], [3.5, 1.76], [1, 1.95]], fill='hi'),
                dict(id='echo-1', type='stroke', chart='top', points=[[1, 2], [3, 2.13], [3, 2.4], [1, 2.27], [1, 2]], width=.03, fill='hi')]),
            dict(name='type', images=[
                text('name', 'CHEN QIANYU', .3, variation='Bold', tracking=.08, color='hi'),
                text('subline', 'ENDFIELD INDUSTRIES', .1, variation='Light', tracking=.25, color='hi')])])
        result, codes = self.lint(design)
        self.assertEqual(result['hits'], [], result['hits'])

    def test_outline_sequence_beside_solid_row_is_allowed(self):
        """F-2A fin: a row of solid parallelograms beside a row of 1 cm white outlines of the same shape."""
        solid = [dict(id=f'fin-solid-{i}', type='polygon', chart='top', points=[[i, 0], [i + .6, 0], [i + .9, .4], [i + .3, .4]], fill='sig')
                 for i in range(3)]
        outline = [dict(id=f'fin-sequence-{i}', type='stroke', chart='top', width=.009, fill='hi',
                        points=[[i, .6], [i + .6, .6], [i + .9, 1], [i + .3, 1], [i, .6]]) for i in range(3)]
        lone = dict(id='lone-frame', type='stroke', chart='top', width=.009, fill='hi', points=[[5, 0], [6, 0], [6, 1], [5, 1], [5, 0]])
        design = dict(schema_version=1, charts=[CHART], palette=dict(hi='#eef0f2', sig='#b7303c'),
                      layers=[dict(name='fin', items=solid + outline + [lone])])
        result, _ = self.lint(design)
        frames = {h['where'] for h in result['hits'] if h['code'] == 'outline-frame'}
        self.assertEqual(frames, {'lone-frame'})


if __name__ == '__main__':
    unittest.main()
