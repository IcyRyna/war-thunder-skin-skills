import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('paint_project',Path(__file__).resolve().parents[1]/'project.py')
project=importlib.util.module_from_spec(spec);spec.loader.exec_module(project)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.scene=self.root/'scene';self.scene.mkdir();Image.new('RGB',(16,8),(40,70,50)).save(self.scene/'native-color-000.png')
        source=self.scene/'native-color-000.png'
        row={'name':'body','source_sha256':'source','source_size':[16,8],'view_mode':'stock-camo-approx','camo_sha256':'camo','native_file':source.name,'native_sha256':project.hashlib.sha256(source.read_bytes()).hexdigest(),'source_quality':'native-top'}
        self.scene_data={'schema_version':1,'source_obj_sha256':'model','materials':[row]};self.write(self.scene/'scene.json',self.scene_data)
        Image.new('RGBA',(4,4),(255,0,0,100)).save(self.root/'logo.png')
        self.plan={'kind':'wt-paint-plan','schema_version':1,'model':'model','long_edge':4096,'parts':{'root#0':{'category':'车身','label':'主车身','confirmed':True}},'materials':[{'name':'body','layers':[{'type':'decal','file':'logo.png','name':'AI 标识'}]}]}
        self.plan_path=self.root/'plan.json';self.write(self.plan_path,self.plan)
    def write(self,path,data):path.write_text(json.dumps(data),encoding='utf-8')
    def tearDown(self):self.tmp.cleanup()
    def test_4k_project_embeds_native_base_and_does_not_fake_human_confirmation(self):
        out=self.root/'project.json';project.build(self.scene,self.plan_path,out);data=json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual((data['materials'][0]['width'],data['materials'][0]['height']),(4096,2048))
        self.assertEqual(data['materials'][0]['native_width'],16)
        self.assertEqual(data['materials'][0]['layers'][0]['origin'],'ai')
        self.assertTrue(data['materials'][0]['layers'][0]['src'].startswith('data:image/png;base64,'))
        self.assertFalse(data['parts']['root#0']['confirmed'])
        self.assertFalse(data['materials'][0]['layers'][0]['manually_adjusted'])
    def test_asset_escape_and_overwrite_are_rejected(self):
        self.plan['materials'][0]['layers'][0]['file']='../elsewhere.png';self.write(self.plan_path,self.plan)
        with self.assertRaises(ValueError):project.build(self.scene,self.plan_path,self.root/'out.json')
        out=self.root/'keep.json';out.write_text('keep')
        with self.assertRaises(FileExistsError):project.write_new(out,{'x':1})
        self.assertEqual(out.read_text(),'keep')
    def test_changed_base_and_wrong_model_are_rejected(self):
        self.plan['model']='wrong';self.write(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'不匹配'):project.build(self.scene,self.plan_path,self.root/'out.json')
        self.plan['model']='model';self.write(self.plan_path,self.plan);(self.scene/'native-color-000.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'哈希变化'):project.build(self.scene,self.plan_path,self.root/'out.json')
    def test_invalid_layer_ids_switches_and_part_references_are_rejected(self):
        for change in ({'id':'invalid id'},{'locked':'yes'},{'part_refs':{'root#0':True}}):
            with self.assertRaises(ValueError):project.prepare_layer({'type':'shape',**change},self.root)
    def test_thumbnail_is_not_accepted_as_editing_source(self):
        self.scene_data['materials'][0]['source_quality']='thumbnail-only';self.write(self.scene/'scene.json',self.scene_data)
        with self.assertRaisesRegex(ValueError,'缩略级'):project.build(self.scene,self.plan_path,self.root/'out.json')


if __name__=='__main__':unittest.main()
