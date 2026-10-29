"""Do not confuse a clipped empty patch with the full intended native panel."""
from pathlib import Path
import json,sys,tempfile,unittest
import numpy as np
from PIL import Image
ROOT=(Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial');sys.path.insert(0,str(ROOT/'scripts'))
from layout_fit import ink_points,image_coordinates,measure_composition,validate_layout_checks,require_front_facing_text
from production_tools import spec

class CompositionScopeTests(unittest.TestCase):
    def actual(self,name):
        f=Path(__file__).resolve().parent/'fixtures/a7hu-warning-layout'
        row=json.loads((f/(name+'.json')).read_text('utf-8'))
        with np.load(f/'carrier.npz') as g:p=g['positions']
        with Image.open(f/(name+'.png')) as im:alpha=np.array(im)[...,3]
        points=ink_points(alpha,row['center_uv_m'],row['graphic_size_m'])
        y,x=np.nonzero(alpha)
        content=(x.max()-x.min()+1)/alpha.shape[1]*(y.max()-y.min()+1)/alpha.shape[0]
        report=measure_composition(p,points,**{k:row['frame'][v] for k,v in [('origin','origin'),('u_axis','u'),('v_axis','v')]},graphic_bounds_area=float(np.prod(row['graphic_size_m'])*content))
        return row,report

    def test_actual_rejected_corner_is_small_on_full_A7HU_panel(self):
        _,report=self.actual('compact')
        self.assertAlmostEqual(report['carrier_area_m2'],.4089107984,places=8)
        self.assertLess(report['carrier_fill_fraction'],.25)
        self.assertLess(report['ink_span_fraction'][0],.4)

    def test_actual_full_panel_graphic_spans_both_dimensions(self):
        _,report=self.actual('full')
        self.assertGreater(report['carrier_fill_fraction'],.80)
        self.assertGreater(report['ink_span_fraction'][0],.90)
        self.assertGreater(report['ink_span_fraction'][1],.85)

    def test_crop_cannot_inflate_gate_fill(self):
        with tempfile.TemporaryDirectory(prefix='native-composition-') as temp:
            root=Path(temp);p=np.array([[[0,0,0],[1,0,0],[1,1,0]],[[0,0,0],[1,1,0],[0,1,0]]],float)
            np.savez(root/'g.npz',positions=p);Image.new('RGBA',(32,32),(200,120,30,255)).save(root/'a.png')
            row={'id':'one','source_model_sha256':'a'*64,'geometry':spec(root/'g.npz'),'faces':[0,1],'mode':'actual_ink','asset':spec(root/'a.png'),
                 'frame':{'origin':[0,0,0],'u':[1,0,0],'v':[0,1,0]},'center_uv_m':[.15,.15],'graphic_size_m':[.24,.24],
                 'scope_polygon_uv_m':[[0,0],[.3,0],[.3,.3],[0,.3]],'depth_interval_m':[-.002,.002],
                 'target_fill':{'min':.3,'max':.9,'reason':'test complete panel scale'}}
            # The cropped scope used to report 64%; the real panel is 5.76%.
            with self.assertRaisesRegex(ValueError,'Roof group scale'):
                validate_layout_checks(root,{'required_instances':['one'],'placement_checks':[row]},'a'*64)

    def test_forward_inverse_projection_keeps_top_left_image_rows(self):
        a=np.zeros((7,13),np.uint8);a[0,1]=255;a[2,9]=255;a[6,4]=255
        y,x=np.nonzero(a);expected=np.c_[(x+.5)/13,(y+.5)/7]
        for angle in [0,90,-37,180]:
            points=ink_points(a,[.7,-.2],[.93,.395],angle)
            np.testing.assert_allclose(image_coordinates(points,[.7,-.2],[.93,.395],angle),expected,rtol=0,atol=1e-12)

    def test_native_extent_gate_rejects_small_corner(self):
        with tempfile.TemporaryDirectory(prefix='native-extent-') as temp:
            root=Path(temp);f=Path(__file__).resolve().parent/'fixtures/a7hu-warning-layout';row=json.loads((f/'compact.json').read_text('utf-8'))
            row.update(id='upper',source_model_sha256='a'*64,geometry=spec(f/'carrier.npz'),faces=list(range(18)),mode='actual_ink',asset=spec(f/'compact.png'),
                       depth_interval_m=[-.002,.002],composition_requirement={'basis':'complete_native_carrier','min_span_fraction':[.9,.85],'reason':'user requested whole panel'})
            with self.assertRaisesRegex(ValueError,'full native panel extent'):
                validate_layout_checks(root,{'required_instances':['upper'],'placement_checks':[row]},'a'*64)

    def test_back_facing_basis_is_rejected_for_text(self):
        f=Path(__file__).resolve().parent/'fixtures/a7hu-warning-layout'
        with np.load(f/'carrier.npz') as g:p=g['positions']
        with self.assertRaisesRegex(ValueError,'mirror'):
            require_front_facing_text(p,[0,0,1],[-1,0,0])

    def test_actual_outward_basis_preserves_text_handedness(self):
        f=Path(__file__).resolve().parent/'fixtures/a7hu-warning-layout'
        with np.load(f/'carrier.npz') as g:p=g['positions']
        require_front_facing_text(p,[0,0,1],[1,0,0])

if __name__=='__main__':unittest.main()
