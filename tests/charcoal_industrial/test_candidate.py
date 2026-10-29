"""Deterministic negative and integration tests; all imagery is synthetic, never artwork approval."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import numpy as np
from PIL import Image

ROOT=(Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0,str(ROOT/"scripts"))
from skill_contract import identity, policy, sha, material_parameters
from reference_contract import check_roles, check_base_color
from basecoat import neutral_basecoat
from surface_coverage import audit
from hd_antislip import make_patch, verify_patch, resolve_parameters
from material_parameters import apply_parameters, audit_parameters
from uv_coverage import check as check_uv
from vehicle_review import validate_manifest
from compose_native import compose
from package_budget import inspect_package
from dds_variant import write_rgba8_mips
from texture_semantics import iter_mipmaps
from runtime_validation import audit_runtime, audit_delivery


def planes(alias=False):
    p=np.array([[[0,0,0],[1,0,0],[1,1,0]],[[0,0,0],[1,1,0],[0,1,0]]],float)
    uv=p[:,:,:2].copy()
    if alias:
        p=np.concatenate((p,p+np.array([0,0,1])),axis=0)
        uv=np.concatenate((uv,uv),axis=0)
    return p,uv


def group(name="armor", faces=None, role="armor_main"):
    return {"id":name,"faces":[0,1] if faces is None else faces,"role":role,"evidence":"synthetic face classification"}


def material(role="body", **params):
    result={"role":role,"state":"paint","reason":"synthetic material test","color_mode":"neutral",
            "packed_n_semantics":policy()["materials"]["packed_n_semantics"],"shader_evidence":"synthetic packed layout",
            "parameters":{"color_srgb":[34]*3,"inverse_roughness_center":80,"metallic":90}}
    result["parameters"].update(params)
    return result


class Fixture:
    def __init__(self,root):
        self.root=root;root.mkdir(parents=True)
        self.shape=(32,48)
        self.color=np.zeros(self.shape+(4,),np.uint8);self.color[...,3]=255
        for i,tone in enumerate((34,47,65)):self.color[:,i*16:(i+1)*16,:3]=tone
        self.base=self.image("base.png",self.color)
        allmask=np.ones(self.shape,np.uint8)*255;zero=np.zeros(self.shape,np.uint8)
        self.all=self.image("all.png",allmask);self.zero=self.image("zero.png",zero)
        self.bind=self.json("bindings.json",{"fixture":"synthetic native shader/user inventory"})
        self.evidence=self.json("observation.json",{"fixture":"synthetic evidence, not a rendered vehicle"})
        p,u=planes();np.savez(root/"geometry.npz",positions=p,uvs=u,source_face_ids=np.arange(len(p)))
        self.geometry=self.spec("geometry.npz")
        self.bind=self.json("bindings.json",{"schema_version":1,"unit_id":"fixture_tank","model_sha256":self.geometry["sha256"],
            "resources":[{"resource":resource,"role":role,"alpha_semantics":semantics,"color_space":space,
                          "shader":"synthetic_native_shader","users":["plate"]}
                         for resource,role,semantics,space in [("body_c","color","fixed_rgb","srgb"),
                         ("body_n","normal","packed_data","linear"),("body_ao","ao","scalar_data","linear")]]})
        regions=[]
        for i,role in enumerate("ABC"):
            mask=np.zeros(self.shape,np.uint8);mask[:,i*16:(i+1)*16]=255
            regions.append({"id":role,"role":role,"mask":self.image(role+".png",mask)})
        coverage={"id":"hull","texture":"body","native_resource":"body_c","geometry":self.geometry,"binding_evidence":self.bind,
                  "all_texture_users_included":True,"paint_mask":self.all,
                  "face_groups":[group()],"target_groups":["armor"],"accepted_shared":{},
                  "layer_role":"decal","mode":"partial"}
        self.design={"schema_version":3,"policy_version":identity()["version"],"vehicle":"Synthetic tank",
                     "unit_id":"fixture_tank","attachment_state":"none","model":self.geometry,"bindings":self.bind,
                     "textures":[{"id":"body","base_c":self.base,"base_paint_mask":self.all,"paint_regions":regions}],
                     "coverage":[coverage],"zones":{},"materials":[],"graphics":[],"reviews":{}}
        for zone in policy()["composition"]["zones"]:
            self.design["zones"][zone]={"state":"designed","large_geometry":"three broad synthetic plates",
                "quiet_area":"unmarked panel center","focal_point":"local test marking",
                "pattern_scale":"small side band and larger local focus","material_contrast":"matte body and deep housing",
                "coverage_ids":["hull"]}
        for role in policy()["materials"]["roles"]:
            self.design["materials"].append({"role":role,"state":"not_applicable","reason":"synthetic geometry has no physical component","evidence":self.evidence})
        for role in policy()["graphic_roles"]["required"]:
            self.design["graphics"].append({"id":role,"role":role,"layer_role":"decal","coverage_id":"hull","purpose":"synthetic role on carrier"})
        self.design["reviews"]["base_only"]={"state":"checked_local","observation":"three geometric regions visible without decoration",
            "lighting_id":"synthetic unlit identity","view":"fixture top","evidence":[self.evidence],
            "hidden_layers":["honeycomb","decals","micro_accents"]}
        self.design["part_layouts"]={}
        for name,recipe in policy()["part_recipes"].items():
            self.design["part_layouts"][name]={"state":"apply_default","reason":"synthetic default recipe test",
                "elements":recipe["default_elements"],"coverage_ids":["hull"],"visibility_checked":True,
                "evidence":self.evidence,"identity_text":"SYNTHETIC","identity_unit_id":"fixture_tank",
                "layout":"synthetic centered text and paired stripes","label_texts":["NO STEP"],
                "carrier_size_m":[1,1],"graphic_size_m":[.8,.8],"margins_m":[.1,.1,.1,.1],
                "rotation_deg":0,"readable_at_normal_view":True,"accent_component":"housing",
                "components":{part:{"state":"not_applicable","reason":"synthetic geometry fixture lacks actual guns","evidence":self.evidence}
                              for part in ("housing","gun_body","stock","ammunition")}}
        roof_asset=np.full((8,8,4),255,np.uint8)
        roof_art=self.image("roof-source.png",roof_asset)
        scene=self.json("scene.json",{"schema_version":1,"model_sha256":self.geometry["sha256"],"attachment_state":"none","pose_id":"default","lod":"lod0","nodes":[{"id":"plate","visible":True,"matrix":np.eye(4).tolist()}],"camera":{"kind":"orthographic","direction":[0,0,-1]}})
        probe=self.json("roof-probe.json",{"source_model_sha256":self.geometry["sha256"],"geometry_sha256":self.geometry["sha256"],
            "center_uv_m":[.5,.5],"graphic_size_m":[.8,.8],"rotation_deg":0,"ink_samples":64,"visible_ink_samples":64,"text_samples":0,"visible_text_samples":0,"scene_sha256":scene["sha256"],"frame":{"origin":[0,0,0],"u":[1,0,0],"v":[0,1,0]},"asset_sha256":roof_art["sha256"]})
        self.design["part_layouts"]["roof_warning"].update(required_instances=["main-warning"],placement_checks=[{
            "id":"main-warning","mode":"actual_ink","contains_text":False,"source_model_sha256":self.geometry["sha256"],
            "geometry":self.geometry,"faces":[0,1],"asset":roof_art,"frame":{"origin":[0,0,0],"u":[1,0,0],"v":[0,1,0]},
            "center_uv_m":[.5,.5],"graphic_size_m":[.8,.8],"rotation_deg":0,"scope_polygon_uv_m":[[0,0],[1,0],[1,1],[0,1]],
            "depth_interval_m":[-.002,.002],"minimum_margin_m":.05,
            "target_fill":{"min":.3,"max":.9,"reason":"synthetic panel group scale"},
            "visibility":{"scene":scene,"probe":probe,"minimum_visible_fraction":.95}}])
        self.save_design()

    def spec(self,name):
        return {"file":name,"sha256":sha(self.root/name)}

    def json(self,name,data):
        (self.root/name).write_text(json.dumps(data),encoding="utf-8");return self.spec(name)

    def image(self,name,array):
        if name.endswith(".dds"):
            normal="normal" in name or name.endswith("-n.dds")
            semantics="packed_data" if normal else "fixed_rgb"
            mips=[np.array(m) for m in iter_mipmaps(Image.fromarray(array),semantics,"linear" if normal else "srgb")]
            write_rgba8_mips(self.root/name,mips,"data" if normal else "color")
        else:
            Image.fromarray(array).save(self.root/name)
        return self.spec(name)

    def runtime_spec(self,spec):
        return {**spec,"package_path":"Synthetic/"+spec["file"]}

    def save_design(self):
        # Synthetic observation fixtures describe the current synthetic test inputs.
        from visual_evidence import artifact_binding
        def render_receipt(record,base_only):
            binding=artifact_binding(self.design,base_only)
            script=self.root/'synthetic-render.py'
            script.write_text('# Synthetic fixture of evidence linkage; not an actual vehicle render.\n',encoding='utf8')
            name='base-render.json' if base_only else 'final-render.json'
            proof={'model_sha256':binding['model_sha256'],'bound_base_colors' if base_only else 'bound_runtime_dds':binding['texture_sha256'],
                'exit_code':0,'script':self.spec(script.name),'run_log':self.evidence,
                'renders':[{**entry,'texture_kind':binding['texture_kind']} for entry in record.get('images',[])]}
            return self.json(name,proof)
        for name,record in self.design.get('reviews',{}).items():
            record.setdefault('verdict','satisfactory');record.setdefault('images',[self.base])
            if name=='base_only' or self.design.get('runtime_textures'):
                record['artifact_binding']=artifact_binding(self.design,name=='base_only')
                record['render_receipt']=render_receipt(record,name=='base_only')
        for view in self.design.get('observation_matrix',{}).get('views',[]):
            view.setdefault('verdict','satisfactory');view.setdefault('images',[self.base])
            view['artifact_binding']=artifact_binding(self.design)
            view['render_receipt']=render_receipt(view,False)
        for claim in self.design.get('coverage',[]):
            if 'scope_contract' not in claim:
                with np.load(self.root/claim['geometry']['file']) as g:ids=g['source_face_ids'].tolist()
                local=sorted({f for group in claim['face_groups'] if group['id'] in claim['target_groups'] for f in group['faces']})
                claim['scope_contract']=self.json(claim['id']+'-intent.json',{'model_sha256':self.design['model']['sha256'],
                    'native_resource':claim['native_resource'],'layer_role':claim['layer_role'],'mode':claim['mode'],
                    'target_source_faces':[ids[f] for f in local],'reason':'Synthetic independently declared complete plate intent'})
        # The synthetic model's source export is explicit; production must use
        # the original exporter inventory, never derive authority from claims.
        binding_path=self.root/self.design['bindings']['file']
        bindings=json.loads(binding_path.read_text())
        from native_inventory import source_geometry
        names=sorted({u for row in bindings['resources'] for u in row['users']}|set(source_geometry(self.root/self.design['model']['file'])['materials']));source=[]
        for name in names:
            slots=[None]*4;shader='synthetic_native_shader'
            for row in bindings['resources']:
                if name in row['users']:
                    slots[{'color':0,'normal':2,'ao':3}[row['role']]]=row['resource']+'*';shader=row['shader']
            source.append({'obj_name':name,'shader':shader,'texture_slots':slots})
        bindings['source_inventory']=self.json('exported-materials.json',{'materials':source})
        self.bind=self.json(self.design['bindings']['file'],bindings);self.design['bindings']=self.bind
        for claim in self.design.get('coverage',[]):claim['binding_evidence']=self.bind
        return self.json("vehicle.json",self.design)

    def make_plan(self):
        asset=np.full((8,8,4),255,np.uint8)
        asset[:,:,:3]=[200,140,40]
        decal=self.image("decal.png",asset)
        record={"id":"mark","kind":"transparent_element","allowed_modes":["style_transfer","source_reproduction"],
            "origin_class":"target_authored","source_surface_content":False,"lighting_content":"flat_graphic",
            "graphic_validation":{"state":"checked_local","evidence":self.evidence},"trial_eligible":True,
            "contains_text":False,"native_detail_size":[8,8],"critical_features":{"line_width_px":3},"feature_regions":{"line_width_px":{"bounds_px":[0,0,3,8],"axis":"x"}},
            "sha256":decal["sha256"]}
        catalog=self.json("catalog.json",{"schema_version":3,"assets":[record]})
        model_view=self.json("model-view.json",{"test":"synthetic model view"})
        uv_view=self.image("uv-view.png",np.zeros((8,8,3),np.uint8))
        study=self.json("study.json",{"schema_version":1,"source_identity":{"vehicle":"Synthetic source"},
            "source_model":self.geometry,"material_binding":self.bind,"regions":[{"id":"source-region","state":"checked_local",
            "semantic_role":"synthetic test module","observed_parts":["plate"],"resource":"body","model_view":model_view,
            "uv_view":uv_view,"source_texture":decal,"uv_region":{"coordinate_space":"image_pixels_top_left","image_size":[8,8],"box_xyxy":[0,0,8,8]},
            "orientation":{"state":"checked_local"},"sharing":{"state":"checked_local","kind":"unique"},
            "observation":"synthetic paired geometry/UV fixture"}]})
        self.profile={"schema_version":1,"vehicle":"Synthetic tank","unit_id":"fixture_tank","uv_evidence":"synthetic fixture",
            "textures":{"body":{"file":self.base["file"],"sha256":self.base["sha256"],"alpha_semantics":"fixed_rgb","color_space":"srgb",
                "paint_mask":self.all,"protected_mask":self.zero}},
            "surfaces":[{"id":"hull","texture":"body","verified":True,"evidence":"synthetic native face",
                "sharing":"unique","polygon_px":[[0,0],[47,0],[47,31],[0,31]],"rotation_deg":0,
                "planar":True,"coverage_id":"hull"}]}
        profile=self.json("profile.json",self.profile)
        self.plan={"schema_version":4,"intent":"style_transfer","source_study":study,"catalog":"catalog.json",
            "catalog_sha256":catalog["sha256"],"profile_sha256":profile["sha256"],"vehicle_design":self.save_design(),
            "placements":[{"id":"mark","surface":"hull","reason":"synthetic bounded module","asset_id":"mark",
                "kind":"transparent_element","graphic_id":"warning","layer_role":"decal","asset":"decal.png","asset_sha256":decal["sha256"],
                "quad_px":[[10,10],[17,10],[17,17],[10,17]],"source_region":"source-region",
                "target_correspondence":{"role":"mark","reason":"test adapted marking","surface":"hull"}}]}
        self.json("plan.json",self.plan)
        return self.root/"profile.json",self.root/"plan.json"

    def final(self, paint_material=False):
        texture=self.design["textures"][0]
        texture.update(before_c=self.base,final_c=self.base,occupied_mask=self.all,edit_mask=self.all,
                       protected_mask=self.zero,shared_mask=self.zero,decoration_mask=self.zero,
                       final_paint_regions=[{**r,"base_region_id":r["id"]} for r in texture["paint_regions"]],layers=[],
                       final_dds=self.image("body.dds",self.color))
        for name in ("whole_vehicle","surface_finish","final_dds"):
            self.design["reviews"][name]={"state":"checked_local","observation":"synthetic audit fixture",
                "lighting_id":"fixture","view":"fixture","evidence":[self.evidence],
                "distances":["far","medium","near"],"rotating_light_checked":True,"all_mips_rebound":True}
        (self.root/"fixture.blk").write_text('name:t="synthetic fixture"\nreplace_tex{ from:t="body_c*" to:t="body.dds" }')
        self.design["final_runtime_files"]=[self.runtime_spec(texture["final_dds"])]
        self.design["runtime_textures"]=[{"id":"body-c","native_resources":["body_c"],"dds":texture["final_dds"],"role":"color","alpha_semantics":"fixed_rgb",
            "color_space":"srgb","state":"modified","baseline":self.base,"canonical":self.base,"encoding":{"mode":"exact"}}]
        self.design["graphics"]=[]
        self.design["graphic_omissions"]={r:"synthetic material fixture has no physical graphics" for r in policy()["graphic_roles"]["required"]}
        self.design["observation_matrix"]={"delivery_state":"default",
            "states":[{"id":"default","status":"checked","configuration":"synthetic fixed plate","affected_coverage":["hull"],"evidence":self.evidence}],
            "views":[{"direction":d,"state_id":"default","status":"checked","observation":"synthetic state/matrix test","coverage_ids":["hull"],"evidence":self.evidence}
                     for d in ("front","rear","left","right","top","lower_visible")],
            "paired_surfaces":[],"dynamic_net":{"state":"absent","reason":"no native net in synthetic fixture","evidence":self.evidence},
            "available_lods":[{"id":"lod0","status":"checked","observation":"synthetic single mesh","evidence":self.evidence}]}
        if paint_material:
            n=np.zeros(self.shape+(4,),np.uint8);n[:]=[40,128,50,128]
            after=n.copy();after[...,0]=80;after[...,2]=90
            record=material();record["evidence"]=self.evidence
            record["color_mode"]="paint_roles";del record["parameters"]["color_srgb"]
            record["parameters"]["paint_roles"]=["A","B","C"]
            record["surfaces"]=[{"id":"body-surface","coverage_id":"hull","group_ids":["armor"],"color_resource":"body_c","normal_resource":"body_n"}]
            record["color_samples"]=[{"surface_id":"body-surface","texture":"body","mask":self.all}]
            record["final_samples"]=[{"surface_id":"body-surface","runtime_texture_id":"body-n","coverage_id":"hull","before_n":self.image("before-n.png",n),
                "final_n":self.image("after-n.png",after),"final_n_dds":self.image("normal.dds",after),"mask":self.all,"uv_mapping":{"mode":"same_native_uv","color_texture":"body","evidence":self.evidence}}]
            self.design["materials"][0]=record
            sample=record["final_samples"][0]
            self.design["final_runtime_files"].append(self.runtime_spec(sample["final_n_dds"]))
            self.design["runtime_textures"].append({"id":"body-n","native_resources":["body_n"],"dds":sample["final_n_dds"],"role":"normal","alpha_semantics":"packed_data",
                "color_space":"linear","state":"modified","baseline":sample["before_n"],"canonical":sample["final_n"],"encoding":{"mode":"exact"}})
            with (self.root/"fixture.blk").open("a") as stream:stream.write('\nreplace_tex{ from:t="body_n*" to:t="normal.dds" }')
        self.design["final_runtime_files"].append(self.runtime_spec(self.spec("fixture.blk")))
        self.save_design()


class PolicyTests(unittest.TestCase):
    def test_optional_circuit_and_pixels(self):
        roles=[{"role":r,"pixels":1} for r in policy()["graphic_roles"]["required"]]
        self.assertNotIn("circuit",check_roles(roles)["observed_roles"])
    def test_missing_primary_role_fails(self):
        with self.assertRaises(ValueError):check_roles([])
    def test_explicit_omissions(self):
        self.assertEqual(check_roles([],dict.fromkeys(policy()["graphic_roles"]["required"],"physical carrier unavailable"))["observed_roles"],[])
    def test_unknown_role_fails(self):
        with self.assertRaises(ValueError):check_roles([{"role":"typo","pixels":1}])
    def test_contradictory_omission(self):
        with self.assertRaises(ValueError):check_roles([{"role":"warning","pixels":1}],{"warning":"absent"})
    def test_three_gray_roles(self):
        for role,tone in zip("ABC",(34,47,65)):
            self.assertEqual(check_base_color(np.full((8,8,3),tone,np.uint8),np.ones((8,8),bool),role=role)["role"],role)
    def test_basecoat_uses_same_policy(self):
        for role,tone in zip("ABC",(34,47,65)):
            out=neutral_basecoat(np.full((8,8,4),128,np.uint8),np.ones((8,8),bool),role=role)
            self.assertTrue(np.all(out[...,:3]==tone));self.assertTrue(np.all(out[...,3]==128))
    def test_cold_gray_fails(self):
        with self.assertRaises(ValueError):check_base_color(np.tile([25,27,29],(8,8,1)).astype("uint8"),np.ones((8,8),bool),reference=[27]*3,override_reason="target paint")
    def test_override_reason_required(self):
        with self.assertRaises(ValueError):check_base_color(np.full((8,8,3),40,np.uint8),np.ones((8,8),bool),reference=[40]*3)
    def test_explicit_override(self):
        self.assertEqual(check_base_color(np.full((8,8,3),40,np.uint8),np.ones((8,8),bool),reference=[40]*3,override_reason="target exposure calibration")["target_rgb"],[40]*3)
    def test_nan_tolerance(self):
        with self.assertRaises(ValueError):check_base_color(np.full((8,8,3),34,np.uint8),np.ones((8,8),bool),max_median_delta=float("nan"))
    def test_material_shader_required(self):
        r=material();r["packed_n_semantics"]={}
        with self.assertRaises(ValueError):material_parameters(r)
    def test_material_neutral_required(self):
        with self.assertRaises(ValueError):material_parameters(material(color_srgb=[25,27,29]))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.p,self.uv=planes();self.mask=np.ones((16,16),bool)
    def run_audit(self,**kw):
        return audit(self.p,self.uv,kw.pop("mask",self.mask),kw.pop("groups",[group()]),["armor"],**kw)
    def test_complete(self):self.assertTrue(self.run_audit()["technical_pass"])
    def test_one_texel_missing_fails(self):
        m=self.mask.copy();m[0,0]=False
        r=self.run_audit(mask=m)
        self.assertFalse(r["technical_pass"]);self.assertEqual(r["counts"]["missing_target_texels"],1)
    def test_subpixel_glass_alias_rejected(self):
        p,u=planes()
        p=np.concatenate((p,np.array([[[0,0,1],[1,0,1],[0,1,1]]])),axis=0)
        u=np.concatenate((u,np.array([[[.499,.499],[.501,.499],[.499,.501]]])),axis=0)
        r=audit(p,u,self.mask,[group(),group("tiny_glass",[2],"glass")],["armor"])
        self.assertFalse(r["technical_pass"]);self.assertEqual(r["undersampled_alias_faces"],[2])
    def test_partial_decal_allowed(self):
        m=np.zeros_like(self.mask);m[2:4,2:4]=True
        self.assertTrue(self.run_audit(mask=m,mode="partial",layer_role="decal")["technical_pass"])
    def test_unclassified_face_rejected(self):
        with self.assertRaises(ValueError):self.run_audit(groups=[group(faces=[0])])
    def test_overlap_group_rejected(self):
        with self.assertRaises(ValueError):self.run_audit(groups=[group(),group("other",[1])])
    def test_honey_on_louver_rejected(self):
        with self.assertRaises(ValueError):self.run_audit(groups=[group(role="louver")])
    def test_shared_alias_fails(self):
        p,uv=planes(True)
        self.assertFalse(audit(p,uv,self.mask,[group(),group("peer",[2,3])],["armor"])["technical_pass"])
    def test_reviewed_shared_allowed(self):
        p,uv=planes(True)
        self.assertTrue(audit(p,uv,self.mask,[group(),group("peer",[2,3])],["armor"],{"peer":"same paint accepted on shared rear plate"})["technical_pass"])
    def test_glass_alias_cannot_be_accepted(self):
        p,uv=planes(True)
        with self.assertRaises(ValueError):audit(p,uv,self.mask,[group(),group("glass",[2,3],"glass")],["armor"],{"glass":"do not hide error"})
    def test_degenerate_uv_rejected(self):
        uv=self.uv.copy();uv[1]=0
        with self.assertRaises(ValueError):audit(self.p,uv,self.mask,[group()],["armor"])
    def test_tile_span_not_silently_skipped(self):
        uv=self.uv*5
        with self.assertRaises(ValueError):audit(self.p,uv,self.mask,[group()],["armor"])
    def test_zero_sample_narrow_face_fails(self):
        uv=self.uv*.00001
        r=audit(self.p,uv,self.mask,[group()],["armor"])
        self.assertFalse(r["technical_pass"])
    def test_uv_outside_edit_detected(self):
        b=np.zeros((4,4,4),np.uint8);a=b.copy();a[3,3,0]=1
        p=np.zeros((4,4),bool);p[0]=True
        r,_=check_uv(np.ones((4,4),bool),p,~p,b,a,shared=np.zeros((4,4),bool))
        self.assertFalse(r["technical_pass"]);self.assertEqual(r["counts"]["outside_paint_changed"],1)
    def test_uv_unknown_shared_not_pass(self):
        b=np.zeros((4,4,4),np.uint8);ones=np.ones((4,4),bool)
        self.assertFalse(check_uv(ones,ones,~ones,b,b)[0]["technical_pass"])
    def test_uv_alpha_data_protected(self):
        b=np.zeros((4,4,4),np.uint8);a=b.copy();a[0,0,3]=255;ones=np.ones((4,4),bool)
        self.assertFalse(check_uv(ones,ones,~ones,b,a,shared=~ones)[0]["technical_pass"])


class MaterialTests(unittest.TestCase):
    def test_default_neutral(self):self.assertEqual(resolve_parameters()["color_srgb"],[27]*3)
    def test_physical_scale(self):
        self.assertEqual(resolve_parameters(grain_mm=4,texels_per_meter=1000)["grain_sigma_px"],2)
    def test_subpixel_rejected(self):
        with self.assertRaises(ValueError):resolve_parameters(.35)
    def test_required_mip_rejected(self):
        with self.assertRaises(ValueError):resolve_parameters(1,required_mip=1)
    def test_conflicting_scale_rejected(self):
        with self.assertRaises(ValueError):resolve_parameters(2,grain_mm=4,texels_per_meter=1000)
    def test_tint_reason_required(self):
        with self.assertRaises(ValueError):resolve_parameters(color=[25,27,29])
    def test_invalid_nan_rejected(self):
        with self.assertRaises(ValueError):resolve_parameters(slope=float("nan"))
    def test_native_generation_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-unit-") as tmp:
            path=Path(tmp)/"patch";make_patch(path,64,64,42,metallic=77,inverse_roughness=63)
            r=verify_patch(path);self.assertTrue(r["passed"])
            with Image.open(path/"color.png") as im:a=np.array(im)
            self.assertTrue(np.array_equal(a[...,0],a[...,2]))
    def test_corrupt_map_rejected(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-unit-") as tmp:
            path=Path(tmp)/"patch";make_patch(path,32,32,42)
            (path/"color.png").write_bytes(b"corrupt")
            with self.assertRaises(ValueError):verify_patch(path)
    def test_rb_and_protection(self):
        n=np.full((8,8,4),128,np.uint8);m=np.zeros((8,8),bool);m[2:6,2:6]=True
        out=apply_parameters(n,m,material())
        self.assertTrue(np.array_equal(n[~m],out[~m]))
        self.assertTrue(np.array_equal(n[:,:,[1,3]],out[:,:,[1,3]]))
        self.assertTrue(audit_parameters(n,out,m,material())["technical_pass"])
    def test_minority_material_outliers_rejected(self):
        n=np.zeros((8,8,4),np.uint8);n[:]=[80,128,90,128]
        after=n.copy();after[:3,:,0]=255;after[:3,:,2]=255
        r=audit_parameters(n,after,np.ones((8,8),bool),material())
        self.assertFalse(r["technical_pass"]);self.assertEqual(r["R_outlier_pixels"],24)
    def test_rnm_does_not_replace_structure(self):
        n=np.zeros((8,8,4),np.uint8);n[:]=[40,160,50,128];m=np.ones((8,8),bool)
        d=np.zeros((8,8,3),np.uint8);d[:]=[128,128,255]
        out=apply_parameters(n,m,material(),detail_normal=d,detail_coverage=np.full((8,8),255,np.uint8))
        self.assertLessEqual(abs(int(out[0,0,1])-160),1)
    def test_micro_scope_rejected(self):
        n=np.full((8,8,4),128,np.uint8);m=np.zeros((8,8),bool);m[0]=True
        with self.assertRaises(ValueError):apply_parameters(n,m,material(),detail_normal=np.full((8,8,3),128,np.uint8),detail_coverage=np.full((8,8),255,np.uint8))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="charcoal-integration-")
        self.addCleanup(self.temp.cleanup)
        self.fx=Fixture(Path(self.temp.name)/"case")
    def test_base_manifest(self):
        r=validate_manifest(self.fx.root/"vehicle.json")
        self.assertTrue(r["technical_pass"]);self.assertEqual(r["visual_approval"],"not inferred")
    def test_missing_zone_rejected(self):
        del self.fx.design["zones"]["Z6"];self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_missing_base_only_review(self):
        self.fx.design["reviews"]={};self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_missing_coverage_evidence(self):
        self.fx.design["coverage"][0]["all_texture_users_included"]=False;self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_color_mask_hole(self):
        mask=np.full(self.fx.shape,255,np.uint8);mask[0,0]=0
        self.fx.design["textures"][0]["base_paint_mask"]=self.fx.image("badmask.png",mask);self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_evidence_hash_changed(self):
        (self.fx.root/"observation.json").write_text("{}")
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_final_checks(self):
        self.fx.final(True)
        r=validate_manifest(self.fx.root/"vehicle.json","final")
        self.assertTrue(r["technical_pass"]);self.assertEqual(len(r["final_materials"]),1)
    def test_final_material_mismatch(self):
        self.fx.final(True)
        sample=self.fx.design["materials"][0]["final_samples"][0]
        a=np.zeros(self.fx.shape+(4,),np.uint8);a[:]=[80,128,220,128]
        sample["final_n"]=self.fx.image("bad-n.png",a);self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json","final")
    def test_composer_check_and_output(self):
        profile,plan=self.fx.make_plan()
        r=compose(profile,plan,None,dry=True);self.assertTrue(r["actual_layer_scope_checked"])
        out=self.fx.root/"composed";r=compose(profile,plan,out)
        self.assertTrue(r["outputs"][0]["alpha_exact"])
        with Image.open(out/"colors/body.png") as im:a=np.array(im)
        self.assertTrue(np.array_equal(a[0],self.fx.color[0]))
        self.assertFalse(np.array_equal(a,self.fx.color))
    def test_schema_two_transfer_rejected(self):
        profile,plan=self.fx.make_plan();self.fx.plan["schema_version"]=2;self.fx.json("plan.json",self.fx.plan)
        with self.assertRaises(ValueError):compose(profile,plan,None,dry=True)
    def test_wrong_vehicle_rejected(self):
        profile,plan=self.fx.make_plan()
        self.fx.design["unit_id"]="different";self.fx.plan["vehicle_design"]=self.fx.save_design();self.fx.json("plan.json",self.fx.plan)
        with self.assertRaises(ValueError):compose(profile,plan,None,dry=True)
    def test_composer_dry_checks_actual_scope(self):
        profile,plan=self.fx.make_plan()
        mask=np.zeros(self.fx.shape,np.uint8);mask[0:5,0:5]=255
        self.fx.design["coverage"][0]["paint_mask"]=self.fx.image("tiny.png",mask)
        self.fx.plan["vehicle_design"]=self.fx.save_design();self.fx.json("plan.json",self.fx.plan)
        with self.assertRaises(ValueError):compose(profile,plan,None,dry=True)
    def test_complete_surface_not_ratio(self):
        profile,plan=self.fx.make_plan()
        self.fx.design["coverage"][0]["mode"]="full_surface"
        self.fx.plan["vehicle_design"]=self.fx.save_design();self.fx.json("plan.json",self.fx.plan)
        with self.assertRaises(ValueError):compose(profile,plan,None,dry=True)
    def test_final_blue_pixels_rejected(self):
        self.fx.final()
        a=self.fx.color.copy();a[:,:,:3]=[0,0,255]
        texture=self.fx.design["textures"][0]
        texture["final_c"]=self.fx.image("blue.png",a)
        texture["final_dds"]=self.fx.image("blue.dds",a)
        self.fx.design["final_runtime_files"][0]=self.fx.runtime_spec(texture["final_dds"])
        self.fx.design["runtime_textures"][0].update(dds=texture["final_dds"],canonical=texture["final_c"])
        (self.fx.root/"fixture.blk").write_text('replace_tex{ from:t="body_c*" to:t="blue.dds" }')
        self.fx.design["final_runtime_files"][-1]=self.fx.runtime_spec(self.fx.spec("fixture.blk"))
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json","final")
    def test_decoded_pixels_must_match_dds(self):
        self.fx.final()
        a=self.fx.color.copy();a[0,0,0]+=1
        self.fx.design["textures"][0]["final_c"]=self.fx.image("different.png",a)
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json","final")
    def test_preserved_texture_without_neutral_paint(self):
        self.fx.final()
        old=self.fx.design["textures"][0]
        texture=copy.deepcopy(old)
        texture.update(id="preserved",base_paint_mask=self.fx.zero,paint_regions=[],final_paint_regions=[],
                       edit_mask=self.fx.zero,protected_mask=self.fx.all,no_neutral_paint_reason="native glass retained")
        self.fx.design["textures"].append(texture);self.fx.save_design()
        self.assertTrue(validate_manifest(self.fx.root/"vehicle.json","final")["technical_pass"])
    def test_missing_part_default_rejected(self):
        del self.fx.design["part_layouts"]["lower_glacis"];self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_roof_group_cannot_be_only_a_label(self):
        self.fx.design["part_layouts"]["roof_warning"]["elements"]=["centered_legible_text"]
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_roof_group_physical_fit(self):
        self.fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]["graphic_size_m"]=[2,2]
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_blowout_function_cannot_be_invented(self):
        self.fx.design["part_layouts"]["roof_warning"]["label_texts"]=["BLOW-OUT"]
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_gun_group_cannot_stand_in_for_all_parts(self):
        components=self.fx.design["part_layouts"]["machine_gun"]["components"]
        for name in ("housing","gun_body"):
            components[name]={"state":"paint","coverage_id":"hull","face_group_ids":["armor"]}
        self.fx.save_design()
        with self.assertRaises(ValueError):validate_manifest(self.fx.root/"vehicle.json")
    def test_front_occlusion_can_use_nontext(self):
        part=self.fx.design["part_layouts"]["lower_glacis"]
        part.update(state="adapted",elements=["nontext_motif"],
                    replacements={"vehicle_wordmark":"native spare tracks obscure text; use visible nontext motif"})
        self.fx.save_design()
        self.assertTrue(validate_manifest(self.fx.root/"vehicle.json")["technical_pass"])
    def test_package_crc_and_paths(self):
        path=self.fx.root/"valid.zip"
        with zipfile.ZipFile(path,"w") as z:z.writestr("skin/test.blk","data")
        self.assertTrue(inspect_package(path)["payload_verified"])
        path=self.fx.root/"bad.zip"
        with zipfile.ZipFile(path,"w") as z:z.writestr("../bad","data")
        self.assertFalse(inspect_package(path)["passed"])


if __name__=="__main__":
    unittest.main(verbosity=2)
