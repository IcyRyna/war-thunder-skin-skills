import unittest

import arrangement


def area(poly):
    return arrangement.area([tuple(p) for p in poly])


class ArrangementTests(unittest.TestCase):
    def test_lines_cut_cells_that_share_edges_and_mirror(self):
        spec = {'chart': 'c', 'mirror': 'y', 'clip': [-1, 1, -1, 1],
                'lines': [{'id': 'slant', 'deg': 20, 'apex': 0.5}, {'id': 'cut', 'deg': 0, 'at': 0.3}],
                'fills': [{'id': 'a', 'seed': [0.0, 0.6], 'fill': 'w'}, {'id': 'b', 'seed': [0.0, 0.1], 'fill': 'w'}]}
        items = arrangement.build(spec)
        self.assertEqual([i['id'] for i in items], ['a', 'b', 'a~', 'b~'])
        a, b, am = items[0]['points'], items[1]['points'], items[2]['points']
        # mirrored cell has the same area and opposite y
        self.assertAlmostEqual(area(a), area(am), places=9)
        self.assertTrue(all(y < 0 for _, y in am))
        # neighbours across the cut share the cut edge: both have vertices on y = 0.3
        self.assertTrue(any(abs(y - .3) < 1e-9 for _, y in a) and any(abs(y - .3) < 1e-9 for _, y in b))

    def test_outline_is_the_cell_minus_an_inset_copy(self):
        spec = {'chart': 'c', 'clip': [0, 2, 0, 1], 'lines': [{'id': 'v', 'deg': 90, 'through': [1, 0]}],
                'fills': [{'id': 'o', 'seed': [0.5, 0.5], 'fill': 'w', 'outline': 0.1}]}
        (item,) = arrangement.build(spec)
        self.assertAlmostEqual(area(item['points']), 1.0, places=9)
        self.assertAlmostEqual(area(item['holes'][0]), 0.8 * 0.8, places=9)

    def test_using_limits_the_cutting_lines(self):
        spec = {'chart': 'c', 'clip': [0, 2, 0, 1],
                'lines': [{'id': 'v', 'deg': 90, 'through': [1, 0]}, {'id': 'h', 'deg': 0, 'at': 0.5}],
                'fills': [{'id': 'all', 'seed': [0.5, 0.25], 'fill': 'w'},
                          {'id': 'only_v', 'seed': [0.5, 0.25], 'fill': 'w', 'using': ['v']}]}
        cut, whole = arrangement.build(spec)
        self.assertAlmostEqual(area(cut['points']), 0.5, places=9)
        self.assertAlmostEqual(area(whole['points']), 1.0, places=9)

    def test_bad_specs_are_rejected(self):
        with self.assertRaises(ValueError):
            arrangement.build({'chart': 'c', 'clip': [0, 1, 0, 1], 'lines': [{'id': 'h', 'deg': 0, 'at': 0.5}],
                               'fills': [{'id': 'x', 'seed': [0.5, 0.5], 'fill': 'w'}]})          # seed on a line
        with self.assertRaises(ValueError):
            arrangement.build({'chart': 'c', 'clip': [0, 1, 0, 1], 'lines': [{'id': 'h', 'deg': 10, 'at': 0.5}],
                               'fills': []})                                                   # "at" needs deg 0
        with self.assertRaises(ValueError):
            arrangement.build({'chart': 'c', 'clip': [0, 1, 0, 1], 'lines': [{'id': 'h', 'deg': 0, 'at': 0.5}],
                               'fills': [{'id': 'x', 'seed': [0.5, 0.2], 'fill': 'w', 'using': ['nope']}]})


if __name__ == '__main__':
    unittest.main()
