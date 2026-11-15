import argparse
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

import item_visibility as audit
import scene_preview as scene
import vector_paint as paint


class VisibilityTests(unittest.TestCase):
    def test_native_same_colour_and_occluded_marks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            geom = root/'plate.npz'
            # Two sheets at the same screen position: the front has a neutral
            # material, the rear uses the other half of the body UV atlas.
            tris = np.array([[[-.9,-.8,0.], [-.1,-.8,0.], [-.9,.8,0.]],
                             [[.1,-.8,0.], [.9,-.8,0.], [.1,.8,0.]],
                             [[.1,-.8,.2], [.9,-.8,.2], [.1,.8,.2]]], np.float32)
            uvs = np.array([[[.05,.1],[.4,.1],[.05,.9]], [[.55,.1],[.9,.1],[.55,.9]],
                            [[.55,.1],[.9,.1],[.55,.9]]], np.float32)
            np.savez(geom, triangles=tris, uvs=uvs, node_ids=np.arange(3, dtype=np.int32),
                     names=np.array(['left','rear','front']), material_ids=np.array([0,0,1],np.int32),
                     material_names=np.array(['body','cover']), material_resources=np.array(['[]','[]']))
            base = root/'base.png'
            Image.new('RGBA',(64,64),(51,51,52,255)).save(base)
            def mark(name,x,y,fill):
                return dict(id=name,chart='paint',type='polygon',fill=fill,
                            points=[[x,y],[x+.2,y],[x,y+.4]])
            design = dict(schema_version=1, atlas=dict(width=64,height=64), supersample=2, bleed_px=0,
                          charts=[dict(id='paint',u='x',v='y',materials=['body'])],
                          layers=[dict(name='marks',items=[mark('visible',-.8,-.7,'#a070d0'),
                                   mark('under-cover',.2,-.7,'#a070d0'),mark('same',-.8,.05,'#333334')])])
            ds=root/'design.json';ds.write_text(json.dumps(design),encoding='utf8')
            baked = root/'original'
            paint.run(argparse.Namespace(geometry=geom,design=ds,base=base,protect=None,out=baked,proof_width=None))
            col = baked/'composite.png'
            camera=dict(basis=np.eye(3).tolist(),center=[0,0],scale=40,width=96,height=80)
            raw=dict(schema_version=1,geometry=dict(path=geom.name,sha256=scene.file_hash(geom)),
                     width=96,height=80,display_state=dict(description='occluded right half-plane'),cameras=dict(front=camera),
                     materials=[dict(id=0,name='body',color=dict(path=str(col),sha256=scene.file_hash(col))),
                                dict(id=1,name='cover',base_color=[.5,.5,.5,1])])
            sc=root/'scene.json';sc.write_text(json.dumps(raw),encoding='utf8')
            scene.render(sc,'front','layout',root/'front.png')
            opts=argparse.Namespace(design=ds,base=base,geometry=geom,protect=None,material='body',width=64,
                                    view=root/'front.json',item=['visible','under-cover','same'])
            report=audit.inspect(opts)
            self.assertEqual(report['full_proof_differs_from_saved_gt1'],0)
            self.assertEqual([x['status'] for x in report['items'].values()],
                             ['visible_rgb_difference','no_screen_difference','no_composite_rgb_difference'])
            self.assertGreater(report['items']['under-cover']['changed_atlas_texels'],0)
            # A different image with the same dimensions cannot represent this saved camera.
            Image.new('RGB',(96,80)).save(root/'front.png')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                audit.inspect(opts)

    def test_single_pixel_and_shared_surface_are_separate(self):
        full=np.array([[33,3,9],[99,30,0],[33,30,25]],np.uint8)
        removed=full.copy();removed[0]+=4;removed[1]+=2
        result=audit.summary(full,removed,np.array([2,0,0]),2,np.arange(3),np.zeros(3,int),full)
        self.assertEqual(result['on_carrier']['pixels'],1)
        self.assertEqual(result['other_shared_surface']['pixels'],1)
        self.assertEqual(audit.classify(3,2,result),'trace_only')
        other=audit.summary(full,removed,np.array([0,0,0]),2,np.arange(3),np.zeros(3,int),full)
        self.assertEqual(audit.classify(3,2,other),'only_other_surface')


if __name__=='__main__':
    unittest.main()
