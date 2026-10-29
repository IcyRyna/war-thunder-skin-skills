"""Cross-file regression contracts using tiny, real composed layers and DDS files."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from test_candidate import Fixture
from compose_native import compose
from equipment_labels import check_label
from style_quality import check_detail
from vehicle_review import validate_manifest


class DeepContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="charcoal-deep-contract-")
        self.addCleanup(temporary.cleanup)
        self.fx = Fixture(Path(temporary.name) / "case")

    def validate_final(self):
        self.fx.save_design()
        return validate_manifest(self.fx.root / "vehicle.json", "final")

    def read_image(self, spec):
        with Image.open(self.fx.root / spec["file"]) as image:
            return np.array(image)

    def replace_canonical_color(self, pixels):
        """Keep all runtime identities valid so tests reach the edit contract."""
        fixture = self.fx
        texture = fixture.design["textures"][0]
        texture["final_c"] = fixture.image("canonical-final.png", pixels)
        texture["final_dds"] = fixture.image("body.dds", pixels)
        fixture.design["runtime_textures"][0].update(
            canonical=texture["final_c"], dds=texture["final_dds"]
        )
        fixture.design["final_runtime_files"][0] = fixture.runtime_spec(texture["final_dds"])

    def decorated_final(self):
        """Build the final proof from the actual composer's saved layer pixels."""
        fixture = self.fx
        profile, plan = fixture.make_plan()
        warning = copy.deepcopy(next(g for g in fixture.design["graphics"] if g["id"] == "warning"))
        output = fixture.root / "composed"
        compose(profile, plan, output)
        layer_spec = fixture.spec("composed/layers/mark.png")
        selected = self.read_image(layer_spec)[..., 3] > 0
        composed = self.read_image(fixture.spec("composed/colors/body.png"))
        fixture.final()
        fixture.design["graphics"] = [warning]
        fixture.design["graphic_omissions"].pop("warning")
        texture = fixture.design["textures"][0]
        texture["decoration_mask"] = fixture.image("actual-decoration.png", selected.astype("uint8") * 255)
        texture["layers"] = [{
            "id": "mark", "graphic_id": "warning", "asset_id": "mark",
            "catalog": fixture.spec("catalog.json"), "asset": fixture.spec("decal.png"),
            "rgba": layer_spec, "quad_px": fixture.plan["placements"][0]["quad_px"],
            "rotation_deg": 0, "opacity": 1,
        }]
        texture["final_paint_regions"] = []
        for region in texture["paint_regions"]:
            remaining = (self.read_image(region["mask"]) > 0) & ~selected
            texture["final_paint_regions"].append({
                "base_region_id": region["id"], "role": region["role"],
                "mask": fixture.image("remaining-" + region["id"] + ".png", remaining.astype("uint8") * 255),
            })
        self.replace_canonical_color(composed)
        return texture, selected

    def label_case(self, text="NO STEP"):
        fixture = self.fx
        normalized = text.lower().replace(" ", "-")
        asset = {"contains_text": True, "label_text": text, "sha256": fixture.base["sha256"]}
        profile = {
            "unit_id": "fixture_tank", "_evidence_root": str(fixture.root),
            "capabilities": {}, "approved_labels": [text],
            "label_evidence": {normalized: {
                "unit_id": "fixture_tank", "text": text, "asset_sha256": asset["sha256"],
                "carrier": "synthetic native roof panel", "evidence": fixture.evidence,
            }},
        }
        return asset, profile, profile["label_evidence"][normalized]

    def test_real_composed_layer_passes_complete_final_review(self):
        _, selected = self.decorated_final()
        report = self.validate_final()
        self.assertTrue(report["technical_pass"])
        self.assertGreater(int(selected.sum()), 0)
        self.assertEqual(report["final_graphics"]["observed_roles"], ["warning"])
        self.assertEqual(report["visual_approval"], "not inferred")

    def test_decoration_mask_cannot_hide_unqualified_blue_pixels(self):
        self.fx.final()
        texture = self.fx.design["textures"][0]
        fake = np.full(self.fx.shape, 255, np.uint8)
        fake[:8, :8] = 0
        texture["decoration_mask"] = self.fx.image("fake-decoration.png", fake)
        changed = self.fx.color.copy()
        changed[fake > 0, :3] = [0, 0, 255]
        self.replace_canonical_color(changed)
        with self.assertRaisesRegex(ValueError, "actual qualified layer Alpha union"):
            self.validate_final()

    def test_real_layer_alpha_union_cannot_be_enlarged(self):
        texture, selected = self.decorated_final()
        selected[0, 0] = True
        texture["decoration_mask"] = self.fx.image("enlarged-decoration.png", selected.astype("uint8") * 255)
        with self.assertRaisesRegex(ValueError, "actual qualified layer Alpha union"):
            self.validate_final()

    def test_exported_layer_pixels_must_match_reconstruction(self):
        texture, selected = self.decorated_final()
        layer = texture["layers"][0]
        pixels = self.read_image(layer["rgba"])
        pixels[selected, 0] = 0
        layer["rgba"] = self.fx.image("edited-layer.png", pixels)
        with self.assertRaisesRegex(ValueError, "exported layer differs"):
            self.validate_final()

    def test_layer_asset_pixels_must_match_frozen_catalog(self):
        texture, _ = self.decorated_final()
        layer = texture["layers"][0]
        pixels = self.read_image(layer["asset"])
        pixels[0, 0, 0] = 0
        layer["asset"] = self.fx.image("different-asset.png", pixels)
        with self.assertRaisesRegex(ValueError, "pixels differ from reviewed source asset"):
            self.validate_final()

    def test_canonical_must_equal_base_plus_actual_layers(self):
        texture, _ = self.decorated_final()
        changed = self.read_image(texture["final_c"])
        changed[0, 0, :3] = [34, 34, 35]
        self.replace_canonical_color(changed)
        with self.assertRaisesRegex(ValueError, "not the reviewed base plus actual qualified layers"):
            self.validate_final()

    def test_final_regions_cannot_discard_undecorated_paint(self):
        texture, _ = self.decorated_final()
        region = texture["final_paint_regions"][0]
        mask = self.read_image(region["mask"])
        mask[0, 0] = 0
        region["mask"] = self.fx.image("discarded-paint.png", mask)
        with self.assertRaisesRegex(ValueError, "discarded undeclared pixels"):
            self.validate_final()

    def test_decal_cannot_borrow_base_paint_louver_coverage(self):
        profile, plan = self.fx.make_plan()
        claim = self.fx.design["coverage"][0]
        claim["layer_role"] = "base_paint"
        claim["face_groups"][0]["role"] = "louver"
        self.fx.plan["vehicle_design"] = self.fx.save_design()
        self.fx.json("plan.json", self.fx.plan)
        with self.assertRaisesRegex(ValueError, "same actual decoration role"):
            compose(profile, plan, None, dry=True)

    def test_placement_cannot_change_its_declared_graphic_role(self):
        profile, plan = self.fx.make_plan()
        self.fx.plan["placements"][0]["layer_role"] = "base_paint"
        self.fx.json("plan.json", self.fx.plan)
        with self.assertRaisesRegex(ValueError, "actual decoration layer role"):
            compose(profile, plan, None, dry=True)

    def test_preserve_cannot_skip_existing_final_material_samples(self):
        self.fx.final(True)
        material = self.fx.design["materials"][0]
        material["state"] = "preserve"
        material.pop("parameters")
        with self.assertRaisesRegex(ValueError, "Preserve cannot silently skip"):
            self.validate_final()

    def test_not_applicable_cannot_skip_real_material_samples(self):
        self.fx.final(True)
        material = self.fx.design["materials"][0]
        material["state"] = "not_applicable"
        material.pop("parameters")
        with self.assertRaisesRegex(ValueError, "Absent material cannot carry"):
            self.validate_final()

    def test_material_color_parameters_are_checked_against_actual_c(self):
        self.fx.final(True)
        material = self.fx.design["materials"][0]
        material["color_mode"] = "neutral"
        material["parameters"].pop("paint_roles")
        material["parameters"]["color_srgb"] = [220, 220, 220]
        with self.assertRaisesRegex(ValueError, "color_srgb disagrees with canonical C"):
            self.validate_final()

    def test_material_color_scope_must_match_declared_paint_roles(self):
        self.fx.final(True)
        self.fx.design["materials"][0]["parameters"]["paint_roles"] = ["A"]
        with self.assertRaisesRegex(ValueError, "exceeds its declared A/B/C/F roles"):
            self.validate_final()

    def test_material_with_matching_paint_roles_passes(self):
        self.fx.final(True)
        report = self.validate_final()
        self.assertTrue(report["technical_pass"])
        self.assertEqual(len(report["final_materials"]), 1)

    def test_false_capability_key_does_not_authorize_roof_label(self):
        self.fx.design["capabilities"] = {"ammunition_blowout_panels": False}
        self.fx.design["part_layouts"]["roof_warning"].update(
            label_texts=["BLOW-OUT"], function_evidence=self.fx.evidence
        )
        self.fx.save_design()
        with self.assertRaisesRegex(ValueError, "confirmed target ammunition"):
            validate_manifest(self.fx.root / "vehicle.json")

    def test_composer_profile_cannot_contradict_design_capabilities(self):
        profile, plan = self.fx.make_plan()
        self.fx.design["capabilities"] = {"ammunition_blowout_panels": False}
        self.fx.profile["capabilities"] = {"ammunition_blowout_panels": True}
        self.fx.plan["vehicle_design"] = self.fx.save_design()
        self.fx.plan["profile_sha256"] = self.fx.json("profile.json", self.fx.profile)["sha256"]
        self.fx.json("plan.json", self.fx.plan)
        with self.assertRaisesRegex(ValueError, "disagree on capabilities"):
            compose(profile, plan, None, dry=True)

    def test_label_with_bound_unit_text_pixels_and_evidence_passes(self):
        asset, profile, _ = self.label_case()
        self.assertEqual(check_label(asset, profile)["semantic_check"], "target/asset/evidence matched")

    def test_approved_label_without_bound_evidence_is_rejected(self):
        asset, profile, _ = self.label_case()
        profile.pop("label_evidence")
        with self.assertRaisesRegex(ValueError, "bind unit, text and the actual asset hash"):
            check_label(asset, profile)

    def test_label_evidence_cannot_name_another_unit(self):
        asset, profile, proof = self.label_case()
        proof["unit_id"] = "another_vehicle"
        with self.assertRaisesRegex(ValueError, "bind unit, text and the actual asset hash"):
            check_label(asset, profile)

    def test_label_evidence_cannot_approve_different_text(self):
        asset, profile, proof = self.label_case()
        proof["text"] = "NO HANDHOLD"
        with self.assertRaisesRegex(ValueError, "bind unit, text and the actual asset hash"):
            check_label(asset, profile)

    def test_label_evidence_cannot_approve_different_asset_pixels(self):
        asset, profile, proof = self.label_case()
        proof["asset_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "bind unit, text and the actual asset hash"):
            check_label(asset, profile)

    def test_label_evidence_file_hash_must_match(self):
        asset, profile, proof = self.label_case()
        proof["evidence"] = {**self.fx.evidence, "sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            check_label(asset, profile)

    def test_label_cannot_disable_text_checks(self):
        asset, profile, _ = self.label_case()
        asset["contains_text"] = False
        with self.assertRaisesRegex(ValueError, "contains_text=False"):
            check_label(asset, profile)

    def test_blowout_label_requires_true_capability_without_explicit_claim(self):
        asset, profile, _ = self.label_case("BLOW-OUT")
        profile["capabilities"] = {"ammunition_blowout_panels": False}
        with self.assertRaisesRegex(ValueError, "does not confirm required equipment"):
            check_label(asset, profile)

    def test_true_label_capability_requires_hashed_evidence(self):
        asset, profile, _ = self.label_case("BLOW-OUT")
        profile["capabilities"] = {"ammunition_blowout_panels": True}
        with self.assertRaisesRegex(ValueError, "capability evidence"):
            check_label(asset, profile)

    def test_detail_budgets_cannot_lower_line_or_text_minimums(self):
        record = {"native_detail_size": [32, 32], "contains_text": True,
                  "critical_features": {"line_width_px": 3, "text_cap_height_px": 14}}
        quad = [[0, 0], [31, 0], [31, 31], [0, 31]]
        for field, value in (("min_line_px", 1), ("min_text_cap_px", 8)):
            with self.subTest(budget=field):
                with self.assertRaisesRegex(ValueError, "cannot silently lower"):
                    check_detail(record, quad, (32, 32), budget={field: value})


if __name__ == "__main__":
    unittest.main(verbosity=2)
