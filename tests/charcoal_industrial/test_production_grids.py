"""Actual grid/vector transforms and production-state/channel-repair regressions."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=(Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0,str(ROOT/"scripts"))
from material_grid import transform_packed, conservative_mask, downsample_patch
from production_checks import validate_observations, audit_channel_repair, CHANNELS
from vehicle_review import validate_manifest
from runtime_validation import audit_runtime
from test_candidate import Fixture


class GridTests(unittest.TestCase):
    def setUp(self):
        self.p=np.zeros((8,8,4),np.uint8);self.p[:]=[80,160,90,110]
    def test_four_turns_restore_normal_and_material(self):
        a=self.p.copy()
        for _ in range(4):a=transform_packed(a,90)
        self.assertTrue(np.array_equal(a,self.p))
    def test_mirror_changes_vector_not_data_alpha_coverage(self):
        a=transform_packed(self.p,mirror_u=True)
        self.assertEqual(int(a[0,0,1]),95);self.assertEqual(int(a[0,0,3]),110)
        self.assertTrue(np.array_equal(transform_packed(a,mirror_u=True),self.p))
    def test_rotation_turns_vector(self):
        a=transform_packed(self.p,90)
        self.assertEqual(a[0,0].tolist(),[80,145,90,160])
    def test_narrow_protection_survives_downsample(self):
        mask=np.zeros((8,8),bool);mask[3,3]=True
        self.assertEqual(int(conservative_mask(mask,(4,4)).sum()),1)
        self.assertTrue(conservative_mask(mask,(1,1))[0,0])
    def test_weighted_patch_preserves_rb_inside(self):
        mask=np.zeros((8,8),np.uint8);mask[:4,:4]=255
        a,c=downsample_patch(self.p,mask,(4,4))
        self.assertTrue(np.all(a[c>0,0]==80));self.assertTrue(np.all(a[c>0,2]==90))
        self.assertFalse(np.array_equal(a[...,3],c))
    def test_same_grid_is_exact(self):
        c=np.full((8,8),255,np.uint8)
        a,b=downsample_patch(self.p,c,(8,8))
        self.assertTrue(np.array_equal(a,self.p));self.assertTrue(np.array_equal(b,c))
    def test_anisotropic_grain_is_not_silent(self):
        with self.assertRaises(ValueError):downsample_patch(self.p,np.full((8,8),255,np.uint8),(4,2))
    def test_no_fake_detail_upscale(self):
        with self.assertRaises(ValueError):downsample_patch(self.p,np.full((8,8),255,np.uint8),(16,16))


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="charcoal-state-")
        self.addCleanup(self.temp.cleanup)
        self.fx=Fixture(Path(self.temp.name)/"case");self.fx.final(True)
        self.claims={c["id"]:c for c in self.fx.design["coverage"]}
    def check_views(self):
        return validate_observations(self.fx.root,self.fx.design,self.claims)
    def test_declared_readme_is_not_a_game_dependency(self):
        (self.fx.root/"README.txt").write_text("not runtime")
        self.fx.design["final_runtime_files"].append(self.fx.runtime_spec(self.fx.spec("README.txt")))
        with self.assertRaises(ValueError):audit_runtime(self.fx.root,self.fx.design)
    def test_actual_model_dependency_needs_evidence(self):
        (self.fx.root/"vehicle.bin").write_bytes(b"synthetic dependency")
        spec=self.fx.runtime_spec(self.fx.spec("vehicle.bin"));spec["kind"]="native_model_dependency"
        self.fx.design["final_runtime_files"].append(spec)
        with self.assertRaises(ValueError):audit_runtime(self.fx.root,self.fx.design)
        spec["dependency_evidence"]=self.fx.evidence
        self.assertTrue(audit_runtime(self.fx.root,self.fx.design)["runtime_identity_pass"])
    def test_complete_state_matrix(self):
        self.assertEqual(len(self.check_views()["directions"]),6)
    def test_missing_back_or_underside_rejected(self):
        self.fx.design["observation_matrix"]["views"].pop()
        with self.assertRaises(ValueError):self.check_views()
    def test_delivery_state_must_be_checked(self):
        self.fx.design["observation_matrix"]["states"][0].update(status="not_checked",reason="not available")
        with self.assertRaises(ValueError):self.check_views()
    def test_alternate_state_can_remain_explicitly_unchecked(self):
        self.fx.design["observation_matrix"]["states"].append({"id":"elevated","status":"not_checked",
            "configuration":"barrel elevated","affected_coverage":["hull"],"reason":"game not run"})
        self.assertEqual(self.check_views()["states"]["elevated"],"not_checked")
    def test_net_pattern_needs_actual_shared_users_check(self):
        self.fx.design["observation_matrix"]["dynamic_net"].update(state="target_pattern")
        with self.assertRaises(ValueError):self.check_views()
    def test_lod_scope_required(self):
        self.fx.design["observation_matrix"]["available_lods"]=[]
        with self.assertRaises(ValueError):self.check_views()
    def test_c_n_mapping_cannot_be_implicit(self):
        del self.fx.design["materials"][0]["final_samples"][0]["uv_mapping"]
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json","final")
    def test_independent_n_uv_requires_actual_geometry_record(self):
        sample=self.fx.design["materials"][0]["final_samples"][0]
        sample["uv_mapping"]["mode"]="independent_uv"
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json","final")
    def repair(self):
        return {"intent":"material_adjustment","reason":"local channel diagnosis fixture","evidence":self.fx.evidence,
            "decisions":{name:{"action":"preserve","before":self.fx.base,"after":self.fx.base,"mask":self.fx.all}
                         for name in CHANNELS}}
    def test_channel_preservation(self):
        self.assertTrue(audit_channel_repair(self.fx.root,self.repair())["passed"])
    def test_all_six_channel_decisions_required(self):
        r=self.repair();del r["decisions"]["AO"]
        with self.assertRaises(ValueError):audit_channel_repair(self.fx.root,r)
    def test_restore_compares_actual_pre_effect_source(self):
        r=self.repair();r["decisions"]["N_GA"].update(action="restore",restore_from=self.fx.base)
        self.assertTrue(audit_channel_repair(self.fx.root,r)["passed"])
        a=self.fx.color.copy();a[0,0,1]=255
        r["decisions"]["N_GA"]["after"]=self.fx.image("bad-restore.png",a)
        with self.assertRaises(ValueError):audit_channel_repair(self.fx.root,r)
    def test_repair_cannot_escape_boundary(self):
        r=self.repair();a=self.fx.color.copy();a[0,0,0]=255
        r["decisions"]["C_RGB"].update(action="modify",method="local original-color repair",
            mask=self.fx.zero,after=self.fx.image("outside.png",a))
        with self.assertRaises(ValueError):audit_channel_repair(self.fx.root,r)


if __name__=="__main__":
    unittest.main(verbosity=2)
