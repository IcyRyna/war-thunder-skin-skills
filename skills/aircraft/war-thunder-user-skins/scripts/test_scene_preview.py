import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image

import scene_preview as scene


class SceneTests(unittest.TestCase):
    def fixture(self, root):
        triangles = np.array([[[-1.,0.,0.],[0.,0.,0.],[-1.,1.,0.]],
                              [[.2,0.,0.],[1.2,0.,0.],[.2,1.,0.]]], np.float32)
        geometry = root/'geometry.npz'
        np.savez_compressed(geometry, triangles=triangles, uvs=np.tile(np.array([[0.,0.],[1.,0.],[0.,1.]], np.float32), (2,1,1)),
                            node_ids=np.array([0,1],np.int32), names=np.array(['left','right']),
                            material_ids=np.array([0,1],np.int32), material_names=np.array(['red','green']),
                            material_resources=np.array(['[]','[]']))
        color = root/'color.png'; packed = root/'packed.png'
        Image.new('RGBA',(8,8),(180,100,50,255)).save(color)
        Image.new('RGBA',(8,8),(80,125,20,127)).save(packed)
        camera = dict(basis=np.eye(3).tolist(),center=[.1,.5],scale=32.,width=96,height=64)
        manifest = dict(schema_version=1, geometry=dict(path=geometry.name,sha256=scene.file_hash(geometry)),
                        width=96,height=64, display_state=dict(description='two nonoverlapping test triangles'),
                        cameras=dict(test=camera), materials=[
                            dict(id=0,name='red',color=dict(path=color.name,sha256=scene.file_hash(color)),
                                 packed=dict(path=packed.name,sha256=scene.file_hash(packed))),
                            dict(id=1,name='green',base_color=[0.,1.,0.,1.])])
        path=root/'scene.json'; path.write_text(json.dumps(manifest),encoding='utf-8')
        return path,manifest,color,packed

    def rewrite(self,path,raw):
        path.write_text(json.dumps(raw),encoding='utf-8')

    def pixels(self,path):
        with Image.open(path) as image:return np.asarray(image).copy()

    def test_two_material_layout_and_bound_owners(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            report=scene.render(path,'test','layout',root/'layout.png')
            self.assertGreater(report['material_coverage']['red'],0)
            self.assertGreater(report['material_coverage']['green'],0)
            with np.load(root/'layout-depth.npz',allow_pickle=False) as depth:
                owners=depth['owners'];self.assertEqual(owners.dtype,np.int32)
                actual=self.pixels(root/'layout.png')
                self.assertTrue(np.all(actual[owners==0]==[180,100,50]))
                self.assertTrue(np.all(actual[owners==1]==[0,255,0]))
            self.assertEqual(report['depth_sha256'],scene.file_hash(root/'layout-depth.npz'))
            self.assertEqual(report['camera_sha256'],scene.surface.camera_fingerprint(report))

    def test_material_R_B_controls_fixed_camera_keep_G_A_and_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            initial={p:scene.file_hash(p) for p in [path,color,packed,root/'geometry.npz']}
            baseline=scene.render(path,'test','material',root/'base.png')
            with Image.open(packed) as image:original=np.asarray(image.convert('RGBA')).copy()
            for channel,name,value in [(0,'r',230),(2,'b',240)]:
                data=original.copy();data[:,:,channel]=value
                alternate=root/f'{name}.png';Image.fromarray(data).save(alternate)
                alternative=json.loads(json.dumps(raw))
                alternative['materials'][0]['packed']=dict(path=alternate.name,sha256=scene.file_hash(alternate))
                setting=root/f'{name}.json';self.rewrite(setting,alternative)
                actual=scene.render(setting,'test','material',root/f'material-{name}.png')
                self.assertEqual(baseline['camera_sha256'],actual['camera_sha256'])
                self.assertFalse(np.array_equal(self.pixels(root/'base.png'),self.pixels(root/f'material-{name}.png')))
                self.assertTrue(np.array_equal(data[:,:,[1,3]],original[:,:,[1,3]]))
            for p,digest in initial.items():self.assertEqual(scene.file_hash(p),digest)

    def test_hash_mismatch_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            Image.new('RGBA',(8,8),'blue').save(color)
            with self.assertRaisesRegex(ValueError,'hash mismatch'):scene.render(path,'test','layout',root/'out.png')
            self.assertFalse((root/'out.png').exists())

    def test_output_input_and_derived_collisions_preserve_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            before=scene.file_hash(color)
            with self.assertRaises((ValueError,RuntimeError,OSError)):scene.render(path,'test','layout',color)
            self.assertEqual(scene.file_hash(color),before)
            protected=root/'out-mask.png';protected.write_bytes(b'prior result')
            with self.assertRaises((ValueError,RuntimeError,OSError)):scene.render(path,'test','layout',root/'out.png')
            self.assertEqual(protected.read_bytes(),b'prior result')
            self.assertFalse((root/'out.png').exists())

    def test_custom_camera_is_deterministic_and_changes_crop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            loaded=scene.load_scene(path)
            camera=root/'camera.json';self.rewrite(camera,dict(eye=[0,0,1],fit_nodes=['right'],width=128,height=96))
            first,meta,_=scene.select_camera(loaded,'custom',camera)
            second,again,_=scene.select_camera(loaded,'custom',camera)
            self.assertTrue(np.array_equal(first,second));self.assertEqual(meta,again)
            self.assertEqual(meta['width'],128)
            self.assertAlmostEqual(meta['center'][0],.7,places=6)

    def test_invalid_camera_material_and_dimensions_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            raw['materials'][1]['name']='wrong';self.rewrite(path,raw)
            with self.assertRaisesRegex(ValueError,'name mismatch'):scene.load_scene(path)
            for eye in [[0,0,0],[0,1,0],[float('nan'),0,1]]:
                with self.assertRaises(ValueError):scene.basis_from_eye(eye)
            for dimensions in [(0,64),(True,64),(128,9000),(8192,8192)]:
                with self.assertRaises(ValueError):scene.dimensions(*dimensions)

    def test_unit_UV_rejects_repeat_unless_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            geometry=root/'geometry.npz'
            with np.load(geometry,allow_pickle=False) as data:arrays={key:data[key] for key in data.files}
            arrays['uvs'][0,0,0]=1.5;np.savez_compressed(geometry,**arrays)
            raw['geometry']['sha256']=scene.file_hash(geometry);self.rewrite(path,raw)
            with self.assertRaisesRegex(ValueError,'outside unit tile'):scene.load_scene(path)
            raw['materials'][0]['uv_mode']='repeat';self.rewrite(path,raw)
            loaded=scene.load_scene(path);self.assertTrue(loaded['repeats'][0])

    def test_input_changes_during_draw_reject_stale_outputs(self):
        for changed in ['geometry','color','scene','camera']:
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);path,raw,color,packed=self.fixture(root)
                camera=root/'camera.json';self.rewrite(camera,raw['cameras']['test'])
                original_draw=scene.draw
                def change_after_draw(*args,**kwargs):
                    result=original_draw(*args,**kwargs)
                    if changed=='geometry':
                        target=root/'geometry.npz'
                        with np.load(target,allow_pickle=False) as data:arrays={key:data[key] for key in data.files}
                        arrays['triangles']+=.01;np.savez_compressed(target,**arrays)
                    elif changed=='color':Image.new('RGBA',(8,8),'blue').save(color)
                    elif changed=='scene':self.rewrite(path,{**raw,'width':128})
                    else:self.rewrite(camera,{**raw['cameras']['test'],'scale':33.})
                    return result
                with mock.patch.object(scene,'draw',side_effect=change_after_draw):
                    with self.assertRaisesRegex(ValueError,'input changed during rendering'):
                        scene.render(path,'test','layout',root/'out.png',camera)
                for name in ['out.png','out-mask.png','out-depth.npz','out.json']:
                    self.assertFalse((root/name).exists())

    def export_fixture(self,root):
        asset=root/'asset';asset.mkdir();(asset/'parts').mkdir()
        material=[dict(name='red',obj_name='red',texture_slots=[None,None,None]),
                  dict(name='green',obj_name='green',texture_slots=[None,None,None])]
        self.rewrite(asset/'materials.json',dict(materials=material))
        parts=[]
        for index,name in enumerate(['left','right']):
            obj=asset/'parts'/f'{name}.obj'
            obj.write_text(f'v {index} 0 0\nv {index+1} 0 0\nv {index} 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl {material[index]["name"]}\nf 1/1 2/2 3/3\n',encoding='utf-8')
            parts.append(dict(name=name,file=f'parts/{name}.obj',faces=1))
        self.rewrite(asset/'parts.json',dict(parts=parts))
        selection=root/'selection.json';self.rewrite(selection,dict(schema_version=1,include_nodes=['left','right'],description='explicit test static state'))
        return asset,selection

    def test_public_prepare_preserves_OBJ_geometry_and_material_association(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);asset,selection=self.export_fixture(root)
            before={path:scene.file_hash(path) for path in asset.rglob('*') if path.is_file()}
            result=scene.prepare(asset,selection,root/'prepared')
            self.assertEqual(result['triangles'],2)
            loaded=scene.load_scene(Path(result['scene']))
            np.testing.assert_array_equal(loaded['geometry']['material_ids'],[0,1])
            np.testing.assert_array_equal(loaded['geometry']['uvs'][0],[[0,0],[1,0],[0,1]])
            np.testing.assert_array_equal(loaded['geometry']['triangles'][1],[[1,0,0],[2,0,0],[1,1,0]])
            for path,digest in before.items():self.assertEqual(scene.file_hash(path),digest)
            with self.assertRaises((OSError,RuntimeError,ValueError)):scene.prepare(asset,selection,asset)

    def test_public_prepare_rejects_ambiguous_selection_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);asset,selection=self.export_fixture(root)
            for nodes in [['left','left'],['missing']]:
                self.rewrite(selection,dict(schema_version=1,include_nodes=nodes,description='test'))
                with self.assertRaises(ValueError):scene.prepare(asset,selection,root/'out')
            self.rewrite(selection,dict(schema_version=1,include_nodes=['left'],description='test'))
            self.rewrite(asset/'parts.json',dict(parts=[dict(name='left',file='../outside.obj',faces=1)]))
            with self.assertRaisesRegex(ValueError,'escapes asset root'):scene.prepare(asset,selection,root/'out')
            self.assertFalse((root/'out').exists())

    def test_tangent_normal_conventions_mirrored_UV_and_degenerate_fallback(self):
        normal=np.array([0.,0.,1.],np.float32)
        tangent=np.array([1.,0.,0.],np.float32);bitangent=np.array([0.,1.,0.],np.float32)
        ag=np.array([.4,.5,0.,.8],np.float64)
        expected=np.array([.6,0.,.8])
        np.testing.assert_allclose(scene.mapped_normal(normal,tangent,bitangent,ag,3,1.,1.),expected,atol=1e-7)
        ga=ag.copy();ga[1],ga[3]=ag[3],ag[1]
        np.testing.assert_allclose(scene.mapped_normal(normal,tangent,bitangent,ga,2,1.,1.),expected,atol=1e-7)
        rg=np.array([.8,.5,0.,0.])
        np.testing.assert_allclose(scene.mapped_normal(normal,tangent,bitangent,rg,1,1.,1.),expected,atol=1e-7)
        # Mirror U; original UV handedness must mirror world-space X while
        # retaining positive B for the unchanged V direction.
        np.testing.assert_allclose(scene.mapped_normal(normal,-tangent,bitangent,ag,3,1.,1.),[-.6,0.,.8],atol=1e-7)
        np.testing.assert_allclose(scene.mapped_normal(normal,np.zeros(3,np.float32),bitangent,ag,3,1.,1.),normal)
        np.testing.assert_array_equal(scene.mapped_normal(normal,tangent,bitangent,ag,3,0.,1.),normal)
        extreme=scene.decode_tangent_normal(np.array([0.,1.,0.,1.]),3,1.,1.)
        self.assertTrue(np.isfinite(extreme).all());self.assertAlmostEqual(float(np.linalg.norm(extreme)),1.)

    def test_packed_AG_normal_changes_light_response_and_preserves_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            left=root/'normal-left.png';right=root/'normal-right.png'
            Image.new('RGBA',(8,8),(102,128,0,204)).save(left)
            Image.new('RGBA',(8,8),(102,128,0,51)).save(right)
            for index,normal_path in enumerate([left,right]):
                raw['materials'][index]=dict(id=index,name=['red','green'][index],color=dict(path=color.name,sha256=scene.file_hash(color)),
                                            packed=dict(path=normal_path.name,sha256=scene.file_hash(normal_path)),normal_convention='ag_xy')
            raw['lighting']=dict(directions=[[1,0,1]],intensities=[4.])
            self.rewrite(path,raw)
            hashes={p:scene.file_hash(p) for p in [left,right,color]}
            first=scene.render(path,'test','material',root/'light-a.png')
            with np.load(root/'light-a-depth.npz') as data:owners=data['owners']
            pixels=self.pixels(root/'light-a.png')
            first_means=[float(pixels[owners==index].mean()) for index in [0,1]]
            self.assertGreater(first_means[0],first_means[1]+10)
            self.assertTrue(first['normal_mapping']['active_in_this_mode'])
            opposite=json.loads(json.dumps(raw));opposite['lighting']['directions']=[[-1,0,1]]
            other=root/'opposite.json';self.rewrite(other,opposite)
            scene.render(other,'test','material',root/'light-b.png')
            pixels=self.pixels(root/'light-b.png')
            second_means=[float(pixels[owners==index].mean()) for index in [0,1]]
            self.assertGreater(second_means[1],second_means[0]+10)
            scene.render(path,'test','layout',root/'layout-normal.png')
            disabled=json.loads(json.dumps(raw))
            for record in disabled['materials']:record['normal_convention']='none'
            no_normal=root/'disabled.json';self.rewrite(no_normal,disabled)
            scene.render(no_normal,'test','layout',root/'layout-disabled.png')
            np.testing.assert_array_equal(self.pixels(root/'layout-normal.png'),self.pixels(root/'layout-disabled.png'))
            # Default omission is pixel-identical to explicit disabled mode.
            default=json.loads(json.dumps(disabled))
            for record in default['materials']:record.pop('normal_convention')
            default_path=root/'default.json';self.rewrite(default_path,default)
            scene.render(no_normal,'test','material',root/'disabled-material.png')
            scene.render(default_path,'test','material',root/'default-material.png')
            np.testing.assert_array_equal(self.pixels(root/'disabled-material.png'),self.pixels(root/'default-material.png'))
            for p,digest in hashes.items():self.assertEqual(scene.file_hash(p),digest)

    def test_normal_source_validation_and_degenerate_TBN(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            raw['materials'][1]['normal_convention']='ag_xy';self.rewrite(path,raw)
            with self.assertRaisesRegex(ValueError,'needs a hash-bound'):scene.load_scene(path)
            raw['materials'][1]['normal_texture']=dict(path=packed.name,sha256=scene.file_hash(packed));self.rewrite(path,raw)
            loaded=scene.load_scene(path);self.assertEqual(loaded['normal_codes'].tolist(),[0,3])
            raw['materials'][1]['normal_y_sign']=0;self.rewrite(path,raw)
            with self.assertRaisesRegex(ValueError,'normal_y_sign'):scene.load_scene(path)
            world=loaded['geometry']['triangles'];uv=np.zeros((len(world),3,2),np.float32)
            tangent,bitangent,valid=scene.tangent_frames(world,uv)
            self.assertFalse(valid.any());self.assertFalse(tangent.any());self.assertFalse(bitangent.any())

    def test_double_sided_back_face_flips_complete_tangent_normal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            positive=root/'positive.png';negative=root/'negative.png'
            Image.new('RGBA',(8,8),(102,128,0,204)).save(positive)
            Image.new('RGBA',(8,8),(102,128,0,51)).save(negative)
            for index,normal_path in enumerate([positive,negative]):
                raw['materials'][index]=dict(id=index,name=['red','green'][index],color=dict(path=color.name,sha256=scene.file_hash(color)),
                                            packed=dict(path=normal_path.name,sha256=scene.file_hash(normal_path)),normal_convention='ag_xy',double_sided=True)
            # Geometry is +Z-facing. Looking from -Z must flip the complete
            # mapped normal: local +X becomes world -X on the back face.
            raw['cameras']['test']=dict(basis=np.diag([-1.,1.,-1.]).tolist(),center=[-.1,.5],scale=32.,width=96,height=64)
            raw['lighting']=dict(directions=[[-1,0,-1]],intensities=[4.]);self.rewrite(path,raw)
            scene.render(path,'test','material',root/'back-light-a.png')
            with np.load(root/'back-light-a-depth.npz') as data:owners=data['owners']
            pixels=self.pixels(root/'back-light-a.png')
            means=[float(pixels[owners==index].mean()) for index in [0,1]]
            self.assertGreater(means[0],means[1]+10)
            opposite=json.loads(json.dumps(raw));opposite['lighting']['directions']=[[1,0,-1]]
            other=root/'other.json';self.rewrite(other,opposite)
            scene.render(other,'test','material',root/'back-light-b.png')
            pixels=self.pixels(root/'back-light-b.png')
            means=[float(pixels[owners==index].mean()) for index in [0,1]]
            self.assertGreater(means[1],means[0]+10)

    def test_double_sided_face_sign_uses_geometry_not_perturbed_normal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            Image.new('RGBA',(8,8),(102,128,0,230)).save(packed)
            for index in [0,1]:
                raw['materials'][index]=dict(id=index,name=['red','green'][index],color=dict(path=color.name,sha256=scene.file_hash(color)),
                                            packed=dict(path=packed.name,sha256=scene.file_hash(packed)),normal_convention='ag_xy',double_sided=False)
            self.rewrite(path,raw)
            basis=scene.basis_from_eye([-1.,0.,.1]);world=scene.load_scene(path)['geometry']['triangles']
            _,camera=scene.surface.screen_vertices(world,basis,96,64)
            raw['cameras']['test']=camera;raw['lighting']=dict(directions=[[-1,0,.1]],intensities=[4.]);self.rewrite(path,raw)
            scene.render(path,'test','material',root/'single.png')
            for record in raw['materials']:record['double_sided']=True
            other=root/'double-scene.json';self.rewrite(other,raw)
            scene.render(other,'test','material',root/'double.png')
            # This geometric front face has a normal-map tilt away from the
            # eye. It must stay tilted, not be flipped to face the camera.
            np.testing.assert_array_equal(self.pixels(root/'single.png'),self.pixels(root/'double.png'))


    def test_independent_color4_packed2_numeric_UV_and_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            y,x=np.mgrid[:4,:4]
            data=np.stack((20+60*x,30+50*y,40+10*x+20*y,np.full((4,4),255)),axis=-1).astype(np.uint8)
            channels=np.array([[[51,102,0,153],[102,153,51,204]],
                               [[153,204,102,102],[204,51,153,51]]],np.uint8)
            Image.fromarray(data).save(color);Image.fromarray(channels).save(packed)
            raw['materials'][0]['color']['sha256']=scene.file_hash(color)
            raw['materials'][0]['packed']['sha256']=scene.file_hash(packed);self.rewrite(path,raw)
            loaded=scene.load_scene(path)
            self.assertEqual(loaded['colors'][0].shape,(4,4,4))
            self.assertEqual(loaded['packed'][0].shape,(2,2,4))
            # At UV(.25,.75), C uses (.75,.75) pixels, N uses (.25,.25).
            np.testing.assert_allclose(scene.sample(loaded['colors'][0],.25,.75,False),
                                       np.array([65.,67.5,62.5,255.])/255.,rtol=0,atol=1e-14)
            np.testing.assert_allclose(scene.sample(loaded['packed'][0],.25,.75,False),
                                       np.array([89.25,127.5,38.25,146.625])/255.,rtol=0,atol=1e-14)
            scene.render(path,'test','layout',root/'layout-mixed.png')
            with np.load(root/'layout-mixed-depth.npz') as depth:self.assertEqual(depth['owners'][36,20],0)
            # Camera/triangle geometry gives UV(.240625,.359375) at this pixel;
            # the affine C gradient yields RGB(63.3125,126.09375,85.65625).
            np.testing.assert_array_equal(self.pixels(root/'layout-mixed.png')[36,20],[63,126,85])

    def test_mixed_color4_packed2_normal_mapping_under_two_lights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            Image.new('RGBA',(4,4),(180,100,50,255)).save(color)
            left=root/'left2.png';right=root/'right2.png'
            Image.new('RGBA',(2,2),(102,128,0,204)).save(left)
            Image.new('RGBA',(2,2),(102,128,0,51)).save(right)
            for index,normal_path in enumerate([left,right]):
                raw['materials'][index]=dict(id=index,name=['red','green'][index],
                    color=dict(path=color.name,sha256=scene.file_hash(color)),
                    packed=dict(path=normal_path.name,sha256=scene.file_hash(normal_path)),normal_convention='ag_xy')
            raw['lighting']=dict(directions=[[1,0,1]],intensities=[4.]);self.rewrite(path,raw)
            originals={p:scene.file_hash(p) for p in [color,left,right,path]}
            first=scene.render(path,'test','material',root/'mixed-a.png')
            with np.load(root/'mixed-a-depth.npz') as depth:owners=depth['owners']
            pixels=self.pixels(root/'mixed-a.png')
            means=[float(pixels[owners==index].mean()) for index in [0,1]]
            self.assertGreater(means[0],means[1]+10)
            other=json.loads(json.dumps(raw));other['lighting']['directions']=[[-1,0,1]]
            alternate=root/'opposite.json';self.rewrite(alternate,other)
            second=scene.render(alternate,'test','material',root/'mixed-b.png')
            pixels=self.pixels(root/'mixed-b.png')
            means=[float(pixels[owners==index].mean()) for index in [0,1]]
            self.assertGreater(means[1],means[0]+10)
            self.assertEqual(first['camera_sha256'],second['camera_sha256'])
            for p,digest in originals.items():self.assertEqual(scene.file_hash(p),digest)

    def test_prepare_preserves_mixed_maps_and_independent_normal3x1(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);asset,selection=self.export_fixture(root)
            color=root/'c4.png';packed=root/'n2.png';normal=root/'normal3x1.png'
            Image.new('RGBA',(4,4),(180,100,50,255)).save(color)
            Image.new('RGBA',(2,2),(102,128,0,204)).save(packed)
            Image.fromarray(np.array([[[0,128,0,128],[0,128,0,204],[0,128,0,51]]],np.uint8)).save(normal)
            raw=json.loads(selection.read_text(encoding='utf-8'))
            raw['materials']={'red':dict(color=dict(path=str(color),sha256=scene.file_hash(color)),
                packed=dict(path=str(packed),sha256=scene.file_hash(packed)),
                normal_texture=dict(path=str(normal),sha256=scene.file_hash(normal)),normal_convention='ag_xy')}
            self.rewrite(selection,raw)
            originals={p:scene.file_hash(p) for p in [color,packed,normal]}
            result=scene.prepare(asset,selection,root/'prepared-mixed')
            loaded=scene.load_scene(Path(result['scene']))
            self.assertEqual(loaded['colors'][0].shape,(4,4,4))
            self.assertEqual(loaded['packed'][0].shape,(2,2,4))
            self.assertEqual(loaded['normal_textures'][0].shape,(1,3,4))
            np.testing.assert_allclose(scene.sample(loaded['normal_textures'][0],.25,.75,False),
                                       np.array([0.,128.,0.,166.])/255.,rtol=0,atol=1e-14)
            material=loaded['raw']['materials'][0]
            for field,p in [('color',color),('packed',packed),('normal_texture',normal)]:
                self.assertEqual(material[field]['sha256'],originals[p])
                self.assertEqual(scene.file_hash(p),originals[p])

    def test_each_texture_rejects_invalid_dimensions_before_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            asset,selection=self.export_fixture(root)
            setting=json.loads(selection.read_text(encoding='utf-8'))
            setting['materials']={'red':dict(color=dict(path=str(color),sha256=scene.file_hash(color)),
                                             packed=dict(path=str(packed),sha256=scene.file_hash(packed)))}
            self.rewrite(selection,setting)
            originals={p:scene.file_hash(p) for p in root.rglob('*') if p.is_file()}
            for index,(width,height) in enumerate([(0,2),(-1,2),(8193,8192)]):
                with self.subTest(width=width,height=height):
                    fake=mock.MagicMock()
                    fake.__enter__.return_value.width=width;fake.__enter__.return_value.height=height
                    with mock.patch.object(scene.Image,'open',return_value=fake):
                        with self.assertRaises(ValueError):scene.render(path,'test','layout',root/f'bad-{index}.png')
                    self.assertFalse((root/f'bad-{index}.png').exists())
                    fake.__enter__.return_value.load.assert_not_called()
                    with mock.patch.object(scene.Image,'open',return_value=fake):
                        with self.assertRaises(ValueError):scene.prepare(asset,selection,root/f'bad-prepared-{index}')
                    self.assertFalse((root/f'bad-prepared-{index}').exists())
                    fake.__enter__.return_value.load.assert_not_called()
            for p,digest in originals.items():self.assertEqual(scene.file_hash(p),digest)

    def test_texture_size_limits_are_distinct_from_preview_canvas(self):
        for width,height in [(1,1),(3,1),(4,4),(2,2),(8192,8192)]:
            self.assertEqual(scene.texture_dimensions(width,height),(width,height))
        for width,height in [(0,1),(-1,1),(True,2),(4.,2),(8193,8192)]:
            with self.assertRaises(ValueError):scene.texture_dimensions(width,height)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path,raw,color,packed=self.fixture(root)
            Image.new('RGBA',(3,1),(180,100,50,255)).save(color)
            Image.new('RGBA',(1,1),(102,128,0,204)).save(packed)
            raw['materials'][0]['color']['sha256']=scene.file_hash(color)
            raw['materials'][0]['packed']['sha256']=scene.file_hash(packed);self.rewrite(path,raw)
            loaded=scene.load_scene(path)
            self.assertEqual(loaded['colors'][0].shape,(1,3,4))
            self.assertEqual(loaded['packed'][0].shape,(1,1,4))

    def shared_texture_fixture(self, root):
        path, raw, color, packed = self.fixture(root)
        reference = dict(path=color.name, sha256=scene.file_hash(color))
        for index, record in enumerate(raw['materials']):
            record.pop('base_color', None)
            record.update(color=dict(reference), packed=dict(reference), normal_texture=dict(reference),
                          normal_convention=['ag_xy', 'ga_xy'][index],
                          normal_y_sign=[1., -1.][index], normal_strength=[.4, 1.5][index])
        # The same resolved path through a different valid relative spelling.
        raw['materials'][1]['color']['path'] = './'+color.name
        self.rewrite(path, raw)
        return path, raw, color

    def test_texture_reuse_is_opt_in_and_per_load_not_global(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path, raw, color = self.shared_texture_fixture(root)
            with mock.patch.object(scene, 'read_texture', wraps=scene.read_texture) as decoder:
                legacy = scene.load_scene(path)
                self.assertEqual(decoder.call_count, 6)
            arrays = legacy['colors']+legacy['packed']+legacy['normal_textures']
            self.assertEqual(len({id(array) for array in arrays}), 6)
            original = scene.file_hash(color)
            with mock.patch.object(scene, 'read_texture', wraps=scene.read_texture) as decoder:
                with mock.patch.object(scene, 'bound_file', wraps=scene.bound_file) as binding:
                    reused = scene.load_scene(path, reuse_textures=True)
                    self.assertEqual(decoder.call_count, 1)
                    self.assertEqual(binding.call_count, 7)  # geometry plus all six explicit refs
            arrays = reused['colors']+reused['packed']+reused['normal_textures']
            self.assertEqual(len({id(array) for array in arrays}), 1)
            with mock.patch.object(scene, 'read_texture', wraps=scene.read_texture) as decoder:
                another = scene.load_scene(path, reuse_textures=True)
                self.assertEqual(decoder.call_count, 1)
            self.assertIsNot(another['colors'][0], reused['colors'][0])
            self.assertEqual(scene.file_hash(color), original)
            with self.assertRaises(ValueError): scene.load_scene(path, reuse_textures=1)

    def test_shared_decode_keeps_each_material_and_normal_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path, raw, color = self.shared_texture_fixture(root)
            loaded = scene.load_scene(path, reuse_textures=True)
            self.assertEqual(loaded['normal_codes'].tolist(), [3, 2])
            np.testing.assert_allclose(loaded['normal_strengths'], [.4, 1.5])
            self.assertEqual(loaded['normal_y_signs'].tolist(), [1., -1.])
            self.assertEqual(loaded['geometry']['material_ids'].tolist(), [0, 1])
            self.assertEqual([record['id'] for record in loaded['raw']['materials']], [0, 1])
            self.assertEqual(loaded['inputs'].count(color.resolve()), 6)
            self.assertEqual(loaded['input_hashes'][color.resolve()], scene.file_hash(color))
            first = scene.decode_tangent_normal(loaded['normal_textures'][0][0,0]/255., 3, .4, 1.)
            second = scene.decode_tangent_normal(loaded['normal_textures'][1][0,0]/255., 2, 1.5, -1.)
            self.assertFalse(np.allclose(first, second))

    def test_reused_reference_cannot_bypass_different_expected_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path, raw, color = self.shared_texture_fixture(root)
            before = scene.file_hash(color)
            raw['materials'][1]['color']['sha256'] = '0'*64
            self.rewrite(path, raw)
            with mock.patch.object(scene, 'read_texture', wraps=scene.read_texture) as decoder:
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    scene.load_scene(path, reuse_textures=True)
                self.assertEqual(decoder.call_count, 1)
            self.assertEqual(scene.file_hash(color), before)

    def test_reused_reference_revalidates_changed_file_after_first_decode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path, raw, color = self.shared_texture_fixture(root)
            original = scene.read_texture
            def changed(texture_path, digest):
                array = original(texture_path, digest)
                Image.new('RGBA', (8,8), 'blue').save(color)
                return array
            with mock.patch.object(scene, 'read_texture', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    scene.load_scene(path, reuse_textures=True)

    def test_cache_hit_keeps_snapshot_check_after_reference_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path, raw, color = self.shared_texture_fixture(root)
            original = scene.bound_file
            def changed(reference, directory, field):
                result = original(reference, directory, field)
                if field == 'materials[0].packed':
                    Image.new('RGBA', (8,8), 'blue').save(color)
                return result
            with mock.patch.object(scene, 'bound_file', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'texture changed before snapshot'):
                    scene.load_scene(path, reuse_textures=True)

    def test_one_path_cannot_bind_two_real_versions_in_either_mode(self):
        for reuse in [False, True]:
            with self.subTest(reuse_textures=reuse), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); path, raw, color = self.shared_texture_fixture(root)
                replacement = root/'replacement.png'
                Image.new('RGBA', (8,8), 'blue').save(replacement)
                replacement_bytes = replacement.read_bytes()
                replacement_hash = scene.file_hash(replacement)
                for index, record in enumerate(raw['materials']):
                    for field in ('color', 'packed', 'normal_texture'):
                        if index != 0 or field != 'color':
                            record[field]['sha256'] = replacement_hash
                self.rewrite(path, raw)
                original = scene.read_texture
                def replace_after_first_snapshot(texture_path, digest):
                    array = original(texture_path, digest)
                    color.write_bytes(replacement_bytes)
                    return array
                with mock.patch.object(scene, 'read_texture', side_effect=replace_after_first_snapshot) as decoder:
                    with self.assertRaisesRegex(ValueError, 'conflicting texture snapshots'):
                        scene.load_scene(path, reuse_textures=reuse)
                    self.assertEqual(decoder.call_count, 1)
                self.assertEqual(color.read_bytes(), replacement_bytes)
                self.assertFalse((root/'out.png').exists())
                self.assertFalse((root/'out.json').exists())


if __name__=='__main__':unittest.main()
