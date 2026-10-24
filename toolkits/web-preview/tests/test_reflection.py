import json
from pathlib import Path
import struct
import tempfile
import unittest
from PIL import Image
import preview
import reflection


class ReflectionTests(unittest.TestCase):
    def test_official_channels_are_linear_and_alpha_is_normal_data(self):
        orm,normal=reflection.convert(Image.new('RGBA',(2,2),(220,128,180,128)))
        self.assertEqual(orm.getpixel((0,0)),(255,35,180))
        self.assertEqual(normal.getpixel((0,0)),(128,128,255))
        orm2,_=reflection.convert(Image.new('RGBA',(1,1),(0,128,0,128)))
        self.assertEqual(orm2.getpixel((0,0)),(255,255,0))

    def test_conversion_normalizes_compression_extremes(self):
        _,normal=reflection.convert(Image.new('RGBA',(1,1),(0,255,0,255)))
        x,y,z=normal.getpixel((0,0));self.assertAlmostEqual(x,218,delta=1);self.assertEqual(x,y);self.assertEqual(z,128)

    def test_prepare_embeds_maps_and_keeps_geometry_and_source_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=root/'model';model.mkdir();obj=model/'assembly.obj'
            obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\no hull\nusemtl paint\nf 1/1 2/2 3/3\n')
            source=root/'packed.png';Image.new('RGBA',(8,8),(190,128,100,128)).save(source);original=source.read_bytes()
            bindings=root/'bindings.json';bindings.write_text(json.dumps({'surface_materials':{'paint':'packed.png'}}))
            result=preview.prepare(model,root/'scene',bindings)
            self.assertEqual(result['triangles'],1);self.assertEqual(result['reflection_materials'],1);self.assertEqual(source.read_bytes(),original)
            raw=(root/'scene/model.glb').read_bytes();size=struct.unpack_from('<I',raw,12)[0];gltf=json.loads(raw[20:20+size]);material=gltf['materials'][0]
            self.assertIn('normalTexture',material);self.assertIn('metallicRoughnessTexture',material['pbrMetallicRoughness'])
            self.assertEqual(material['pbrMetallicRoughness']['metallicFactor'],1)
            self.assertEqual(struct.unpack_from('<I',raw,8)[0],len(raw))
            info=result['materials'][0]['reflection'];self.assertTrue((root/'scene'/info['orm']['file']).is_file());self.assertEqual(info['orm']['size'],[8,8])


if __name__=='__main__':unittest.main()
