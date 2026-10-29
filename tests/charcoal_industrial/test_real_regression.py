"""Real retained Type 10/Merkava snapshots plus strict local regression guards."""
from pathlib import Path
from io import BytesIO
import hashlib,json,struct,sys,tempfile,unittest,zipfile
import numpy as np
from PIL import Image
ROOT=(Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0,str(ROOT/"scripts"))
from layout_fit import measure_ink_fit,validate_layout_checks
from dds_snapshot import inspect_stream,read_top
from dds_variant import mip_sizes
from texture_semantics import resize_texture
from production_checks import audit_channel_repair,validate_sensitive_equipment
from surface_coverage import audit
from input_snapshot import snapshot_folder,snapshot_zip,compare_snapshots
from skill_contract import sha,read_json
from vehicle_review import validate_manifest
from test_candidate import Fixture,planes,group

FIX=Path(__file__).resolve().parent/"fixtures/real-regression"


class RealSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta=read_json(FIX/"type10/actual-ink-fixtures.json")
    def test_actual_snapshot_hashes(self):
        for record in read_json(FIX/"sources.json")["files"]:
            self.assertEqual(sha(FIX/record["file"]),record["sha256"])
    def replay(self,panel,key):
        root=FIX/"type10";support=panel["complete_ink_support"];frame=self.meta["frame"]
        with np.load(root/support["geometry"]["file"],allow_pickle=False) as g:p=g["positions"]
        with np.load(root/panel["samples"]["file"],allow_pickle=False) as g:ink=g[key]
        return measure_ink_fit(p,ink,frame["origin"],frame["u_axis"],frame["v_axis"],
                               support["scope_polygon_uv_m"],[-.012,.012],.01)
    def test_type10_current_orange_ink_both_real_lids(self):
        for panel in self.meta["panels"]:
            r=self.replay(panel,"ink_uv_m")
            self.assertTrue(r["technical_pass"],r)
            self.assertEqual(r["unsupported_ink_samples"],0)
            self.assertAlmostEqual(r["minimum_ink_clearance_m"],.017,places=5)
    def test_type10_recorded_old_placement_injected_on_actual_ink(self):
        for panel in self.meta["panels"]:
            r=self.replay(panel,"injected_v11_ink_uv_m")
            self.assertFalse(r["technical_pass"])
            self.assertGreater(r["outside_panel_samples"],30000)
    def test_actual_type10_data_alpha_requires_independent_channels(self):
        with Image.open(FIX/"type10/actual-turret-n-crop.png") as im:
            correct=resize_texture(im,(512,512),"packed_data","linear",Image.Resampling.BILINEAR)
            independent=Image.merge("RGBA",tuple(im.getchannel(c).resize((512,512),Image.Resampling.BILINEAR) for c in "RGBA"))
            incorrect=im.resize((512,512),Image.Resampling.BILINEAR)
        self.assertTrue(np.array_equal(np.array(correct),np.array(independent)))
        self.assertGreater(int(np.any(np.array(correct)!=np.array(incorrect),axis=-1).sum()),200000)
    def test_merkava_existing_injected_R_cannot_claim_removed_by_preserve(self):
        root=FIX/"merkava4m"
        with self.assertRaisesRegex(ValueError,"Old effect may remain"):
            audit_channel_repair(root,read_json(root/"plaque-removal-negative.json"))
    def test_merkava_known_injected_R_restores_exactly(self):
        root=FIX/"merkava4m";r=audit_channel_repair(root,read_json(root/"plaque-removal-positive.json"))
        self.assertTrue(r["passed"])
        self.assertEqual(r["channels"]["N_R"]["changed_samples"],192)


def legacy_bytes(width=8,height=4):
    sizes=mip_sizes(width,height);h=[0]*31
    h[0:7]=[124,0x2100f,height,width,width*4,0,len(sizes)]
    h[18:26]=[32,0x41,0,32,0xff0000,0xff00,0xff,0xff000000]
    h[26]=0x401008
    payload=b"DDS "+struct.pack("<31I",*h);arrays=[]
    for level,(w,hh) in enumerate(sizes):
        a=np.zeros((hh,w,4),np.uint8)
        a[:]=[17+level,35+level,91-level,129+level]
        arrays.append(a);payload+=a[:,:,[2,1,0,3]].tobytes()
    return payload,arrays


