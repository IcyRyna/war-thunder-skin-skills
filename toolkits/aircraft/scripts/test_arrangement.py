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

    def test_separate_halves_are_exact_mirrors_when_lines_do_not_pass_y0(self):
        # a slant "through" a point off the axis: its mirror crosses into the upper half aft of x = -0.52
        spec = {'chart': 'c', 'mirror': 'y', 'clip': [-2, 2, -1, 1],
                'lines': [{'id': 's', 'deg': 30, 'through': [0.0, 0.3]}, {'id': 'e', 'deg': 0, 'at': 0.1}],
                'fills': [{'id': 'w', 'seed': [-1.8, 0.5], 'fill': 'w'}]}
        shared = arrangement.build(spec)
        apart = arrangement.build(dict(spec, halves='separate'))
        mirror = lambda poly: sorted((round(x, 9), round(-y, 9)) for x, y in poly)
        plain = lambda poly: sorted((round(x, 9), round(y, 9)) for x, y in poly)
        self.assertEqual(plain(apart[0]['points']), mirror(apart[1]['points']))
        # with every line cutting every cell, the mirror line chops the seed's cell, so one seed fills only part of
        # the intended shape (J-10C v5: white pieces went missing); separately, the cell is whole
        self.assertGreater(area(apart[0]['points']), area(shared[0]['points']) + 0.3)

    def test_region_minus_cuts_leaves_pieces_that_share_the_cut_lines(self):
        import math
        # a white strip 0.1 < y < 0.5 between x = 0 and 4, cut by two 12 deg bands 0.09 wide lying inside it
        spec = {'chart': 'c', 'mirror': 'y', 'clip': [-1, 5, -1, 1], 'cut_fill': 'white',
                'region': [{'line': {'deg': 0, 'at': 0.1}, 'keep': [1, 0.3]}, {'line': {'deg': 0, 'at': 0.5}, 'keep': [1, 0.3]},
                           {'line': {'deg': 90, 'through': [0, 0]}, 'keep': [1, 0.3]}, {'line': {'deg': 90, 'through': [4, 0]}, 'keep': [1, 0.3]}],
                'cuts': [{'deg': 12, 'through': [x, 0.1], 'toward': [x + 0.5, 0.1], 'width': 0.09} for x in (0.5, 1.5)]}
        items = arrangement.build(spec)
        upper = [i for i in items if not i['id'].endswith('~')]
        lower = [i for i in items if i['id'].endswith('~')]
        self.assertEqual(len(upper), len(lower))
        self.assertGreaterEqual(len(upper), 3)
        # the white area is the strip minus the two bands (each band crosses the 0.4 m strip over 0.4 / sin 12)
        removed = 2 * 0.09 / math.sin(math.radians(12)) * 0.4
        self.assertAlmostEqual(sum(area(i['points']) for i in upper), 4 * 0.4 - removed, delta=0.01)

        def inside(poly, p):
            c = False
            for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
                if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0):
                    c = not c
            return c
        t = math.tan(math.radians(12))
        for x in (0.5, 1.5):
            mid = (x + 0.3 / t + 0.045 / math.sin(math.radians(12)), 0.4)    # centre of the band at y = 0.4
            self.assertFalse(any(inside(i['points'], mid) for i in upper))

    def test_a_horizontal_line_given_by_through_is_mirrored(self):
        spec = {'chart': 'c', 'mirror': 'y', 'clip': [0, 1, -1, 1],
                'lines': [{'id': 'h', 'deg': 0, 'through': [0.5, 0.4]}],
                'fills': [{'id': 'top', 'seed': [0.5, 0.7], 'fill': 'w'}]}
        top, bottom = arrangement.build(spec)
        self.assertAlmostEqual(area(top['points']), 0.6, places=9)
        self.assertAlmostEqual(area(bottom['points']), 0.6, places=9)     # unmirrored, the lower cell was 1.4

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
