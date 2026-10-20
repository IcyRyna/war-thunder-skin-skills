"""Synthetic unit fixtures; these are NOT evidence of real Skill or visual success."""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKS_DIR = Path(__file__).resolve().parents[1] / "checks"
sys.path.insert(0, str(CHECKS_DIR))

from workflow_check import TEST_CASES, files_digest, input_digest, rule_digest, rules_digest, validate_manifest


class StudyFixture:
    def __init__(self, root: Path):
        self.root = root
        self.counter = 0
        self.skill = self.file("candidate/SKILL.md", "# Synthetic candidate\n")
        self.baseline = self.file("baseline/SKILL.md", "# Synthetic generic baseline\n")
        reference = self.evidence("reference", "study", "synthetic observation")
        self.manifest = {
            "schema_version": 1,
            "study_id": "SYNTHETIC-TEST",
            "candidate": {"version": "candidate-1", "files": [self.skill]},
            "evidence": [reference],
            "production_inputs": [reference["id"]],
            "rules": [{
                "id": "R01", "scope": ["style:synthetic"],
                "claim": "SYNTHETIC claim used only to test bookkeeping.",
                "required_checks": ["technical", "visual", "game"],
                "evidence": [reference["id"]], "validation": "unverified",
                "review": {"status": "pending", "evidence": []},
            }],
            "runs": [],
            "publication": {"required_test_cases": list(TEST_CASES), "authorization": None},
        }
        self.inputs = {
            name: {**self.file(f"inputs/{name}.txt", f"Synthetic {name}"), "version": "synthetic-1"}
            for name in ("brief", "profile", "tools", "rubric")
        }
        self.inputs.update({"files": [], "randomness": {"policy": "unsupported", "seed": None}})

    def file(self, name: str, content: str | bytes) -> dict:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        path.write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def evidence(self, kind: str, role: str, content: str | bytes | dict, name: str | None = None) -> dict:
        self.counter += 1
        data = json.dumps(content) if isinstance(content, dict) else content
        return {
            "id": f"E{self.counter:03}",
            **self.file(name or f"evidence/E{self.counter:03}.json", data),
            "kind": kind, "role": role,
        }

    def add_evidence(self, *args, **kwargs) -> dict:
        item = self.evidence(*args, **kwargs)
        self.manifest["evidence"].append(item)
        return item

    def add_run(self, case: str, game: str = "pass") -> dict:
        inputs = copy.deepcopy(self.inputs)
        if case == "T02":
            inputs["profile"] = {
                **self.file("inputs/profile-transfer.txt", "Synthetic second vehicle"),
                "version": "synthetic-1",
            }
        if case == "T03":
            inputs["brief"] = {
                **self.file("inputs/brief-variant.txt", "Synthetic variant"),
                "version": "synthetic-1",
            }
        run = {
            "run_id": case + "-run", "test_case": case, "session_id": case + "-session",
            "fresh_session": True, "agent_version": "synthetic-agent-1", "game_version": "synthetic-game-1",
            "scope": ["style:synthetic"], "vehicle": "B" if case == "T02" else "A",
            "theme": "variant" if case == "T03" else "base",
            "started_at": "2026-10-20T00:00:00+08:00",
            "execution_evidence": [], "context_sources": [],
            "inputs": inputs, "production_inputs": [],
            "input_digest": input_digest(inputs, []),
            "skill": {"version": "baseline-1" if case == "T00" else "candidate-1",
                      "files": [self.baseline if case == "T00" else self.skill]},
            "attempt_count": 1, "attempts": [],
        }
        run["skill_digest"] = files_digest(run["skill"]["files"])
        output = self.file(f"outputs/{case}.txt", f"SYNTHETIC output for {case}")
        attempt = {"attempt": 1, "outputs": [output], "human_interventions": [], "outcomes": {}}
        for check in ("technical", "visual", "game"):
            status = game if check == "game" else "pass"
            receipt = {
                "run_id": run["run_id"], "attempt": 1, "check": check, "status": status,
                "skill_digest": run["skill_digest"], "input_digest": run["input_digest"],
                "output_digest": files_digest([output]),
                "observations": "SYNTHETIC fixture, not real execution or visual evidence.",
                "supporting_evidence": [],
            }
            if check == "game" and status == "pass":
                # A 1px synthetic PNG exercises file type checks, not visual quality.
                capture = self.add_evidence(
                    "game_capture", "development",
                    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3y0AAAAASUVORK5CYII="),
                    name=f"evidence/{case}-synthetic-capture.png",
                )
                capture.update({
                    "run_id": run["run_id"], "attempt": 1, "game_version": run["game_version"],
                    "output_digest": files_digest([output]),
                })
                receipt["supporting_evidence"] = [capture["id"]]
                receipt["game_version"] = run["game_version"]
            refs = []
            if status != "not_run":
                result = self.add_evidence(check + "_result", "development", receipt)
                refs = [result["id"]]
            attempt["outcomes"][check] = {"status": status, "evidence": refs}
        run["attempts"].append(attempt)
        record = {
            key: run[key] for key in (
                "run_id", "session_id", "fresh_session", "input_digest", "skill_digest",
                "attempt_count", "context_sources", "agent_version", "started_at",
                "scope", "vehicle", "theme",
            )
        }
        record.update({"recorded_attempts": [1], "observations": "SYNTHETIC execution record."})
        run["execution_evidence"] = [self.add_evidence("run_record", "development", record)["id"]]
        self.manifest["runs"].append(run)
        return run

    def finish(self) -> None:
        for case in TEST_CASES:
            self.add_run(case)
        rule = self.manifest["rules"][0]
        rule["validation"] = "tested_transfer"
        for run in self.manifest["runs"]:
            if run["test_case"] != "T00":
                for outcome in run["attempts"][-1]["outcomes"].values():
                    rule["evidence"].extend(outcome["evidence"])
        digest = files_digest(self.manifest["candidate"]["files"])
        review = self.add_evidence("user_review", "development", {
            "decision": "accepted", "candidate_digest": digest, "rule_ids": ["R01"],
            "rule_digest": rule_digest(rule, {e["id"]: e for e in self.manifest["evidence"]}),
            "reviewer": "SYNTHETIC tester", "provenance": "unit test only, not user authorization",
        })
        rule["review"] = {"status": "accepted", "evidence": [review["id"]]}
        authorization = self.add_evidence("publication_authorization", "development", {
            "action": "publish", "authorized": True, "candidate_digest": digest,
            "rules_digest": rules_digest(self.manifest["rules"], {e["id"]: e for e in self.manifest["evidence"]}),
            "authorized_by": "SYNTHETIC tester", "provenance": "unit test only",
            "authorized_at": "2026-10-20T00:00:00+08:00",
            "files": self.manifest["candidate"]["files"],
        })
        self.manifest["publication"]["authorization"] = authorization["id"]

    def rewrite_receipt(self, evidence_id: str, change) -> None:
        evidence = next(e for e in self.manifest["evidence"] if e["id"] == evidence_id)
        receipt = json.loads((self.root / evidence["path"]).read_text())
        change(receipt)
        evidence.update(self.file(evidence["path"], json.dumps(receipt)))

    def refresh_approvals(self) -> None:
        """Synthetic re-review only: never used to authenticate a human decision."""
        evidence = {e["id"]: e for e in self.manifest["evidence"]}
        for rule in self.manifest["rules"]:
            for eid in rule["review"]["evidence"]:
                self.rewrite_receipt(eid, lambda r: r.update(rule_digest=rule_digest(rule, evidence)))
        self.rewrite_receipt(
            self.manifest["publication"]["authorization"],
            lambda r: r.update(rules_digest=rules_digest(self.manifest["rules"], evidence)),
        )

    def rebind_input(self, run: dict) -> None:
        evidence = {e["id"]: e for e in self.manifest["evidence"]}
        run["input_digest"] = input_digest(
            run["inputs"], [evidence[eid] for eid in run["production_inputs"]],
            [evidence[eid] for eid in run["context_sources"]],
        )
        for attempt in run["attempts"]:
            for result in attempt["outcomes"].values():
                for eid in result["evidence"]:
                    self.rewrite_receipt(eid, lambda r: r.update(input_digest=run["input_digest"]))
        self.rewrite_receipt(
            run["execution_evidence"][0],
            lambda r: r.update(input_digest=run["input_digest"], context_sources=run["context_sources"]),
        )

    def result(self) -> dict:
        return validate_manifest(self.manifest, self.root)


class WorkflowCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = StudyFixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def assert_error(self, code: str) -> dict:
        result = self.fixture.result()
        self.assertFalse(result["structural_valid"], result)
        self.assertIn(code, [error["code"] for error in result["errors"]], result)
        return result

    def test_valid_pending_is_not_ready(self):
        result = self.fixture.result()
        self.assertTrue(result["structural_valid"], result)
        self.assertFalse(result["ready_for_publication"])
        self.assertIn("missing_test", [gap["code"] for gap in result["readiness_gaps"]])

    def test_complete_synthetic_bookkeeping_is_ready(self):
        self.fixture.finish()
        result = self.fixture.result()
        self.assertTrue(result["structural_valid"], result)
        self.assertTrue(result["ready_for_publication"], result)

    def test_path_traversal_rejected(self):
        self.fixture.manifest["candidate"]["files"][0]["path"] = "../outside.txt"
        self.assert_error("path")

    def test_absolute_windows_path_rejected(self):
        self.fixture.manifest["candidate"]["files"][0]["path"] = "C:/Windows/test"
        self.assert_error("path")

    def test_missing_hash_rejected(self):
        self.fixture.manifest["evidence"][0].pop("sha256")
        self.assert_error("sha256")

    def test_missing_file_rejected(self):
        (self.root / self.fixture.skill["path"]).unlink()
        self.assert_error("missing_file")

    def test_candidate_tamper_rejected(self):
        (self.root / self.fixture.skill["path"]).write_text("changed")
        self.assert_error("hash_mismatch")

    def test_false_accepted_review_without_receipt(self):
        self.fixture.manifest["rules"][0]["review"]["status"] = "accepted"
        self.assert_error("empty")

    def test_review_receipt_wrong_candidate_rejected(self):
        self.fixture.finish()
        review = self.fixture.manifest["rules"][0]["review"]["evidence"][0]
        self.fixture.rewrite_receipt(review, lambda r: r.update(candidate_digest="0" * 64))
        self.assert_error("review_binding")

    def test_holdout_production_leakage_rejected(self):
        held = self.fixture.add_evidence("reference", "holdout", "held-out content")
        self.fixture.manifest["production_inputs"].append(held["id"])
        self.assert_error("holdout_leakage")

    def test_renamed_holdout_bytes_rejected(self):
        self.fixture.add_evidence("reference", "holdout", "held-out content")
        disguised = self.fixture.add_evidence("reference", "development", "held-out content")
        self.fixture.manifest["production_inputs"].append(disguised["id"])
        self.assert_error("holdout_leakage")

    def test_holdout_in_context_rejected(self):
        run = self.fixture.add_run("T01-A")
        held = self.fixture.add_evidence("reference", "holdout", "held-out content")
        run["context_sources"].append(held["id"])
        self.fixture.rebind_input(run)
        self.assert_error("holdout_leakage")

    def test_holdout_human_intervention_rejected(self):
        run = self.fixture.add_run("T01-A")
        held = self.fixture.add_evidence("reference", "holdout", "held-out content")
        run["attempts"][0]["human_interventions"].append({
            "description": "Used held-out material to correct the output.",
            "evidence": [held["id"]],
        })
        self.assert_error("holdout_leakage")

    def test_missing_hash_in_run_production_input_reports_error(self):
        run = self.fixture.add_run("T01-A")
        evidence = self.fixture.manifest["evidence"][0]
        run["production_inputs"].append(evidence["id"])
        evidence.pop("sha256")
        self.assert_error("sha256")

    def test_same_session_repeats_rejected_even_with_identical_inputs(self):
        first = self.fixture.add_run("T01-A")
        second = self.fixture.add_run("T01-B")
        self.assertEqual(first["input_digest"], second["input_digest"])
        second["session_id"] = first["session_id"]
        self.fixture.rewrite_receipt(
            second["execution_evidence"][0], lambda r: r.update(session_id=first["session_id"])
        )
        self.assert_error("session_reuse")

    def test_changed_repeat_input_rejected(self):
        self.fixture.add_run("T01-A")
        second = self.fixture.add_run("T01-B")
        second["inputs"]["randomness"] = {"policy": "fixed", "seed": 7}
        self.assert_error("input_digest")

    def test_run_record_cannot_replace_result(self):
        run = self.fixture.add_run("T01-A")
        run["attempts"][0]["outcomes"]["technical"]["evidence"] = run["execution_evidence"]
        self.assert_error("result_kind")

    def test_execution_record_must_match_session(self):
        run = self.fixture.add_run("T01-A")
        self.fixture.rewrite_receipt(run["execution_evidence"][0], lambda r: r.update(session_id="other"))
        self.assert_error("execution_binding")

    def test_repeat_input_cannot_include_prior_output(self):
        first = self.fixture.add_run("T01-A")
        second = self.fixture.add_run("T01-B")
        second["inputs"]["files"].append(first["attempts"][0]["outputs"][0])
        second["input_digest"] = input_digest(second["inputs"], [])
        for check in ("technical", "visual", "game"):
            result_id = second["attempts"][0]["outcomes"][check]["evidence"][0]
            self.fixture.rewrite_receipt(result_id, lambda r: r.update(input_digest=second["input_digest"]))
        self.fixture.rewrite_receipt(
            second["execution_evidence"][0], lambda r: r.update(input_digest=second["input_digest"])
        )
        self.assert_error("answer_leakage")

    def test_symlink_escape_rejected_where_supported(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.txt"
            target.write_text("outside")
            link = self.root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("OS does not permit creating symlinks")
            self.fixture.manifest["candidate"]["files"][0]["path"] = "linked/outside.txt"
            self.assert_error("path_escape")

    def test_tested_claim_requires_success_not_just_records(self):
        run = self.fixture.add_run("T01-A", game="not_run")
        rule = self.fixture.manifest["rules"][0]
        rule["validation"] = "tested_local"
        rule["evidence"].extend(run["execution_evidence"])
        self.assert_error("unsupported_claim")

    def test_no_game_is_valid_but_blocks_readiness(self):
        self.fixture.add_run("T01-A", game="not_run")
        result = self.fixture.result()
        self.assertTrue(result["structural_valid"], result)
        self.assertFalse(result["ready_for_publication"])
        self.assertIn("unfinished_test", [gap["code"] for gap in result["readiness_gaps"]])

    def test_game_pass_needs_capture(self):
        run = self.fixture.add_run("T01-A")
        result_id = run["attempts"][0]["outcomes"]["game"]["evidence"][0]
        self.fixture.rewrite_receipt(result_id, lambda r: r.update(supporting_evidence=[]))
        self.assert_error("game_capture")

    def test_authorization_scope_must_match_all_files(self):
        self.fixture.finish()
        authorization = self.fixture.manifest["publication"]["authorization"]
        self.fixture.rewrite_receipt(authorization, lambda r: r.update(files=[self.fixture.baseline]))
        self.assert_error("authorization_scope")

    def test_failed_baseline_is_an_honest_completed_comparison(self):
        self.fixture.finish()
        baseline = self.fixture.manifest["runs"][0]
        visual = baseline["attempts"][0]["outcomes"]["visual"]
        visual["status"] = "fail"
        self.fixture.rewrite_receipt(visual["evidence"][0], lambda r: r.update(status="fail"))
        result = self.fixture.result()
        self.assertTrue(result["structural_valid"], result)
        self.assertTrue(result["ready_for_publication"], result)

    def test_narrow_required_cases_cannot_hide_recorded_failure(self):
        self.fixture.finish()
        self.fixture.manifest["publication"]["required_test_cases"] = ["T01-A"]
        transfer = next(run for run in self.fixture.manifest["runs"] if run["test_case"] == "T02")
        outcome = transfer["attempts"][0]["outcomes"]["game"]
        outcome["status"] = "fail"
        self.fixture.rewrite_receipt(outcome["evidence"][0], lambda r: r.update(status="fail"))
        self.fixture.refresh_approvals()
        result = self.fixture.result()
        self.assertTrue(result["structural_valid"], result)
        self.assertFalse(result["ready_for_publication"])
        self.assertIn("unfinished_recorded_run", [gap["code"] for gap in result["readiness_gaps"]])

    def test_copied_candidate_files_do_not_make_baseline(self):
        self.fixture.finish()
        baseline = self.fixture.manifest["runs"][0]
        copied = self.fixture.file("baseline/copy.md", (self.root / self.fixture.skill["path"]).read_bytes())
        baseline["skill"]["files"] = [self.fixture.skill, copied]
        baseline["skill_digest"] = files_digest(baseline["skill"]["files"])
        for check in ("technical", "visual", "game"):
            evidence_id = baseline["attempts"][0]["outcomes"][check]["evidence"][0]
            self.fixture.rewrite_receipt(evidence_id, lambda r: r.update(skill_digest=baseline["skill_digest"]))
        self.fixture.rewrite_receipt(
            baseline["execution_evidence"][0], lambda r: r.update(skill_digest=baseline["skill_digest"])
        )
        self.assert_error("baseline_skill")

    def test_changed_rule_claim_invalidates_review(self):
        self.fixture.finish()
        self.fixture.manifest["rules"][0]["claim"] = "A different, unreviewed rule."
        self.assert_error("review_rule_digest")

    def test_extra_repeat_context_changes_frozen_input(self):
        self.fixture.add_run("T01-A")
        second = self.fixture.add_run("T01-B")
        extra = self.fixture.add_evidence("reference", "study", "extra context")
        second["context_sources"] = [extra["id"]]
        self.fixture.rebind_input(second)
        self.assert_error("repeat_mismatch")

    def test_game_capture_is_forbidden_as_repeat_context(self):
        first = self.fixture.add_run("T01-A")
        second = self.fixture.add_run("T01-B")
        capture = next(e for e in self.fixture.manifest["evidence"]
                       if e["kind"] == "game_capture" and e["run_id"] == first["run_id"])
        second["context_sources"] = [capture["id"]]
        self.fixture.rebind_input(second)
        self.assert_error("answer_leakage")

    def test_boolean_cannot_replace_attempt_integer_in_receipt(self):
        run = self.fixture.add_run("T01-A")
        self.fixture.rewrite_receipt(
            run["attempts"][0]["outcomes"]["technical"]["evidence"][0],
            lambda r: r.update(attempt=True),
        )
        self.assert_error("result_binding")

    def test_game_capture_from_other_attempt_rejected(self):
        run = self.fixture.add_run("T01-A")
        capture = next(e for e in self.fixture.manifest["evidence"] if e["kind"] == "game_capture")
        capture["run_id"] = "another-run"
        self.assert_error("capture_binding")

    def test_malformed_nested_types_return_diagnostics(self):
        for path in [
            ("evidence", 0, "sha256"), ("rules", 0, "validation"),
            ("rules", 0, "review", "status"),
        ]:
            with self.subTest(path=path):
                malformed = copy.deepcopy(self.fixture.manifest)
                parent = malformed
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = {}
                self.assertFalse(validate_manifest(malformed, self.root)["structural_valid"])

    def test_pending_review_still_blocks_with_authorization(self):
        self.fixture.finish()
        self.fixture.manifest["rules"][0]["review"] = {"status": "pending", "evidence": []}
        result = self.fixture.result()
        self.assertTrue(result["structural_valid"], result)
        self.assertFalse(result["ready_for_publication"])

    def test_attempt_count_cannot_hide_attempts(self):
        run = self.fixture.add_run("T01-A")
        run["attempt_count"] = 2
        self.assert_error("attempt_count")

    def test_baseline_preserves_brief(self):
        self.fixture.add_run("T00")
        run = self.fixture.add_run("T01-A")
        # Keep every per-run receipt valid, but replace the baseline's brief with the variant's.
        variant = self.fixture.add_run("T03")
        baseline = self.fixture.manifest["runs"][0]
        baseline["inputs"]["brief"] = variant["inputs"]["brief"]
        baseline["input_digest"] = input_digest(baseline["inputs"], [])
        for check in ("technical", "visual", "game"):
            evidence_id = baseline["attempts"][0]["outcomes"][check]["evidence"][0]
            self.fixture.rewrite_receipt(evidence_id, lambda r: r.update(input_digest=baseline["input_digest"]))
        self.fixture.rewrite_receipt(
            baseline["execution_evidence"][0], lambda r: r.update(input_digest=baseline["input_digest"])
        )
        self.assertNotEqual(baseline["input_digest"], run["input_digest"])
        self.assert_error("baseline_mismatch")

    def test_malformed_shapes_return_diagnostics(self):
        result = validate_manifest([], self.root)
        self.assertFalse(result["structural_valid"])

    def test_cli_nonzero_on_invalid_zero_on_pending(self):
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(self.fixture.manifest), encoding="utf-8")
        command = [sys.executable, "-B", str(CHECKS_DIR / "workflow_check.py"),
                   "--manifest", str(manifest_path), "--json"]
        pending = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(pending.returncode, 0, pending.stderr)
        self.assertFalse(json.loads(pending.stdout)["ready_for_publication"])
        (self.root / self.fixture.skill["path"]).write_text("tamper")
        invalid = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        self.assertFalse(json.loads(invalid.stdout)["structural_valid"])


if __name__ == "__main__":
    unittest.main()
