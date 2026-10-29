"""Independent companion discovery, identity and file integrity."""
from pathlib import Path
import json,os,tempfile,unittest,sys
from unittest.mock import patch
sys.path.insert(0,str((Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')/'scripts'))
from asset_pack import PACK_ID,locate,reference,verify,digest

class AssetPackTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.skill=self.root/'skill';self.skill.mkdir();self.write(self.skill/'VERSION.json',{'skill_id':'wt-style-charcoal-industrial','version':'0.1.6'})
  self.pack=self.make_pack(self.root/PACK_ID)
  self.environment=patch.dict(os.environ,{},clear=False);self.environment.start();self.addCleanup(self.environment.stop)
  os.environ.pop('WT_CHARCOAL_ASSETS',None)
 def write(self,path,data):path.write_text(json.dumps(data),encoding='utf8')
 def make_pack(self,path):
  path.mkdir();self.write(path/'catalog.json',{'schema_version':3,'assets':[]});(path/'payload.txt').write_text('synthetic material identity',encoding='utf8')
  files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in path.iterdir()]
  self.write(path/'ASSET_PACK.json',{'schema_version':1,'asset_pack_id':PACK_ID,'skill_id':'wt-style-charcoal-industrial','version':'0.1.6','compatible_skill_versions':['0.1.6'],'catalog':{'file':'catalog.json','sha256':digest(path/'catalog.json')},'files':files})
  return path
 def test_sibling_pack_is_found(self):self.assertEqual(locate(skill_root=self.skill)[0],self.pack.resolve())
 def test_explicit_external_location(self):
  other=self.make_pack(self.root/'elsewhere');self.assertEqual(locate(other,skill_root=self.skill)[0],other.resolve())
 def test_environment_location(self):
  other=self.make_pack(self.root/'outside');os.environ['WT_CHARCOAL_ASSETS']=str(other);self.assertEqual(locate(skill_root=self.skill)[0],other.resolve())
 def test_wrong_explicit_path_does_not_fall_back(self):
  with self.assertRaises(FileNotFoundError):locate(self.root/'absent',skill_root=self.skill)
 def test_version_mismatch_rejected(self):
  p=self.pack/'ASSET_PACK.json';r=json.loads(p.read_text());r['compatible_skill_versions']=['0.1.5'];self.write(p,r)
  with self.assertRaisesRegex(ValueError,'compatibility'):locate(self.pack,skill_root=self.skill)
 def test_wrong_pack_identity_rejected(self):
  p=self.pack/'ASSET_PACK.json';r=json.loads(p.read_text());r['asset_pack_id']='another-pack';self.write(p,r)
  with self.assertRaisesRegex(ValueError,'not the charcoal'):locate(self.pack,skill_root=self.skill)
 def test_catalog_tampering_rejected(self):
  (self.pack/'catalog.json').write_text('{}',encoding='utf8')
  with self.assertRaisesRegex(ValueError,'catalog hash'):locate(self.pack,skill_root=self.skill)
 def test_asset_path_escape_rejected(self):
  with self.assertRaisesRegex(ValueError,'escapes'):reference('asset-pack:../skill/VERSION.json',pack=self.pack,skill_root=self.skill)
 def test_asset_pack_verifies_without_being_in_skill(self):self.assertTrue(verify(self.pack,skill_root=self.skill)['passed'])
 def test_changed_material_detected(self):
  (self.pack/'payload.txt').write_text('changed')
  with self.assertRaisesRegex(ValueError,'content changed'):verify(self.pack,skill_root=self.skill)
 def test_unknown_extra_file_rejected(self):
  (self.pack/'unexpected.txt').write_text('research residue')
  with self.assertRaisesRegex(ValueError,'file set differs'):verify(self.pack,skill_root=self.skill)

if __name__=='__main__':unittest.main()
