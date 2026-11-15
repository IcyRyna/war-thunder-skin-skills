"""A model-derived marking must keep the nose, fin direction, holes and separate components."""
import unittest

import numpy as np

from aircraft_markings import direction, place_outline, project_outline, select_nodes


def rectangle(x0, y0, x1, y1):
    a, b, c, d = ([x0,y0,0], [x1,y0,0], [x1,y1,0], [x0,y1,0])
    return [a,b,c], [a,c,d]


class MarkingTests(unittest.TestCase):
    def test_rings_and_detached_shape_survive_signed_projection(self):
        # An open window, a raised fin at the tail and a detached marker at the nose.
        tris = [*rectangle(-3,-1,2,-.7),*rectangle(-3,.7,2,1),
                *rectangle(-3,-.7,-2.6,.7),*rectangle(1.6,-.7,2,.7),
                *rectangle(-3,1,-2.6,2),*rectangle(2.4,-.15,2.8,.15)]
        image, view = project_outline(np.array(tris,float),direction('x'),direction('y'),256,.5)
        self.assertEqual(len(view['parts']),2)
        self.assertEqual(len(view['parts'][0]['holes']),1)
        extreme = max(view['parts'][0]['points'],key=lambda p:p[1])
        self.assertLess(extreme[0],-.3)
        self.assertEqual(image.getchannel('A').getpixel((128,65)),0)
        items = place_outline(view,chart='spine',prefix='left',center=(3,5),
                              nose=(1,0),upper=(0,-1),length=2,fill='white')
        self.assertEqual(len(items[0]['holes']),1)
        self.assertEqual([i['id'] for i in items],['left-1','left-2'])
        pts = np.concatenate([np.asarray(i['points']) for i in items])
        self.assertAlmostEqual(np.ptp(pts[:,0]),2,places=5)
        np.testing.assert_allclose(items[0]['points'][0], [3+2*view['parts'][0]['points'][0][0],5-2*view['parts'][0]['points'][0][1]],atol=1e-6)
        inverted, _ = project_outline(np.array(tris,float),direction('-x'),direction('y'),256,.5)
        np.testing.assert_array_equal(np.asarray(image.getchannel('A'))[:,::-1],np.asarray(inverted.getchannel('A')))

    def test_select_real_nodes_rejects_missing_patterns(self):
        g={'triangles':np.zeros((2,3,3)), 'names':np.array(['fuse','wing','unused']), 'node_ids':np.array([0,1])}
        faces,nodes=select_nodes(g,['wi*'])
        self.assertEqual((len(faces),nodes),(1,['wing']))
        with self.assertRaisesRegex(ValueError,'matches node'):
            select_nodes(g,['fuse','unused'])


if __name__=='__main__':
    unittest.main()
