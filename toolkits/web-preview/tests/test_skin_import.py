import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('skin_import',Path(__file__).resolve().parents[1]/'skin_import.py')
skin=importlib.util.module_from_spec(spec);spec.loader.exec_module(skin)


class SkinImportTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_zip_paths_links_and_case_collisions_are_rejected(self):
        for index,name in enumerate(['../escape.dds','C:/escape.dds','folder/../escape.dds','CON.dds']):
            path=self.root/f'bad{index}.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr(name,b'bad')
            with self.assertRaises(ValueError):skin.unpack_zip(path,self.root/f'out{index}')
        path=self.root/'link.zip';info=zipfile.ZipInfo('link.dds');info.external_attr=(stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(path,'w') as z:z.writestr(info,b'../../other')
        with self.assertRaises(ValueError):skin.unpack_zip(path,self.root/'linkout')
        path=self.root/'case.zip'
        with zipfile.ZipFile(path,'w') as z:z.writestr('a.dds',b'a');z.writestr('A.dds',b'b')
        with self.assertRaises(ValueError):skin.unpack_zip(path,self.root/'caseout')
    def test_text_config_is_data_and_does_not_follow_includes(self):
        path=self.root/'cn_ztz_99a.blk'
        path.write_text('name:t="user"\n// note\nset_tex { to:t="body.dds" param:t="camo_skin_tex" from:t="ztz_99a_body_c*" }',encoding='utf-8')
        rules=skin.blk_rules(path);self.assertEqual(rules[0]['to'],'body.dds');self.assertEqual(rules[0]['param'],'camo_skin_tex')
        path.write_text('include "run_this.py"',encoding='utf-8')
        with self.assertRaises(ValueError):skin.blk_rules(path)
    def test_model_selection_uses_actual_catalog_and_keeps_shared_variants_ambiguous(self):
        catalog=[{'name':'ztz_99a','pack':'a.grp'},{'name':'ztz_99a_variant','pack':'b.grp'}]
        rules=[{'from':'ztz_99a_body_c*'}]
        candidates,vehicle=skin.choose_models(Path('cn_ztz_99a.blk'),rules,catalog)
        self.assertEqual(vehicle,'ztz_99a')
        candidates,vehicle=skin.choose_models(Path('skin.blk'),rules,catalog)
        self.assertIsNone(vehicle);self.assertEqual(len(candidates),2)
    def test_folder_and_zip_preserve_selected_inputs_without_copying_scripts(self):
        folder=self.root/'input';folder.mkdir();(folder/'tank.blk').write_bytes(b'name:t="user"');(folder/'body.dds').write_bytes(b'pixels');(folder/'run.py').write_text('raise RuntimeError')
        out=self.root/'folder-out';self.assertEqual(skin.copy_folder(folder,out),2)
        self.assertEqual((out/'body.dds').read_bytes(),b'pixels');self.assertFalse((out/'run.py').exists())
        with self.assertRaises(ValueError):skin.copy_folder(folder,folder/'bad')
        archive=self.root/'skin.zip'
        with zipfile.ZipFile(archive,'w') as z:z.write(folder/'body.dds','wrapper/body.dds');z.write(folder/'run.py','wrapper/run.py')
        zipout=self.root/'zip-out';self.assertEqual(skin.unpack_zip(archive,zipout),1);self.assertEqual((zipout/'wrapper/body.dds').read_bytes(),b'pixels')


if __name__=='__main__':unittest.main()
