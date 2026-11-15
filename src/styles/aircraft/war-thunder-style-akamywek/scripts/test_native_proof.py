"""Reduced layout proofs use the native UV selections and preserve data channels."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image

import vector_paint as vp
from test_vector_paint import islands


class ProofTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.geo = self.root/'plane.npz'
        islands(self.geo, [(-1,1,-1,1,0,1,0,1)])
        self.design = dict(schema_version=1, atlas=dict(width=96,height=64), supersample=2, bleed_px=3,
                           charts=[dict(id='skin', u='x', v='z', island=[[44.,23.]],
                                        frame=dict(origin=[42,31],x=[35,2],y=[-3,-26]))],
                           layers=[
                               dict(name='shapes', items=[dict(id='field',type='polygon',chart='skin',
                                     points=[[-2,-2],[2,-2],[2,2],[-2,2]],fill='#b03044')]),
                               dict(name='art',images=[dict(id='im',source='art.png',chart='skin',
                                    center=[.2,-.1],width=.7,rotation=18,flip=True)]),
                               dict(name='type',images=[dict(id='letter',text='A',chart='skin',
                                    center=[-.4,.35],height=.25)])])
        rgba=np.zeros((11,7,4),np.uint8)
        rgba[2:9,1:4]=[20,80,210,143]
        Image.fromarray(rgba).save(self.root/'art.png')

    def run_design(self, design, key, width=None, base=None, mask=None):
        src=self.root/(key+'.json')
        src.write_text(json.dumps(design),encoding='utf-8')
        dst=self.root/key
        receipt=vp.run(SimpleNamespace(design=src,geometry=self.geo,base=base,protect=mask,
                                       proof_width=width,out=dst))
        return dst,receipt

    def test_manual_rectangular_design_matches_all_layers_and_shared_owners(self):
        small=copy.deepcopy(self.design)
        small['atlas']={'width':36,'height':24}
        small['bleed_px']=2
        chart=small['charts'][0]
        ratio=np.array([35/95,23/63])
        chart['island']=(np.array(chart['island'])*ratio).tolist()
        for key in ('x','y','origin'):
            chart['frame'][key]=(np.array(chart['frame'][key])*ratio).tolist()
        trial, receipt=self.run_design(self.design,'proof',width=36)
        manual, ordinary=self.run_design(small,'manual')
        for filename in ('layers/01-shapes.png','layers/02-art.png','layers/03-type.png','composite.png','chart-coverage.png'):
            with Image.open(trial/filename) as a, Image.open(manual/filename) as b:
                np.testing.assert_array_equal(np.array(a),np.array(b))
        self.assertNotIn('proof',ordinary)
        self.assertEqual(receipt['proof']['bleed_px'],2)
        geometry=vp.load_geometry(self.geo)
        assign,_,facing,_,_=vp.select_charts(small,geometry,(36,24))
        from uv_ownership import surface_owners
        owners=surface_owners(geometry['uvs'].astype(np.float64),assign,facing,36,24)
        self.assertEqual(receipt['proof']['owner_atlas_sha256'],hashlib.sha256(owners.astype('<i4')).hexdigest())
        self.assertEqual(receipt['zero_hit_items'],[])

    def test_single_native_mechanical_texel_survives_noninteger_reduction_and_data_alpha(self):
        original=np.empty((64,96,4),np.uint8)
        yy,xx=np.indices(original.shape[:2])
        original[:,:,:3]=np.stack([xx*2,yy*2,yy+xx],axis=-1)
        original[:,:,3]=np.where((yy+xx)%3==0,0,151)
        base=self.root/'base.png';Image.fromarray(original).save(base)
        native_mask=np.zeros((64,96),np.uint8)
        native_mask[33,41]=1
        native_mask[0,95]=255
        mask=self.root/'mask.png';Image.fromarray(native_mask).save(mask)
        out,r=self.run_design(self.design,'guard',36,base,mask)
        with Image.open(out/'composite.png') as image:
            composite=np.asarray(image)
        with Image.open(out/'chart-coverage.png') as image:
            guarded=np.asarray(image)==0
        self.assertTrue(guarded[12,15])
        self.assertTrue(guarded[0,35])
        self.assertEqual(r['proof']['protected_texels'],int(guarded.sum()))
        rgb=np.array(Image.fromarray(original[:,:,:3]).resize((36,24),Image.Resampling.BOX))
        expected_alpha=np.array(Image.fromarray(original[:,:,3]).resize((36,24),Image.Resampling.NEAREST))
        np.testing.assert_array_equal(composite[:,:,3],expected_alpha)
        np.testing.assert_array_equal(composite[guarded,:3],rgb[guarded])
        for layer in (out/'layers').glob('*.png'):
            with Image.open(layer) as im:
                self.assertFalse(np.asarray(im)[:,:,3][guarded].any())
        self.assertGreater(np.count_nonzero(np.any(composite[:,:,:3]!=rgb,axis=2)),600)

    def test_invalid_size_or_native_inputs_do_not_publish_a_proof(self):
        for name,width in [('larger',120),('same',96),('short',21),('aspect',49)]:
            with self.subTest(width=width),self.assertRaisesRegex(ValueError,'proof-width'):
                self.run_design(self.design,name,width)
            self.assertFalse((self.root/name).exists())
        wrong=self.root/'wrong.png';Image.new('RGB',(36,24)).save(wrong)
        with self.assertRaisesRegex(ValueError,'native design.atlas'):
            self.run_design(self.design,'wrongbase',36,base=wrong)
        with self.assertRaisesRegex(ValueError,'native atlas size'):
            self.run_design(self.design,'wrongmask',36,mask=wrong)


if __name__=='__main__':
    unittest.main()
