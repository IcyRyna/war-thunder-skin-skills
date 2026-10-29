"""Independent DDS/BLK/delivery regressions using small synthetic inputs only."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image

ROOT = (Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_candidate import Fixture
from dds_variant import decode_mips, write_rgba8_mips
from runtime_validation import audit_delivery, audit_encoding, audit_runtime
from skill_contract import sha
from texture_semantics import iter_mipmaps
from vehicle_review import validate_manifest


class RuntimeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="charcoal-runtime-regression-")
        self.addCleanup(self.temporary.cleanup)
        self.fx = Fixture(Path(self.temporary.name) / "fixture")
        self.fx.final(paint_material=True)

    def row(self, role):
        return next(r for r in self.fx.design["runtime_textures"] if r["role"] == role)

    def refresh_file(self, name):
        """Refresh every declared hash after deliberately changing one test input."""
        digest = sha(self.fx.root / name)

        def visit(value):
            if isinstance(value, dict):
                if value.get("file") == name and "sha256" in value:
                    value["sha256"] = digest
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.fx.design)

    def change_header(self, role, offset, value):
        name = self.row(role)["dds"]["file"]
        path = self.fx.root / name
        payload = bytearray(path.read_bytes())
        struct.pack_into("<I", payload, offset, value)
        path.write_bytes(payload)
        self.refresh_file(name)

    def change_blk(self, text):
        (self.fx.root / "fixture.blk").write_text(text, encoding="utf-8")
        self.refresh_file("fixture.blk")

    def rewrite_normal(self, values):
        row = self.row("normal")
        name = row["dds"]["file"]
        mips = [np.array(im) for im in iter_mipmaps(Image.fromarray(values), "packed_data", "linear")]
        write_rgba8_mips(self.fx.root / name, mips, "data")
        self.refresh_file(name)
        self.fx.design["materials"][0]["final_samples"][0]["final_n"] = self.fx.image("decoded-normal.png", values)

    def final_audit(self):
        self.fx.save_design()
        return validate_manifest(self.fx.root / "vehicle.json", "final")

    def archive(self, *, replacements=None, extra=None, omitted=()):
        replacements = replacements or {}
        path = self.fx.root / "game.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in self.fx.design["final_runtime_files"]:
                name = item["package_path"]
                if name not in omitted:
                    payload = replacements.get(name, (self.fx.root / item["file"]).read_bytes())
                    archive.writestr(name, payload)
            for name, payload in (extra or {}).items():
                archive.writestr(name, payload)
        return path

    def bounded_normal(self, *, absolute=2, mean=2, angle=2):
        self.row("normal")["encoding"] = {
            "mode": "bounded",
            "evidence": self.fx.evidence,
            "max_abs": [0, absolute, 0, 0],
            "max_mean": [0, mean, 0, 0],
            "max_normal_angle_deg": angle,
        }

    def test_complete_final_and_game_zip_pass(self):
        self.assertTrue(self.final_audit()["technical_pass"])
        runtime = audit_runtime(self.fx.root, self.fx.design)
        self.assertEqual(len(runtime["mappings"]), 2)
        for texture in runtime["textures"]:
            self.assertEqual([m["size"] for m in texture["mips"]],
                             [[48, 32], [24, 16], [12, 8], [6, 4], [3, 2], [1, 1]])
            self.assertTrue(all(m["decoded_rgba_sha256"] == m["canonical_mip_sha256"]
                                for m in texture["mips"]))
        archive = self.archive()
        report = audit_delivery(self.fx.root, self.fx.design, archive)
        self.assertTrue(all(report[key] for key in ("technical_pass", "budget_pass", "runtime_identity_pass", "dds_semantics_pass")))
        self.assertEqual(report["members_checked"], 3)
        self.assertEqual(report["zip_sha256"], sha(archive))
        self.assertEqual(report["game_validation"], "not inferred")

    def test_truncated_tail_mips_rejected_even_when_top_png_matches(self):
        row = self.row("color")
        path = self.fx.root / row["dds"]["file"]
        path.write_bytes(path.read_bytes()[:148 + self.fx.color.nbytes])
        self.refresh_file(row["dds"]["file"])
        with self.assertRaisesRegex(ValueError, "Truncated mip payload"):
            self.final_audit()

    def test_declared_single_mip_rejected(self):
        self.change_header("color", 28, 1)
        with self.assertRaisesRegex(ValueError, "complete mip chain"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_trailing_surface_bytes_rejected(self):
        row = self.row("color")
        path = self.fx.root / row["dds"]["file"]
        path.write_bytes(path.read_bytes() + b"unreviewed-surface")
        self.refresh_file(row["dds"]["file"])
        with self.assertRaisesRegex(ValueError, "trailing|additional surface"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_wrong_lower_mip_pixels_rejected_despite_matching_top(self):
        row = self.row("color")
        path = self.fx.root / row["dds"]["file"]
        _, mips = decode_mips(path)
        mips[-1][0, 0, 0] += 1
        write_rgba8_mips(path, mips, "color")
        self.refresh_file(row["dds"]["file"])
        with self.assertRaisesRegex(ValueError, "mip 5: encoding error"):
            self.final_audit()

    def test_srgb_packed_normal_rejected(self):
        self.change_header("normal", 128, 29)
        with self.assertRaisesRegex(ValueError, "color-space tag"):
            self.final_audit()

    def test_opacity_alpha_mode_rejected_for_packed_normal(self):
        self.change_header("normal", 144, 1)
        with self.assertRaisesRegex(ValueError, "alpha-mode"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_blk_without_mappings_rejected(self):
        self.change_blk('name:t="fixture with no mappings"')
        with self.assertRaisesRegex(ValueError, "Every manifest texture must be mapped"):
            self.final_audit()

    def test_garbage_blk_rejected(self):
        self.change_blk("this is not BLK mapping syntax")
        with self.assertRaisesRegex(ValueError, "Unsupported BLK"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_blk_resource_from_different_vehicle_rejected(self):
        text = (self.fx.root / "fixture.blk").read_text(encoding="utf-8")
        self.change_blk(text.replace("body_c*", "other_vehicle_c*"))
        with self.assertRaisesRegex(ValueError, "BLK source missing"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_blk_color_normal_target_swap_rejected(self):
        text = (self.fx.root / "fixture.blk").read_text(encoding="utf-8")
        text = text.replace("body.dds", "swap.dds").replace("normal.dds", "body.dds").replace("swap.dds", "normal.dds")
        self.change_blk(text)
        with self.assertRaisesRegex(ValueError, "slot role mismatch"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_blk_unknown_target_rejected(self):
        text = (self.fx.root / "fixture.blk").read_text(encoding="utf-8")
        self.change_blk(text.replace("body.dds", "old-body.dds"))
        with self.assertRaisesRegex(ValueError, "target is absent"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_native_slot_inventory_for_other_model_rejected(self):
        bindings = json.loads((self.fx.root / "bindings.json").read_text(encoding="utf-8"))
        bindings["model_sha256"] = "0" * 64
        self.fx.json("bindings.json", bindings)
        self.refresh_file("bindings.json")
        with self.assertRaisesRegex(ValueError, "different model/unit"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_native_slot_semantics_conflict_rejected(self):
        bindings = json.loads((self.fx.root / "bindings.json").read_text(encoding="utf-8"))
        bindings["resources"][0]["alpha_semantics"] = "opacity"
        self.fx.json("bindings.json", bindings)
        self.refresh_file("bindings.json")
        with self.assertRaisesRegex(ValueError, "native slot alpha_semantics"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_undeclared_runtime_dds_rejected(self):
        copied = self.fx.root / "unreviewed.dds"
        copied.write_bytes((self.fx.root / "body.dds").read_bytes())
        self.fx.design["final_runtime_files"].append(self.fx.runtime_spec(self.fx.spec(copied.name)))
        with self.assertRaisesRegex(ValueError, "Unreviewed/missing runtime DDS"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_declared_dds_missing_from_runtime_rejected(self):
        self.fx.design["final_runtime_files"] = [item for item in self.fx.design["final_runtime_files"]
                                                 if item["file"] != "normal.dds"]
        with self.assertRaisesRegex(ValueError, "Declared DDS missing"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_zip_with_old_dds_bytes_rejected(self):
        payload = bytearray((self.fx.root / "body.dds").read_bytes())
        payload[-1] ^= 1
        archive = self.archive(replacements={"Synthetic/body.dds": payload})
        with self.assertRaisesRegex(ValueError, "member differs.*body.dds"):
            audit_delivery(self.fx.root, self.fx.design, archive)

    def test_zip_with_different_blk_rejected(self):
        archive = self.archive(replacements={"Synthetic/fixture.blk": b'name:t="not the reviewed BLK"'})
        with self.assertRaisesRegex(ValueError, "member differs.*fixture.blk"):
            audit_delivery(self.fx.root, self.fx.design, archive)

    def test_zip_with_extra_file_rejected(self):
        archive = self.archive(extra={"Synthetic/unreviewed.dds": b"DDS unreviewed"})
        with self.assertRaisesRegex(ValueError, "extra, missing"):
            audit_delivery(self.fx.root, self.fx.design, archive)

    def test_zip_with_missing_file_rejected(self):
        archive = self.archive(omitted={"Synthetic/normal.dds"})
        with self.assertRaisesRegex(ValueError, "extra, missing"):
            audit_delivery(self.fx.root, self.fx.design, archive)

    def test_zip_with_wrong_member_location_rejected(self):
        archive = self.archive(omitted={"Synthetic/normal.dds"},
                               extra={"Elsewhere/normal.dds": (self.fx.root / "normal.dds").read_bytes()})
        with self.assertRaisesRegex(ValueError, "differently located"):
            audit_delivery(self.fx.root, self.fx.design, archive)

    def test_preserve_state_rejects_changed_canonical(self):
        row = self.row("normal")
        row["state"] = "preserve"
        with self.assertRaisesRegex(ValueError, "Preserve DDS has changed canonical"):
            audit_runtime(self.fx.root, self.fx.design)

    def test_preserve_state_accepts_unchanged_canonical(self):
        row = self.row("normal")
        row.update(state="preserve", baseline=dict(row["canonical"]))
        report = audit_encoding(self.fx.root, row)
        self.assertEqual(report["state"], "preserve")

    def test_exact_encoding_rejects_single_byte_difference(self):
        row = self.row("normal")
        with Image.open(self.fx.root / row["canonical"]["file"]) as image:
            actual = np.array(image)
        actual[0, 0, 1] += 1
        self.rewrite_normal(actual)
        with self.assertRaisesRegex(ValueError, "encoding error exceeds"):
            self.final_audit()

    def test_bounded_encoding_accepts_quantization_without_canonical_edits(self):
        row = self.row("normal")
        canonical_hash = row["canonical"]["sha256"]
        with Image.open(self.fx.root / row["canonical"]["file"]) as image:
            actual = np.array(image)
        actual[..., 1] += 2
        self.rewrite_normal(actual)
        self.bounded_normal()
        report = self.final_audit()
        self.assertTrue(report["technical_pass"])
        self.assertEqual(row["canonical"]["sha256"], canonical_hash)
        measured = audit_encoding(self.fx.root, row)
        self.assertEqual(measured["mips"][0]["max_abs"], [0, 2, 0, 0])
        self.assertGreater(measured["mips"][0]["normal_angle_max_deg"], 0)
        self.assertTrue(audit_delivery(self.fx.root, self.fx.design, self.archive())["technical_pass"])

    def test_canonical_structural_edit_rejected_even_if_encoded_exactly(self):
        row = self.row("normal")
        with Image.open(self.fx.root / row["canonical"]["file"]) as image:
            changed = np.array(image)
        changed[..., 1] += 2
        self.rewrite_normal(changed)
        row["canonical"] = self.fx.image("changed-canonical-normal.png", changed)
        self.assertEqual(audit_encoding(self.fx.root, row)["mips"][0]["max_abs"], [0, 0, 0, 0])
        with self.assertRaisesRegex(ValueError, "Canonical material R/B/G/A"):
            self.final_audit()

    def test_bounded_encoding_still_enforces_normal_angle(self):
        row = self.row("normal")
        with Image.open(self.fx.root / row["canonical"]["file"]) as image:
            actual = np.array(image)
        actual[..., 1] += 2
        self.rewrite_normal(actual)
        self.bounded_normal(angle=0.1)
        with self.assertRaisesRegex(ValueError, "normal direction error"):
            audit_encoding(self.fx.root, row)

    def test_bounded_encoding_still_enforces_mean_error(self):
        row = self.row("normal")
        with Image.open(self.fx.root / row["canonical"]["file"]) as image:
            actual = np.array(image)
        actual[..., 1] += 2
        self.rewrite_normal(actual)
        self.bounded_normal(mean=1)
        with self.assertRaisesRegex(ValueError, "encoding error exceeds"):
            audit_encoding(self.fx.root, row)

    def test_bounded_encoding_needs_frozen_evidence(self):
        self.bounded_normal()
        del self.row("normal")["encoding"]["evidence"]
        with self.assertRaisesRegex(ValueError, "encoding acceptance evidence"):
            audit_encoding(self.fx.root, self.row("normal"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
