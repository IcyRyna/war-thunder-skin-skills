import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import surface_map


def quad(x0, x1, z0, z1, y, up, uv_box):
    """Two triangles of a horizontal plate at height y; up=True faces +Y."""
    u0, v0, u1, v1 = uv_box
    corners = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    order = ((0, 2, 1), (0, 3, 2)) if up else ((0, 1, 2), (0, 2, 3))
    return [[[corners[i][0], y, corners[i][1]] for i in tri] for tri in order], [[uvs[i] for i in tri] for tri in order]


class SurfaceMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        tris, uvs, nodes = [], [], []
        for (t, u), node in [
            (quad(-2, 2, -1, 1, 1.0, True, (.0, .0, .4, .4)), 0),     # outer top skin
            (quad(-2, 2, -1, 1, 0.2, True, (.5, .5, .9, .9)), 0),     # hidden inner face under it, own UV
            (quad(2, 4, -1, 1, 1.0, True, (.5, .0, .7, .2)), 0),      # top patch that shares UV with the belly
            (quad(2, 4, -1, 1, 0.0, False, (.5, .0, .7, .2)), 1),     # belly patch, same UV
        ]:
            tris += t; uvs += u; nodes += [node] * len(t)
        # A steep wall: XY plane at z = 1 (normal +Z), still selected by a top chart through 'nodes'.
        tris += [[[-2, 0, 1], [-2, 1, 1], [-1, 0, 1]]]; uvs += [[(.0, .5), (.0, .6), (.1, .5)]]; nodes += [0]
        np.savez(self.root / 'g.npz', triangles=np.asarray(tris, np.float32), uvs=np.asarray(uvs, np.float32),
                 node_ids=np.asarray(nodes, np.int32), names=np.asarray(['body', 'belly']))

    def tearDown(self):
        self.temp.cleanup()

    def run_map(self, charts, items):
        design = dict(schema_version=1, charts=charts, layers=[dict(name='lines', items=items)])
        (self.root / 'd.json').write_text(json.dumps(design), encoding='utf-8')
        out = self.root / f'out{len(list(self.root.glob("out*")))}'
        return surface_map.run(surface_map.argparse.Namespace(geometry=self.root / 'g.npz', design=self.root / 'd.json',
                                                              protect=None, chart=[], scale=20., threshold=.15, out=out)), out

    def test_hidden_inner_face_does_not_show_through_and_bleeding_fields_are_fine(self):
        charts = [dict(id='top', u='x', v='z', nodes=['body'], normal={'axis': 'y', 'min': .5}, facing='y')]
        items = [dict(id='field', type='polygon', chart='top', points=[[-2.1, -1.1], [1.5, -1.1], [1.5, 1.1], [-2.1, 1.1]], fill='#ffffff'),
                 dict(id='stray', type='stroke', chart='top', points=[[5, 0], [7, 0]], width=.1, fill='#ffffff')]
        report, out = self.run_map(charts, items)
        risky = {r['id'] for r in report['risky_items']}
        self.assertNotIn('field', risky)            # bleed past the edge is allowed for fields
        self.assertIn('stray', risky)               # a line off the surface is not
        self.assertTrue((out / 'top.png').is_file())

    def test_earlier_chart_wins_shared_texels(self):
        charts = [dict(id='belly', u='x', v='z', nodes=['belly'], normal={'axis': 'y', 'max': -.5}, facing='-y'),
                  dict(id='top', u='x', v='z', nodes=['body'], normal={'axis': 'y', 'min': .5}, facing='y')]
        items = [dict(id='on-shared-top', type='stroke', chart='top', points=[[2.2, 0], [3.8, 0]], width=.3, fill='#ffffff'),
                 dict(id='on-belly', type='stroke', chart='belly', points=[[2.2, 0], [3.8, 0]], width=.3, fill='#ffffff')]
        report, _ = self.run_map(charts, items)
        risky = {r['id']: r for r in report['risky_items']}
        self.assertIn('on-shared-top', risky)
        self.assertIn('lost-to-earlier-chart', risky['on-shared-top']['ground'])
        self.assertNotIn('on-belly', risky)

    def test_inner_face_under_other_geometry_is_hidden(self):
        # A lid of another node above part of the top skin hides it from a top chart.
        g = dict(__import__('numpy').load(self.root / 'g.npz'))
        lid_t, lid_u = quad(-2, 0, -1, 1, 1.5, True, (.0, .7, .2, .9))
        g['triangles'] = np.concatenate([g['triangles'], np.asarray(lid_t, np.float32)])
        g['uvs'] = np.concatenate([g['uvs'], np.asarray(lid_u, np.float32)])
        g['node_ids'] = np.concatenate([g['node_ids'], np.asarray([1, 1], np.int32)])
        np.savez(self.root / 'g.npz', **g)
        charts = [dict(id='top', u='x', v='z', nodes=['body'], normal={'axis': 'y', 'min': .5}, facing='y')]
        items = [dict(id='under-lid', type='stroke', chart='top', points=[[-1.8, 0], [-0.2, 0]], width=.2, fill='#ffffff'),
                 dict(id='open', type='stroke', chart='top', points=[[0.3, 0], [1.8, 0]], width=.2, fill='#ffffff')]
        report, _ = self.run_map(charts, items)
        risky = {r['id']: r for r in report['risky_items']}
        self.assertIn('hidden-under-other-surface', risky['under-lid']['ground'])
        self.assertNotIn('open', risky)

    def test_steep_faces_are_classed(self):
        charts = [dict(id='all', u='x', v='z', nodes=['body'])]
        report, _ = self.run_map(charts, [dict(id='f', type='polygon', chart='all', points=[[-2, -1], [2, -1], [2, 1]], fill='#ffffff')])
        self.assertGreater(report['charts']['all']['foreshortened_area_fraction'], 0)


if __name__ == '__main__':
    unittest.main()