class ContainerAndIdentityTests(unittest.TestCase):
    def test_legacy_bgra_semantics_and_real_hash(self):
        raw,arrays=legacy_bytes()
        r=inspect_stream(BytesIO(raw),len(raw))
        _,top=read_top(BytesIO(raw),len(raw))
        self.assertTrue(np.array_equal(top,arrays[0]))
        self.assertEqual(r["actual_file_sha256"],hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(r["mips"]),len(arrays))
        self.assertEqual(r["color_space_tag"],"legacy_unspecified")
    def test_legacy_one_pixel_short_header_read(self):
        raw,arrays=legacy_bytes(1,1)
        r=inspect_stream(BytesIO(raw),len(raw))
        self.assertEqual(r["mip_count"],1)
        self.assertEqual(r["actual_file_sha256"],hashlib.sha256(raw).hexdigest())
    def test_legacy_truncated_chain_rejected(self):
        raw,_=legacy_bytes()
        with self.assertRaises(ValueError):inspect_stream(BytesIO(raw[:-4]),len(raw)-4)
    def test_active_blk_ignores_old_cached_files(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-active-") as td:
            root=Path(td);(root/"old.dds").write_bytes(b"old pixels");(root/"current.dds").write_bytes(b"new pixels")
            (root/"vehicle.blk").write_text('replace_tex{from:t="body_c*" to:t="current.dds"}')
            z=root/"old.zip"
            with zipfile.ZipFile(z,"w") as archive:
                archive.writestr("Skin/vehicle.blk",'replace_tex{from:t="body_c*" to:t="old.dds"}')
                archive.writestr("Skin/old.dds",b"old pixels")
            current=snapshot_folder(root/"vehicle.blk");old=snapshot_zip(z)
            self.assertEqual(current["unbound_dds_files"],1)
            self.assertFalse(compare_snapshots(old,current)["same_active_content"])
    def test_missing_active_target_is_not_replaced_by_stale_file(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-active-") as td:
            root=Path(td);(root/"old.dds").write_bytes(b"old")
            (root/"vehicle.blk").write_text('replace_tex{from:t="body_c*" to:t="missing.dds"}')
            with self.assertRaises(FileNotFoundError):snapshot_folder(root/"vehicle.blk")


class NativeSurfaceAndLayoutTests(unittest.TestCase):
    def test_collapsed_uv_kept_but_nonintersecting_does_not_kill_scene(self):
        p,u=planes();p=np.concatenate((p,np.array([[[0,0,1],[1,0,1],[0,1,1]]])))
        u=np.concatenate((u,np.array([[[.9,.9],[.9,.9],[.9,.9]]])))
        mask=np.zeros((32,32),bool);mask[20:25,2:7]=True
        r=audit(p,u,mask,[group(),group("constant_uv",[2],"other_preserved")],["armor"],layer_role="decal",mode="partial")
        self.assertTrue(r["technical_pass"]);self.assertEqual(r["collapsed_uv_native_faces"],[2])
    def test_collapsed_uv_sampling_paint_is_still_blocked(self):
        p,u=planes();p=np.concatenate((p,np.array([[[0,0,1],[1,0,1],[0,1,1]]])))
        u=np.concatenate((u,np.array([[[.2,.3],[.2,.3],[.2,.3]]])))
        mask=np.ones((32,32),bool)
        r=audit(p,u,mask,[group(),group("constant_uv",[2],"glass")],["armor"],layer_role="decal",mode="partial")
        self.assertFalse(r["technical_pass"]);self.assertIn(2,r["undersampled_alias_faces"])
    def test_nonrendering_geometry_is_accounted_not_silently_dropped(self):
        p,u=planes();p=np.concatenate((p,np.zeros((1,3,3))))
        u=np.concatenate((u,u[:1]))
        r=audit(p,u,np.ones((16,16),bool),[group(),group("collapsed_geometry",[2],"other_preserved")],["armor"])
        self.assertTrue(r["technical_pass"]);self.assertEqual(r["non_rendering_native_faces"],[2])
    def test_self_declared_positive_margins_cannot_hide_actual_misplacement(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-roof-") as td:
            fx=Fixture(Path(td)/"case")
            row=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]
            row["center_uv_m"]=[2,2]
            fx.design["part_layouts"]["roof_warning"]["margins_m"]=[1,1,1,1]
            fx.save_design()
            with self.assertRaises(ValueError):validate_manifest(fx.root/"vehicle.json")
    def test_tiny_panel_group_requires_deliberate_reference(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-roof-") as td:
            fx=Fixture(Path(td)/"case")
            row=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]
            row["graphic_size_m"]=[.2,.2]
            fx.save_design()
            with self.assertRaisesRegex(ValueError,"scale differs"):validate_manifest(fx.root/"vehicle.json")
    def test_occluded_group_cannot_hide_behind_readable_boolean(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-roof-") as td:
            fx=Fixture(Path(td)/"case")
            spec=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]["visibility"]["probe"]
            probe=read_json(fx.root/spec["file"]);probe["visible_ink_samples"]=40
            changed=fx.json("roof-probe.json",probe)
            fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]["visibility"]["probe"]=changed
            fx.design["part_layouts"]["roof_warning"]["readable_at_normal_view"]=True
            fx.save_design()
            with self.assertRaisesRegex(ValueError,"recomputed scene|obstructed"):validate_manifest(fx.root/"vehicle.json")
    def test_transparent_padding_cannot_fake_a_large_warning_group(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-roof-") as td:
            fx=Fixture(Path(td)/"case")
            row=fx.design["part_layouts"]["roof_warning"]["placement_checks"][0]
            padded=np.zeros((32,32,4),np.uint8);padded[12:20,12:20]=255
            row["asset"]=fx.image("padded-roof.png",padded)
            spec=row["visibility"]["probe"];probe=read_json(fx.root/spec["file"])
            probe["asset_sha256"]=row["asset"]["sha256"]
            row["visibility"]["probe"]=fx.json("roof-probe.json",probe)
            fx.save_design()
            with self.assertRaisesRegex(ValueError,"scale differs"):validate_manifest(fx.root/"vehicle.json")
    def test_actual_aps_cannot_be_one_unclassified_housing(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-equipment-") as td:
            fx=Fixture(Path(td)/"case");fx.design["capabilities"]={"active_protection_system":True}
            claims={c["id"]:c for c in fx.design["coverage"]}
            with self.assertRaisesRegex(ValueError,"classification"):
                validate_sensitive_equipment(fx.root,fx.design,claims)


if __name__=="__main__":
    unittest.main(verbosity=2)
