"""Reject plausible numeric/checkbox passes that hide incomplete physical work."""
import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
from test_candidate import Fixture,group
from native_inventory import NativeContext
from vehicle_review import validate_manifest
from visual_evidence import audit_visual_record,artifact_binding
from production_checks import validate_observations
from source_bindings import audit_source_bindings
from material_surfaces import audit_equipment_pixels

class EvidenceAuditTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.f=Fixture(Path(self.temp.name)/'fixture');self.f.final()
 def test_needs_fix_is_not_a_pass(self):
  r=self.f.design['reviews']['final_dds'];r['verdict']='needs_fix'
  with self.assertRaisesRegex(ValueError,'unresolved'):audit_visual_record(self.f.root,r,'final',self.f.design)
 def test_checked_text_file_is_not_an_image(self):
  r=self.f.design['reviews']['final_dds'];r['images']=[]
  with self.assertRaisesRegex(ValueError,'actual images'):audit_visual_record(self.f.root,r,'final',self.f.design)
 def test_old_texture_observation_is_rejected(self):
  r=self.f.design['reviews']['final_dds'];r['artifact_binding']['texture_sha256']['body-c']='0'*64
  with self.assertRaisesRegex(ValueError,'current model/textures'):audit_visual_record(self.f.root,r,'final',self.f.design)
 def test_json_evidence_cannot_masquerade_as_image(self):
  r=self.f.design['reviews']['final_dds'];r['images']=[self.f.evidence]
  with self.assertRaisesRegex(ValueError,'decodable image'):audit_visual_record(self.f.root,r,'final',self.f.design)
 def test_old_model_observation_is_rejected(self):
  r=self.f.design['reviews']['final_dds'];r['artifact_binding']['model_sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'current model/textures'):audit_visual_record(self.f.root,r,'final',self.f.design)
 def test_relabeling_old_picture_with_new_dds_hash_is_rejected(self):
  f=self.f;pixels=f.color.copy();pixels[...,0]=120;f.design['runtime_textures'][0]['dds']=f.image('changed.dds',pixels)
  r=f.design['reviews']['final_dds'];r['artifact_binding']=artifact_binding(f.design)
  with self.assertRaisesRegex(ValueError,'Actual render receipt'):audit_visual_record(f.root,r,'final',f.design)
 def test_unlisted_picture_cannot_use_another_render_receipt(self):
  f=self.f;pixels=f.color.copy();pixels[...,0]=115;r=f.design['reviews']['final_dds'];r['images']=[f.image('other-view.png',pixels)]
  with self.assertRaisesRegex(ValueError,'matching actual render output'):audit_visual_record(f.root,r,'final',f.design)
 def test_base_image_cannot_claim_runtime_dds_review(self):
  f=self.f;r=f.design['reviews']['final_dds'];path=f.root/r['render_receipt']['file'];p=json.loads(path.read_text());p['renders'][0]['texture_kind']='base_color';r['render_receipt']=f.json(path.name,p)
  with self.assertRaisesRegex(ValueError,'matching actual render output'):audit_visual_record(f.root,r,'final',f.design)
 def test_all_directions_not_visible_rejected(self):
  for r in self.f.design['observation_matrix']['views']:r.update(status='not_visible',reason='synthetic obstruction')
  with self.assertRaisesRegex(ValueError,'No actual native carrier'):validate_observations(self.f.root,self.f.design,{'hull':{}})
 def test_empty_checked_scope_rejected(self):
  self.f.design['observation_matrix']['views'][0]['coverage_ids']=[]
  with self.assertRaisesRegex(ValueError,'empty native scope'):validate_observations(self.f.root,self.f.design,{'hull':{}})
 def test_unobserved_carrier_needs_specific_limit(self):
  with self.assertRaisesRegex(ValueError,'omits actual carriers'):validate_observations(self.f.root,self.f.design,{'hull':{},'roof':{}})
 def test_frozen_mode_cannot_be_relaxed(self):
  c=self.f.design['coverage'][0];c['mode']='full_surface'
  with self.assertRaisesRegex(ValueError,'scope changed mode'):validate_manifest(self.f.root/self.f.save_design()['file'],'design')
 def test_reclassified_half_plate_cannot_shrink_target(self):
  c=self.f.design['coverage'][0];c['face_groups']=[group('armor',[0]),group('quiet',[1])]
  with self.assertRaisesRegex(ValueError,'shrink or change'):validate_manifest(self.f.root/self.f.save_design()['file'],'design')
 def test_omitted_source_resource_rejected(self):
  b=json.loads((self.f.root/'bindings.json').read_text());b['resources']=b['resources'][:-1]
  with self.assertRaisesRegex(ValueError,'resource inventory differs'):audit_source_bindings(self.f.root,b,{'plate'})
 def test_conflicting_export_definition_rejected(self):
  b=json.loads((self.f.root/'bindings.json').read_text());p=self.f.root/'exported-materials.json';s=json.loads(p.read_text());r=copy.deepcopy(s['materials'][0]);r['shader']='different';s['materials'].append(r)
  b['source_inventory']=self.f.json(p.name,s)
  with self.assertRaisesRegex(ValueError,'Conflicting'):audit_source_bindings(self.f.root,b,{'plate'})
 def test_identical_repeated_export_definition_is_valid(self):
  b=json.loads((self.f.root/'bindings.json').read_text());p=self.f.root/'exported-materials.json';s=json.loads(p.read_text());s['materials'].append(copy.deepcopy(s['materials'][0]));b['source_inventory']=self.f.json(p.name,s)
  self.assertTrue(audit_source_bindings(self.f.root,b,{'plate'})['source_inventory_checked'])
 def test_mixed_shaders_require_all_users(self):
  b=json.loads((self.f.root/'bindings.json').read_text());s=json.loads((self.f.root/'exported-materials.json').read_text());other=copy.deepcopy(s['materials'][0]);other.update(obj_name='glass',shader='glass_shader');s['materials'].append(other);b['source_inventory']=self.f.json('mixed-export.json',s)
  for row in b['resources']:row['users'].append('glass')
  with self.assertRaisesRegex(ValueError,'Mixed native shaders'):audit_source_bindings(self.f.root,b,{'plate','glass'})
  for row in b['resources']:row['shader_by_user']={'plate':'synthetic_native_shader','glass':'glass_shader'}
  self.assertEqual(len(audit_source_bindings(self.f.root,b,{'plate','glass'})['mixed_shader_resources']),3)
 def test_zero_pixel_comparisons_do_not_claim_preservation(self):
  f=self.f;evidence=f.json('equipment-classification.json',{'unit_id':f.design['unit_id'],'model_sha256':f.design['model']['sha256'],'equipment_source_faces':[0,1],'components':{'housing':[0,1]}})
  d=copy.deepcopy(f.design);d['runtime_textures']=[];d['sensitive_equipment']=[{'id':'optic','coverage_id':'hull','equipment_group_ids':['armor'],'classification_evidence':evidence,'components':{'housing':{'state':'preserve','group_ids':['armor']}}}]
  native=NativeContext(f.root,d);native.validate_claims({'hull':d['coverage'][0]})
  r=audit_equipment_pixels(f.root,d,native)[0]
  self.assertEqual(r['status'],'no_runtime_override');self.assertIsNone(r['unchanged']);self.assertEqual(r['runtime_regions_checked'],0)
 def test_runtime_equipment_with_zero_native_samples_is_unresolved(self):
  f=self.f;evidence=f.json('equipment-classification.json',{'unit_id':f.design['unit_id'],'model_sha256':f.design['model']['sha256'],'equipment_source_faces':[0,1],'components':{'housing':[0,1]}})
  d=copy.deepcopy(f.design);d['sensitive_equipment']=[{'id':'optic','coverage_id':'hull','equipment_group_ids':['armor'],'classification_evidence':evidence,'components':{'housing':{'state':'preserve','group_ids':['armor']}}}]
  native=NativeContext(f.root,d);native.validate_claims({'hull':d['coverage'][0]});native.mask=lambda *args:np.zeros(f.shape,bool)
  with self.assertRaisesRegex(ValueError,'zero native pixel samples'):audit_equipment_pixels(f.root,d,native)

if __name__=='__main__':unittest.main()
