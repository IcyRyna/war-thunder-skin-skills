"""AZUR hierarchy, real decoder samples, and read-only archive audit boundaries."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
import numpy as np

ROOT = (Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0, str(ROOT / "scripts"))
from azur_reference import validate_reference_policy, audit_archive, check_fixtures
from skill_contract import policy, read_json, sha
from reference_contract import masked_gloss
from dds_variant import write_rgba8_mips


class PrimaryReferenceTests(unittest.TestCase):
    def test_primary_and_thirteen_parts(self):
        result = validate_reference_policy()
        self.assertEqual(result["primary_template"], "fr_leclerc_azur")
        self.assertEqual(result["part_relations_checked"], 13)

    def test_a7hu_cannot_replace_primary(self):
        rules = policy(); rules["reference_hierarchy"]["primary_template"] = "germ_leopard_2a7hu"
        with self.assertRaisesRegex(ValueError, "AZUR"): validate_reference_policy(rules)

    def test_regression_cannot_claim_primary_validation(self):
        rules = policy(); rules["reference_hierarchy"]["adaptation_replaces_primary"] = True
        with self.assertRaisesRegex(ValueError, "Adaptation"): validate_reference_policy(rules)

    def test_current_user_choice_preserved(self):
        rules = policy(); rules["reference_hierarchy"]["target_user_override"] = False
        with self.assertRaisesRegex(ValueError, "user"): validate_reference_policy(rules)

    def test_part_requires_honest_source_scope(self):
        rules = policy(); rules["part_recipes"]["spare_tracks"]["primary_basis"]["scope"] = "new_source_rebuild"
        with self.assertRaisesRegex(ValueError, "distinguish"): validate_reference_policy(rules)

    def test_changed_evidence_rejected(self):
        rules = policy(); rules["part_recipes"]["roof_warning"]["primary_basis"]["evidence"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"): validate_reference_policy(rules)

    def test_microblocks_optional_on_front_and_roof(self):
        for part in ("upper_glacis", "turret_roof"):
            recipe = policy()["part_recipes"][part]
            self.assertNotIn("local_microblocks", recipe["default_elements"])
            self.assertIn("local_microblocks", recipe["optional_elements"])
            self.assertIn("large_gray_geometry", recipe["default_elements"])

    def test_gloss_requires_explicit_local_parameters(self):
        with self.assertRaises(TypeError): masked_gloss(np.zeros((4,4,4), np.uint8), np.ones((4,4), bool))

    def test_explicit_gloss_preserves_outside_and_other_channels(self):
        rng = np.random.default_rng(4)
        source = rng.integers(0,256,(8,8,4),dtype=np.uint8)
        mask = np.zeros((8,8),bool); mask[2:5,2:5] = True
        actual = masked_gloss(source, mask, factor=.9, ceiling=220)
        self.assertTrue(np.array_equal(actual[~mask], source[~mask]))
        self.assertTrue(np.array_equal(actual[:,:,1:], source[:,:,1:]))
        self.assertTrue(np.array_equal(actual[mask,0], np.minimum(np.rint(source[mask,0].astype(float)*.9),220)))

    def test_invalid_gloss_factor_rejected(self):
        with self.assertRaises(ValueError):
            masked_gloss(np.zeros((2,2,4), np.uint8), np.ones((2,2),bool), factor=float("nan"), ceiling=82)


class ActualAzurSamplesTests(unittest.TestCase):
    def test_fifteen_real_color_normal_ao_decodes(self):
        result = check_fixtures(Path(__file__).resolve().parent / "fixtures/azur")
        self.assertEqual(result, {"samples_checked":15, "roles":["ao","color","normal"]})

    def test_sample_provenance_matches_full_archive_audit(self):
        index = read_json(Path(__file__).resolve().parent / "fixtures/azur/index.json")
        audit = read_json(Path(__file__).resolve().parent / "fixtures/azur/full-runtime-audit.json")
        evidence = read_json(ROOT / "references/azur-retained-evidence.json")
        self.assertEqual(index["archive_sha256"], evidence["archive_sha256"])
        self.assertEqual(audit["archive_sha256"], evidence["archive_sha256"])
        rows = {r["member"]:r for r in audit["textures"]}
        self.assertEqual(len(rows), 15)
        for sample in index["samples"]:
            self.assertEqual(sample["source_sha256"], evidence["files"][sample["member"]])
            mip = rows[sample["member"]]["mips"][sample["level"]]
            self.assertEqual(sample["payload_sha256"], mip["payload_sha256"])
            self.assertEqual(sample["decoded_rgba_sha256"], mip["decoded_rgba_sha256"])

    def test_fixture_damage_detected(self):
        with tempfile.TemporaryDirectory(prefix="charcoal-azur-test-") as temp:
            dst = Path(temp) / "samples"; shutil.copytree(Path(__file__).resolve().parent/"fixtures/azur", dst)
            row = read_json(dst/"index.json")["samples"][0]
            (dst/row["payload"]).write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "hash mismatch"): check_fixtures(dst)

    def test_historical_measurements_not_claimed_remeasured(self):
        audit = read_json(Path(__file__).resolve().parent / "fixtures/azur/full-runtime-audit.json")
        self.assertEqual(audit["mips_decoded"], 169)
        self.assertEqual(audit["whole_vehicle_style_validation"], "not_run")
        self.assertIn("not remeasured", audit["historical_masked_measurements"])


class ArchiveAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="charcoal-azur-archive-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.contents = {}
        blocks = ['name:t="user"']
        for suffix in ("c", "n", "ao"):
            name = "test_"+suffix+".dds"
            path = self.folder/name
            write_rgba8_mips(path, [np.full((s,s,4),128,np.uint8) for s in (8,4,2,1)],
                             "color" if suffix=="c" else "data")
            self.contents["skin/"+name] = path.read_bytes()
            blocks.append('replace_tex{from:t="test_'+suffix+'*" to:t="'+name+'"}')
        self.contents["skin/test.blk"] = "\n".join(blocks).encode()
        self.archive = self.folder/"fixture.zip"
        self.repack()

    def repack(self):
        with zipfile.ZipFile(self.archive,"w") as z:
            for name, raw in self.contents.items(): z.writestr(name, raw)
        self.evidence = {"archive_sha256":sha(self.archive),
                         "files":{n:hashlib.sha256(b).hexdigest() for n,b in self.contents.items()}}

    def test_exact_runtime_audit_and_source_unchanged(self):
        before = sha(self.archive)
        result = audit_archive(self.archive,self.evidence,self.folder/"samples")
        self.assertEqual(result["mips_decoded"],12)
        self.assertEqual(result["members_verified"],4)
        self.assertEqual(sha(self.archive),before)
        self.assertEqual(check_fixtures(self.folder/"samples")["samples_checked"],3)

    def test_wrong_archive_revision_rejected(self):
        evidence=copy.deepcopy(self.evidence); evidence["archive_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"revision"): audit_archive(self.archive,evidence)

    def test_wrong_member_hash_rejected(self):
        self.evidence["files"]["skin/test_n.dds"]="0"*64
        with self.assertRaisesRegex(ValueError,"deployment"): audit_archive(self.archive,self.evidence)

    def test_incomplete_member_inventory_rejected(self):
        del self.evidence["files"]["skin/test_ao.dds"]
        with self.assertRaisesRegex(ValueError,"member set"): audit_archive(self.archive,self.evidence)

    def test_unbound_dds_rejected(self):
        self.contents["skin/spare.dds"]=self.contents["skin/test_c.dds"]; self.repack()
        with self.assertRaisesRegex(ValueError,"exact retained DDS"): audit_archive(self.archive,self.evidence)

    def test_unsafe_member_rejected(self):
        self.contents["../bad.dds"]=b"bad"; self.repack()
        with self.assertRaisesRegex(ValueError,"Unsafe"): audit_archive(self.archive,self.evidence)

    def test_truncated_payload_rejected(self):
        self.contents["skin/test_n.dds"]=self.contents["skin/test_n.dds"][:-1]; self.repack()
        with self.assertRaisesRegex(ValueError,"payload size"): audit_archive(self.archive,self.evidence)


if __name__ == "__main__": unittest.main()
