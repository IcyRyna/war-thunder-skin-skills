"""Behavior tests for optional layouts, actual family identity and work ownership."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "toolkits/ground/scripts"))
sys.path.insert(0, str(ROOT / "tools"))
import layout_brief
import repository


class BriefBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="endfield-brief-tests-")
        cls.package = Path(cls.temporary.name) / "wt-style-endfield"
        tree = repository.assemble(ROOT, next(p for p in repository.read_catalog(ROOT) if p["id"] == "wt-style-endfield"))
        for name, record in tree.files.items():
            path = cls.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(record["data"])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_free_default_all_families_preserves_reference_id_and_complete_views(self):
        for family, unit in zip(layout_brief.FAMILIES, ("germ_leopard_2a7v", "ussr_t_80u", "ussr_t_90m", "cn_ztz_99a", "fr_leclerc_s2")):
            with self.subTest(family=family):
                brief = layout_brief.make_brief(self.package, family)
                self.assertIsNone(brief["preset"])
                self.assertEqual(brief["composition_mode"], "independent")
                self.assertEqual(brief["target_vehicle"]["reference_unit"], unit)
                self.assertEqual(set(brief["references"]["views"]), {"side", "front", "rear", "top"})
                self.assertTrue(all(p["optional_start"] is None for p in brief["parts"]))
                self.assertEqual(brief["inputs"]["weathering"], "none")
                self.assertEqual(brief["checks"]["game"], "not_run")

    def test_all_fallbacks_are_explicit_optional_and_independently_editable(self):
        for preset in ("F01", "F02", "F03"):
            brief = layout_brief.make_brief(self.package, "leclerc", preset=preset)
            self.assertEqual(brief["preset"], preset)
            self.assertFalse(brief["preset_is_mandatory"])
            self.assertTrue(all(p["optional_start"] for p in brief["parts"]))
            brief["parts"][0]["composition_intent"] = "重新选择前段主标、后部留白；不使用示例黄线。"
            self.assertEqual(layout_brief.validate_brief(self.package, brief)["artwork_acceptance"], "not_assessed")
            brief["preset_is_mandatory"] = True
            with self.assertRaisesRegex(ValueError, "mandatory"):
                layout_brief.validate_brief(self.package, brief)

    def test_text_and_surface_options_do_not_change_other_inputs_or_geometry(self):
        baseline = layout_brief.make_brief(self.package, "t-90")
        number = layout_brief.make_brief(self.package, "t-90", number="EF11")
        expected = deepcopy(baseline)
        expected["inputs"]["number"] = "EF11"
        self.assertEqual(number, expected)
        light = layout_brief.make_brief(self.package, "t-90", weathering="light")
        expected = deepcopy(baseline)
        expected["inputs"]["weathering"] = "light"
        self.assertEqual(light, expected)
        grain = layout_brief.make_brief(self.package, "t-90", surface_grain="subtle")
        self.assertEqual(grain["inputs"]["weathering"], "none")

    def test_single_granularity_and_region_ownership_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "granularity"):
            layout_brief.make_brief(self.package, "leopard-2", selected_zones=["H04", "H07"])
        with self.assertRaisesRegex(ValueError, "overlapping"):
            layout_brief.make_brief(self.package, "leopard-2", selected_zones=["H04", "H04L"])
        brief = layout_brief.make_brief(self.package, "leopard-2", selected_zones=["H07", "T01"])
        self.assertEqual([p["region_ids"] for p in brief["parts"]], [["H07"], ["T01L", "T01R"]])
        brief["parts"][0]["region_ids"] = ["G01"]
        with self.assertRaisesRegex(ValueError, "different"):
            layout_brief.validate_brief(self.package, brief)

    def test_model_identity_complete_mark_and_package_containment_are_not_silent(self):
        baseline = layout_brief.make_brief(self.package, "t-90")
        for key, value in (("reference_unit", "ussr_t_90a"), ("reference_profile", "profiles/ground/t-80/profile.json")):
            brief = deepcopy(baseline)
            brief["target_vehicle"][key] = value
            with self.assertRaisesRegex(ValueError, "identity"):
                layout_brief.validate_brief(self.package, brief)
        for key in ("crop", "split_lettering", "separate_opaque_logo_backing"):
            brief = deepcopy(baseline)
            brief["identity_policy"][key] = True
            with self.assertRaisesRegex(ValueError, "whole"):
                layout_brief.validate_brief(self.package, brief)
        for path in ("../SKILL.md", "C:/outside.png", "assets/../../outside.png"):
            with self.assertRaises(ValueError):
                layout_brief.package_file(self.package, path)

    def test_extracted_cli_works_from_an_unrelated_directory_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(prefix="endfield-cli-cwd-") as temporary:
            output = Path(temporary) / "brief.json"
            script = self.package / "scripts/layout_brief.py"
            command = [sys.executable, "-B", str(script), "create", "--family", "type-99", "--out", str(output)]
            first = subprocess.run(command, cwd=temporary, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(first.returncode, 0, first.stderr)
            data = output.read_bytes()
            repeat = subprocess.run(command, cwd=temporary, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(repeat.returncode, 0)
            self.assertEqual(output.read_bytes(), data)
            check = subprocess.run([sys.executable, "-B", str(script), "check", str(output)], cwd=temporary, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertEqual(json.loads(check.stdout)["artwork_acceptance"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
