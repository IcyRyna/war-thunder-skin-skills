import tempfile
from pathlib import Path
import unittest
import numpy as np
from PIL import Image
from surface_preview import camera_basis,screen_vertices,rasterize,project_overlay,paint_image
from build_skin import build


class SurfaceTests(unittest.TestCase):
    def test_side_print_direction_agrees_with_isometric_camera(self):
        # A printed horizontal stroke on the right side must not reverse
        # when the reviewer moves from a side camera to the front quarter.
        stroke=np.array([1.,0.,0.],dtype=np.float32)
        self.assertGreater(float(camera_basis('right')[0]@stroke),0.)
        self.assertGreater(float(camera_basis('iso')[0]@stroke),0.)
        for view in ['top','bottom','left','right','front','rear','iso']:
            basis=camera_basis(view)
            self.assertTrue(np.allclose(basis[0],np.cross(basis[1],basis[2]),atol=1e-6),view)

    def test_editor_png_can_be_render_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'editor.png';Image.new('RGBA',(8,8),(10,20,30,77)).save(path)
            bitmap=paint_image(path)
            self.assertEqual(bitmap.getpixel((0,0)),(10,20,30,77));bitmap.close()
    def scene(self):
        face=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],dtype=np.float32)
        behind=face.copy();behind[:,2]=-1
        world=np.stack((face,behind))
        uvs=np.array([[[.25,.5]]*3,[[.75,.5]]*3],dtype=np.float32)
        texture=np.zeros((4,4,4),dtype=np.uint8);texture[:,:2]=[255,0,0,255];texture[:,2:]=[0,255,0,255]
        basis=np.eye(3,dtype=np.float32)
        screen,meta=screen_vertices(world,basis,64,64)
        return world,uvs,texture,basis,screen,meta

    def test_depth_buffer_hides_back_triangle(self):
        world,uvs,texture,basis,screen,meta=self.scene()
        frame,depth,owners=rasterize(screen,world,uvs,texture,64,64)
        mask=owners>=0
        self.assertTrue(mask.any())
        self.assertTrue(np.all(owners[mask]==0))
        self.assertTrue(np.all(frame[mask][:,0]>190))
        self.assertTrue(np.all(frame[mask][:,1]==0))

    def test_reverse_face_is_culled_in_layout_preview(self):
        world,uvs,texture,basis,screen,meta=self.scene()
        world=world[:,[0,2,1],:]
        screen,meta=screen_vertices(world,basis,64,64)
        _,_,owners=rasterize(screen,world,uvs,texture,64,64)
        self.assertTrue(np.all(owners==-1))

    def test_left_handed_camera_keeps_outward_front_faces(self):
        world,uvs,texture,basis,screen,meta=self.scene()
        basis=np.diag([-1.,1.,1.]).astype(np.float32)
        screen,meta=screen_vertices(world,basis,64,64)
        _,_,owners=rasterize(screen,world,uvs,texture,64,64,float(np.linalg.det(basis)))
        self.assertTrue(np.any(owners==0))

    def test_projection_preserves_alpha_and_rejects_occluded_surface(self):
        world,uvs,texture,basis,screen,meta=self.scene()
        # Give both layers valid atlas triangles to test UV-to-world projection.
        uvs[:]=np.array([[0.,0.],[1.,0.],[0.,1.]],dtype=np.float32)
        _,depth,_=rasterize(screen,world,uvs,texture,64,64)
        overlay=np.empty((64,64,4),dtype=np.uint8);overlay[:]=[0,255,0,128]
        base=np.empty((32,32,4),dtype=np.uint8);base[:]=[100,100,100,77]
        output=base.copy();score=np.zeros((32,32),dtype=np.float32);owner=np.full((32,32),-1,dtype=np.int32)
        count=project_overlay(world,uvs,basis,np.asarray(meta['center'],dtype=np.float32),meta['scale'],overlay,depth,
                              base,output,score,owner,3/meta['scale'])
        self.assertGreater(count,0)
        mask=score>0
        self.assertTrue(np.all(owner[mask]==0))
        self.assertTrue(np.all(output[:,:,3]==77))
        self.assertTrue(np.all(output[mask][:,0]==49))
        self.assertTrue(np.all(output[mask][:,1]==177))

    def test_builder_keeps_original_alpha_and_material_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);template=root/'template';template.mkdir()
            color=np.empty((4,4,4),dtype=np.uint8);color[:]=[80,90,100,0];color[:,:,3]=np.arange(16,dtype=np.uint8).reshape(4,4)*10
            material=np.empty((4,4,4),dtype=np.uint8);material[:]=[1,2,3,4]
            Image.fromarray(color).save(template/'color.tga');Image.fromarray(material).save(template/'material.tga')
            (template/'plane.blk').write_text('name:t="user"\nreplace_tex{from:t="plane_c*" to:t="color.tga"}\nreplace_tex{from:t="plane_n*" to:t="material.tga"}\n',encoding='utf-8')
            painted=root/'paint.png';Image.new('RGB',(4,4),(10,20,30)).save(painted)
            output=root/'skin'
            report=build(template,{'plane_c*':painted},{},output)
            with Image.open(output/'plane_c.tga') as bitmap: actual=np.asarray(bitmap.convert('RGBA'))
            self.assertTrue(np.array_equal(actual[:,:,3],color[:,:,3]))
            with Image.open(output/'plane_n.tga') as bitmap: actual=np.asarray(bitmap.convert('RGBA'))
            self.assertTrue(np.array_equal(actual,material))
            self.assertEqual(report['static_validation_errors'],0)

    def test_material_channel_edit_keeps_other_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);template=root/'template';template.mkdir()
            material=np.empty((4,4,4),dtype=np.uint8);material[:]=[10,125,20,127]
            Image.fromarray(material).save(template/'material.tga')
            Image.new('RGBA',(4,4),(80,90,100,255)).save(template/'color.tga')
            (template/'plane.blk').write_text('name:t="user"\nreplace_tex{from:t="plane_c*" to:t="color.tga"}\nreplace_tex{from:t="plane_n*" to:t="material.tga"}\n',encoding='utf-8')
            red=root/'r.png';Image.new('L',(4,4),180).save(red)
            output=root/'skin';build(template,{}, {},output,{'plane_n*':{'R':red}})
            with Image.open(output/'plane_n.tga') as bitmap: actual=np.asarray(bitmap.convert('RGBA'))
            self.assertTrue(np.all(actual[:,:,0]==180))
            self.assertTrue(np.array_equal(actual[:,:,1:],material[:,:,1:]))

    def test_projection_rejects_edge_on_geometry(self):
        world,uvs,texture,basis,screen,meta=self.scene()
        angle=np.deg2rad(80)
        rotation=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]],dtype=np.float32)
        world=world@rotation.T
        uvs[:]=np.array([[0.,0.],[1.,0.],[0.,1.]],dtype=np.float32)
        screen,meta=screen_vertices(world,basis,64,64)
        _,depth,_=rasterize(screen,world,uvs,texture,64,64)
        overlay=np.empty((64,64,4),dtype=np.uint8);overlay[:]=[255,0,0,255]
        base=np.empty((32,32,4),dtype=np.uint8);base[:]=[100,100,100,77]
        output=base.copy();score=np.zeros((32,32),dtype=np.float32);owner=np.full((32,32),-1,dtype=np.int32)
        writes=project_overlay(world,uvs,basis,np.asarray(meta['center'],dtype=np.float32),meta['scale'],overlay,depth,
                               base,output,score,owner,3/meta['scale'],.6)
        self.assertEqual(writes,0)
        self.assertTrue(np.array_equal(output,base))

    def test_thin_wing_reverse_face_is_not_painted_through(self):
        front=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],dtype=np.float32)
        back=front[[0,2,1]].copy();back[:,2]=-.002
        world=np.stack((front,back))
        # Separate UV islands reveal erroneous paint on the reverse face.
        uvs=np.array([[[0.,0.],[.45,0.],[0.,1.]],[[.55,0.],[.55,1.],[1.,0.]]],dtype=np.float32)
        basis=np.eye(3,dtype=np.float32)
        screen,meta=screen_vertices(world,basis,64,64)
        base=np.full((64,64,4),80,dtype=np.uint8)
        _,depth,_=rasterize(screen,world,uvs,base,64,64)
        overlay=np.empty((64,64,4),dtype=np.uint8);overlay[:]=[255,0,0,255]
        output=base.copy();score=np.zeros((64,64),dtype=np.float32);owner=np.full((64,64),-1,dtype=np.int32)
        writes=project_overlay(world,uvs,basis,np.asarray(meta['center'],dtype=np.float32),meta['scale'],overlay,depth,
                               base,output,score,owner,3/meta['scale'],.6)
        self.assertGreater(writes,0)
        self.assertTrue(np.all(owner[score>0]==0))
        self.assertTrue(np.array_equal(output[:,36:],base[:,36:]))


if __name__=='__main__':unittest.main()
