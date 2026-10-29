"""Schema-3 false-accept regressions and valid counterpart cases."""
from __future__ import annotations
import copy,json
from pathlib import Path
import tempfile,unittest
import numpy as np
from PIL import Image
from test_candidate import Fixture,planes
import test_deep_contracts as deep
from vehicle_review import validate_manifest
from style_quality import check_detail
from native_inventory import NativeContext
from migrate_manifest import migrate
from import_legacy_dds import convert
from test_real_regression import legacy_bytes

class Rc3Tests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="charcoal-rc3-");self.addCleanup(temp.cleanup)
        self.fx=Fixture(Path(temp.name)/"case")
    def final(self):
        self.fx.save_design()
        return validate_manifest(self.fx.root/"vehicle.json","final")
    def repairs(self):
        fx=self.fx;fx.final(True)
        bindings=json.loads((fx.root/"bindings.json").read_text())
        bindings["resources"]=[r for r in bindings["resources"] if r["role"]!="ao"]
        fx.bind=fx.json("bindings.json",bindings);fx.design["bindings"]=fx.bind
        fx.design["coverage"][0]["binding_evidence"]=fx.bind
        normal=fx.design["runtime_textures"][1]
        decisions={}
        for channel in ("C_RGB","C_A","N_R","N_B","N_GA"):
            row=fx.design["runtime_textures"][0] if channel.startswith("C_") else normal
            changed=channel in ("N_R","N_B")
            decisions[channel]={"runtime_texture_id":row["id"],"action":"modify" if changed else "preserve",
                "before":row["baseline"],"after":row["canonical"],"mask":fx.all,"method":"bounded fixture repaint",
                "postcondition":{"mode":"reference","reference":row["canonical"],"tolerance":0}}
        decisions["AO"]={"action":"absent","native_users":["plate"],"reason":"No native AO in this synthetic model","evidence":fx.evidence}
        fx.design["channel_repairs"]=[{"intent":"remove_graphic","reason":"remove old synthetic marking","evidence":fx.evidence,"decisions":decisions}]
        return decisions
    def test_bound_runtime_cleanup_passes(self):
        self.repairs();self.assertTrue(self.final()["technical_pass"])
    def test_clean_other_file_cannot_prove_runtime_cleanup(self):
        d=self.repairs();fx=self.fx
        clean=np.zeros(fx.shape+(4,),np.uint8);clean[:]=[80,128,90,128]
        spec=fx.image("different-clean.png",clean)
        d["N_R"]["before"]=spec
        with self.assertRaisesRegex(ValueError,"bind runtime"):self.final()
    def test_wrong_channel_runtime_role_rejected(self):
        d=self.repairs();d["N_R"]["runtime_texture_id"]="body-c"
        with self.assertRaisesRegex(ValueError,"matching runtime resource"):self.final()
    def test_multiple_disjoint_repairs_share_one_real_final(self):
        self.repairs();fx=self.fx;original=fx.design["channel_repairs"][0]
        result=[]
        for side in (0,1):
            repair=copy.deepcopy(original);mask=np.zeros(fx.shape,np.uint8);mask[:,side*24:(side+1)*24]=255
            spec=fx.image("repair-"+str(side)+".png",mask)
            for choice in repair["decisions"].values():
                if choice["action"]!="absent":choice["mask"]=spec
            result.append(repair)
        fx.design["channel_repairs"]=result
        self.assertTrue(self.final()["technical_pass"])
    def test_actual_change_outside_repair_union_rejected(self):
        d=self.repairs();fx=self.fx
        mask=np.zeros(fx.shape,np.uint8);mask[:,:24]=255
        spec=fx.image("half.png",mask);d["N_R"]["mask"]=spec
        with self.assertRaisesRegex(ValueError,"union of bound repairs"):self.final()
    def test_absent_channel_that_exists_in_native_slots_rejected(self):
        self.repairs();fx=self.fx;b=json.loads((fx.root/"bindings.json").read_text())
        b["resources"].append({"resource":"ao","role":"ao","alpha_semantics":"scalar_data","color_space":"linear","shader":"fixture","users":["plate"]})
        spec=fx.json("bindings.json",b);fx.design["bindings"]=spec;fx.design["coverage"][0]["binding_evidence"]=spec
        with self.assertRaisesRegex(ValueError,"declared absent exists"):self.final()
    def test_transparent_canvas_rejects_false_15px_estimate(self):
        r={"native_detail_size":[50,50],"critical_features":{"text_cap_height_px":12},"contains_text":True}
        with self.assertRaisesRegex(ValueError,"below declared budget"):check_detail(r,[[0,0],[63,0],[63,63],[0,63]],(200,200))
    def test_final_entry_rejects_transparent_canvas_text(self):
        h=deep.DeepContractTests();h.fx=self.fx;h.decorated_final();fx=self.fx
        catalog=json.loads((fx.root/"catalog.json").read_text());r=catalog["assets"][0]
        a=np.zeros((200,200,4),np.uint8);a[90:102,90:110]=255
        spec=fx.image("decal.png",a);r.update(sha256=spec["sha256"],native_detail_size=[50,50],contains_text=True,critical_features={"text_cap_height_px":12},feature_regions={"text_cap_height_px":{"bounds_px":[90,90,110,102],"axis":"y"}})
        layer=fx.design["textures"][0]["layers"][0];layer["asset"]=spec;layer["catalog"]=fx.json("catalog.json",catalog)
        with self.assertRaisesRegex(ValueError,"below declared budget"):self.final()
    def test_actual_feature_rotation_and_non_square_canvas_pass(self):
        a=np.full((20,40,4),255,np.uint8)
        r={"native_detail_size":[40,20],"critical_features":{"line_width_px":4},"contains_text":False,
           "feature_regions":{"line_width_px":{"bounds_px":[3,2,7,18],"axis":"x"}}}
        for rotation in (0,90,180,270):
            size=(40,20) if rotation in (0,180) else (20,40)
            q=[[0,0],[size[0]-1,0],[size[0]-1,size[1]-1],[0,size[1]-1]]
            report=check_detail(r,q,(40,20),rotation,source_image=Image.fromarray(a))
            self.assertGreaterEqual(report["raster_features"]["line_width_px"]["opaque_projected_extent_px"],2)
    def test_projective_horizon_rejected(self):
        r={"native_detail_size":[20,20],"critical_features":{"line_width_px":4},"contains_text":False}
        with self.assertRaises(ValueError):check_detail(r,[[0,0],[20,0],[0,20],[20,20]],(20,20))
    def test_C_one_pixel_cannot_cover_full_N_surface(self):
        fx=self.fx;fx.final(True);m=fx.design["materials"][0];mask=np.zeros(fx.shape,np.uint8);mask[0,0]=255
        m["color_samples"][0]["mask"]=fx.image("one.png",mask)
        with self.assertRaisesRegex(ValueError,"complete physical surface"):self.final()
    def test_wrong_surface_resource_rejected(self):
        fx=self.fx;fx.final(True);fx.design["materials"][0]["surfaces"][0]["normal_resource"]="body_c"
        with self.assertRaisesRegex(ValueError,"physical resource"):self.final()
    def test_complete_CN_scopes_pass(self):
        self.fx.final(True);self.assertTrue(self.final()["physical_material_scopes"])
    def test_coverage_cannot_drop_native_face(self):
        fx=self.fx;fx.final(True);p,u=planes()
        np.savez(fx.root/"subset.npz",positions=p[:1],uvs=u[:1],source_face_ids=np.array([0]))
        fx.design["coverage"][0]["geometry"]=fx.spec("subset.npz")
        with self.assertRaisesRegex(ValueError,"omits/reorders"):self.final()
    def test_declared_scene_count_is_recomputed(self):
        fx=self.fx;fx.final(True);r=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]
        proof=json.loads((fx.root/"roof-probe.json").read_text());proof.update(ink_samples=1,visible_ink_samples=1)
        r["visibility"]["probe"]=fx.json("roof-probe.json",proof)
        with self.assertRaisesRegex(ValueError,"recomputed scene"):self.final()
    def test_scene_cannot_omit_a_native_node(self):
        fx=self.fx;fx.final(True);r=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]
        scene=json.loads((fx.root/"scene.json").read_text());scene["nodes"]=[]
        r["visibility"]["scene"]=fx.json("scene.json",scene)
        with self.assertRaisesRegex(ValueError,"every native node"):self.final()
    def test_changed_attachment_scene_is_rejected(self):
        fx=self.fx;fx.final(True);r=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]
        scene=json.loads((fx.root/"scene.json").read_text());scene["attachment_state"]="different"
        r["visibility"]["scene"]=fx.json("scene.json",scene)
        with self.assertRaisesRegex(ValueError,"attachment state"):self.final()
    def equipment(self,paint):
        fx=self.fx;fx.final(paint)
        proof=fx.json("classification.json",{"unit_id":"fixture_tank","model_sha256":fx.geometry["sha256"],"equipment_source_faces":[0,1],"components":{"casing":[0,1]}})
        fx.design["sensitive_equipment"]=[{"id":"sensor","kind":"sensor","classification_evidence":proof,"coverage_id":"hull","equipment_group_ids":["armor"],
            "components":{"casing":{"state":"preserve","group_ids":["armor"]},
                          "working_face":{"state":"not_present","reason":"synthetic absent","evidence":fx.evidence},
                          "mechanism":{"state":"not_present","reason":"synthetic absent","evidence":fx.evidence}}}]
    def test_preserved_casing_cannot_change_RB(self):
        self.equipment(True)
        with self.assertRaisesRegex(ValueError,"Preserved equipment component changed"):self.final()
    def test_unchanged_equipment_passes(self):
        self.equipment(False);self.assertTrue(self.final()["equipment_pixel_protection"][0]["unchanged"])
    def test_equipment_classification_cannot_name_other_model(self):
        self.equipment(False);fx=self.fx
        spec=fx.design["sensitive_equipment"][0]["classification_evidence"];d=json.loads((fx.root/spec["file"]).read_text());d["model_sha256"]="0"*64
        fx.design["sensitive_equipment"][0]["classification_evidence"]=fx.json("classification.json",d)
        with self.assertRaisesRegex(ValueError,"current native faces/model/unit"):self.final()
    def test_migration_never_forges_a_complete_pass(self):
        fx=self.fx;fx.final(True);old=copy.deepcopy(fx.design);old["schema_version"]=2
        fx.design=migrate(old)
        with self.assertRaisesRegex(ValueError,"migration still requires"):self.final()
    def test_legacy_import_generates_verified_semantic_mips(self):
        raw,_=legacy_bytes();src=self.fx.root/"old.dds";src.write_bytes(raw)
        r=convert(src,self.fx.root/"import","normal","packed_data","linear")
        self.assertTrue(r["all_mips_exact"]);self.assertEqual(src.read_bytes(),raw)
    def test_legacy_import_rejects_packed_srgb(self):
        raw,_=legacy_bytes();src=self.fx.root/"old.dds";src.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,"shader role"):convert(src,self.fx.root/"import","normal","packed_data","srgb")

    def occlusion_fixture(self,visible=True,text=False):
        from visibility_probe import compute_visibility
        fx=self.fx;fx.final(True);p,u=planes()
        blocker=p.copy();blocker[:,:,0]=blocker[:,:,0]*.08+.51;blocker[:,:,1]=blocker[:,:,1]*.08+.41;blocker[:,:,2]=.2
        np.savez(fx.root/"scene-source.npz",positions=np.concatenate([p,blocker]),uvs=np.concatenate([u,u]),materials=np.array(["plate","plate","blocker","blocker"]),nodes=np.array(["plate","plate","blocker","blocker"]))
        model=fx.spec("scene-source.npz");fx.design["model"]=model
        contract=json.loads((fx.root/'hull-intent.json').read_text());contract['model_sha256']=model['sha256'];fx.design['coverage'][0]['scope_contract']=fx.json('hull-intent.json',contract)
        bindings=json.loads((fx.root/"bindings.json").read_text());bindings["model_sha256"]=model["sha256"]
        spec=fx.json("bindings.json",bindings);fx.design["bindings"]=spec;fx.design["coverage"][0]["binding_evidence"]=spec
        row=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0];row["source_model_sha256"]=model["sha256"]
        scene=json.loads((fx.root/"scene.json").read_text());scene["model_sha256"]=model["sha256"];scene["nodes"].append({"id":"blocker","visible":visible,"matrix":np.eye(4).tolist()})
        row["visibility"]["scene"]=fx.json("scene.json",scene)
        if text:
            mask=np.zeros((8,8),np.uint8);mask[4,4]=255;row["contains_text"]=True;row["core_text_mask"]=fx.image("core-text.png",mask)
            row["text_region_evidence"]=fx.json("text-evidence.json",{"asset_sha256":row["asset"]["sha256"],"mask_sha256":row["core_text_mask"]["sha256"]})
        native=NativeContext(fx.root,fx.design)
        result=compute_visibility(fx.root,row,native,verify_receipt=False)
        row["visibility"]["probe"]=fx.json("roof-probe.json",result)
        return result
    def test_actual_core_text_obstruction_rejected_even_when_group_passes(self):
        result=self.occlusion_fixture(text=True)
        self.assertGreater(result["visible_ink_samples"]/result["ink_samples"],.95)
        self.assertEqual(result["visible_text_samples"],0)
        with self.assertRaisesRegex(ValueError,"Core warning text"):self.final()
    def test_hidden_attachment_does_not_occlude_current_scene(self):
        result=self.occlusion_fixture(visible=False,text=True)
        self.assertEqual(result["visible_text_samples"],1);self.assertTrue(self.final()["technical_pass"])
    def test_opaque_occluder_counts_are_real(self):
        result=self.occlusion_fixture();self.assertEqual(result["visible_ink_samples"],63)
        self.assertTrue(self.final()["technical_pass"])
    def test_material_different_resolution_same_native_faces(self):
        from ground_dds import semantic_mips
        from dds_variant import write_rgba8_mips
        fx=self.fx;fx.final(True);m=fx.design["materials"][0];n=m["final_samples"][0];row=fx.design["runtime_textures"][1]
        before=np.full((16,24,4),[40,128,50,128],np.uint8);after=np.full((16,24,4),[80,128,90,128],np.uint8)
        b=fx.image("small-before.png",before);a=fx.image("small-after.png",after)
        write_rgba8_mips(fx.root/"normal.dds",semantic_mips(Image.fromarray(after),"packed_data","linear"),"data")
        dds=fx.spec("normal.dds");row.update(baseline=b,canonical=a,dds=dds)
        n.update(before_n=b,final_n=a,final_n_dds=dds,mask=fx.image("small-mask.png",np.full((16,24),255,np.uint8)))
        fx.design["final_runtime_files"][1]=fx.runtime_spec(dds)
        self.assertTrue(self.final()["technical_pass"])
    def test_independent_native_uv_mapping_is_verified(self):
        fx=self.fx;fx.final(True);p,u=planes();normal_uv=u.copy();normal_uv[:,:,0]=1-normal_uv[:,:,0]
        np.savez(fx.root/"independent-source.npz",positions=p,uvs=u,uvs_normal=normal_uv)
        model=fx.spec("independent-source.npz");fx.design["model"]=model
        contract=json.loads((fx.root/'hull-intent.json').read_text());contract['model_sha256']=model['sha256'];fx.design['coverage'][0]['scope_contract']=fx.json('hull-intent.json',contract)
        b=json.loads((fx.root/"bindings.json").read_text());b["model_sha256"]=model["sha256"]
        bs=fx.json("bindings.json",b);fx.design["bindings"]=bs;fx.design["coverage"][0]["binding_evidence"]=bs
        n=fx.design["materials"][0]["final_samples"][0]
        np.savez(fx.root/"normal-geometry.npz",positions=p,uvs=normal_uv,source_face_ids=np.arange(2))
        claim=copy.deepcopy(fx.design["coverage"][0]);claim.update(native_resource="body_n",geometry=fx.spec("normal-geometry.npz"))
        n["uv_mapping"].update(mode="independent_uv",normal_coverage=fx.json("normal-coverage.json",claim))
        row=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0];row["source_model_sha256"]=model["sha256"]
        scene=json.loads((fx.root/"scene.json").read_text());scene["model_sha256"]=model["sha256"];row["visibility"]["scene"]=fx.json("scene.json",scene)
        from visibility_probe import compute_visibility
        proof=compute_visibility(fx.root,row,NativeContext(fx.root,fx.design),verify_receipt=False);row["visibility"]["probe"]=fx.json("roof-probe.json",proof)
        self.assertTrue(self.final()["technical_pass"])
        n["uv_mapping"]["mode"]="same_native_uv"
        with self.assertRaisesRegex(ValueError,"Independent native UV"):self.final()

    def test_BC7_actual_opaque_tail_decodes_every_mip(self):
        from dds_variant import decode_mips
        path=Path(__file__).parent/"fixtures/rc3/bc7-opaque-tail.dds"
        provenance=json.loads(path.with_name("bc7-provenance.json").read_text())
        meta,mips=decode_mips(path)
        self.assertEqual(meta["dxgi"],99);self.assertEqual(len(mips),2)
        for actual,expected in zip(mips,provenance["expected_rgba"]):np.testing.assert_array_equal(actual,np.array(expected,np.uint8))
    def test_opaque_color_alpha_mode_is_accepted_only_for_opaque_pixels(self):
        import struct
        from runtime_validation import audit_encoding
        fx=self.fx;fx.final();row=fx.design["runtime_textures"][0];p=fx.root/row["dds"]["file"]
        raw=bytearray(p.read_bytes());struct.pack_into("<I",raw,144,3);p.write_bytes(raw);row["dds"]=fx.spec(p.name)
        self.assertEqual(audit_encoding(fx.root,row)["role"],"color")
        raw[148+3]=254;p.write_bytes(raw);row["dds"]=fx.spec(p.name)
        with self.assertRaisesRegex(ValueError,"nonopaque decoded"):audit_encoding(fx.root,row)
    def test_editor_rounding_requires_actual_fractional_alpha_and_bound_receipt(self):
        from compositing_contract import audit_composite
        fx=self.fx;expected=np.full((2,2,4),[34,34,34,255],np.uint8);actual=expected.copy();actual[0,0,0]+=1
        layer=np.full((2,2,4),[34,34,34,0],np.uint8);layer[0,0,3]=128
        rgba=fx.image("fractional.png",layer);canonical=fx.image("editor.png",actual)
        receipt=fx.json("editor-receipt.json",{"engine":"Composa","version":"1.4.0","canonical_sha256":canonical["sha256"],"layer_sha256":[rgba["sha256"]],"saved_export":canonical,"reopened_export":canonical})
        texture={"layers":[{"rgba":rgba}],"compositing":{"mode":"composa_normal_u8","receipt":receipt}}
        self.assertEqual(audit_composite(fx.root,texture,expected,actual,canonical)["different_pixels"],1)
        actual[1,1,0]+=1;canonical=fx.image("editor.png",actual)
        proof=json.loads((fx.root/"editor-receipt.json").read_text());proof.update(canonical_sha256=canonical["sha256"],saved_export=canonical,reopened_export=canonical)
        texture["compositing"]["receipt"]=fx.json("editor-receipt.json",proof)
        with self.assertRaisesRegex(ValueError,"fractional-Alpha"):audit_composite(fx.root,texture,expected,actual,canonical)
    def test_editor_rounding_is_not_an_implicit_global_tolerance(self):
        from compositing_contract import audit_composite
        fx=self.fx;a=np.full((2,2,4),255,np.uint8);b=a.copy();b[0,0,0]-=1
        with self.assertRaisesRegex(ValueError,"reviewed base"):audit_composite(fx.root,{"layers":[]},a,b,fx.image("c.png",b))

    def test_all_transfer_eligible_bundled_assets_have_verified_pixel_regions(self):
        from asset_pack import catalog_file
        path=catalog_file();root=path.parent;catalog=json.loads(path.read_text(encoding="utf-8"));count=0
        for record in catalog["assets"]:
            if "style_transfer" not in record.get("allowed_modes",[]) or not record.get("critical_features"):continue
            with Image.open(root/record["file"]) as im:
                w,h=im.size
                report=check_detail(record,[[0,0],[w-1,0],[w-1,h-1],[0,h-1]],im.size,source_image=im)
            self.assertTrue(report["raster_features"]);count+=1
        self.assertEqual(count,18)
    def test_preserve_material_region_requires_full_physical_scope(self):
        fx=self.fx;fx.final(False);m=fx.design["materials"][0]
        m.update(state="preserve",reason="Keep entire native plate",preserve_samples=[{"runtime_texture_id":"body-c","coverage_id":"hull","group_ids":["armor"],"native_resource":"body_c","mask":fx.all}])
        m.pop("parameters",None)
        self.assertTrue(self.final()["technical_pass"])
        one=np.zeros(fx.shape,np.uint8);one[0,0]=255;m["preserve_samples"][0]["mask"]=fx.image("one-preserved.png",one)
        with self.assertRaisesRegex(ValueError,"complete physical surface"):self.final()

if __name__=="__main__":unittest.main()
