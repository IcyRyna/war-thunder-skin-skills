#!/usr/bin/env python3
"""Validate a local Skill study manifest without promoting or publishing anything."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

CHECKS = ("technical", "visual", "game")
TEST_CASES = ("T00", "T01-A", "T01-B", "T01-C", "T02", "T03")
ROLES = {"study", "development", "holdout"}
KINDS = {
    "reference", "observation", "run_record", "technical_result", "visual_result",
    "game_result", "game_capture", "user_review", "publication_authorization", "other",
}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_digest(value: Any) -> str:
    """Digest JSON identity, independently of source indentation or key ordering."""
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def files_digest(files: list[dict[str, Any]]) -> str:
    return canonical_digest(sorted(
        ({"path": item["path"], "sha256": item["sha256"]} for item in files),
        key=lambda item: item["path"],
    ))


def input_digest(inputs: dict[str, Any], evidence: list[dict[str, Any]],
                 context: list[dict[str, Any]] | None = None) -> str:
    return canonical_digest({
        "inputs": inputs,
        "production_inputs": sorted(
            ({"id": item["id"], "sha256": item["sha256"]} for item in evidence),
            key=lambda item: item["id"],
        ),
        "context_sources": sorted(
            ({"id": item["id"], "sha256": item["sha256"]} for item in (context or [])),
            key=lambda item: item["id"],
        ),
    })


def rule_digest(rule: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> str:
    definition = {
        key: rule.get(key) for key in
        ("id", "scope", "claim", "required_checks", "validation")
    }
    definition["evidence"] = [
        {key: evidence[eid].get(key) for key in ("id", "sha256", "role", "kind")}
        for eid in rule.get("evidence", []) if isinstance(eid, str) and eid in evidence
    ] if isinstance(rule.get("evidence"), list) else []
    return canonical_digest(definition)


def rules_digest(rules: list[dict[str, Any]], evidence: dict[str, dict[str, Any]]) -> str:
    return canonical_digest(sorted(
        ({"id": rule["id"], "digest": rule_digest(rule, evidence)} for rule in rules),
        key=lambda item: item["id"],
    ))


def json_equal(left: Any, right: Any) -> bool:
    # Python equates True with 1; JSON receipt types are part of the contract.
    return canonical_digest(left) == canonical_digest(right)


def load_json(path: Path) -> Any:
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys)


class Validator:
    def __init__(self, manifest: Any, root: Path):
        self.manifest = manifest
        self.root = root.resolve()
        self.errors: list[dict[str, str]] = []
        self.gaps: list[dict[str, str]] = []
        self.evidence: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.current_digest: str | None = None
        self._file_hashes: dict[Path, str] = {}

    def error(self, code: str, location: str, message: str) -> None:
        self.errors.append({"code": code, "location": location, "message": message})

    def gap(self, code: str, message: str) -> None:
        self.gaps.append({"code": code, "message": message})

    def mapping(self, value: Any, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            self.error("type", where, "expected an object")
            return {}
        return value

    def sequence(self, value: Any, where: str, nonempty: bool = False) -> list[Any]:
        if not isinstance(value, list):
            self.error("type", where, "expected an array")
            return []
        if nonempty and not value:
            self.error("empty", where, "expected at least one item")
        return value

    def string(self, value: Any, where: str) -> bool:
        if not isinstance(value, str) or not value.strip():
            self.error("type", where, "expected a nonempty string")
            return False
        return True

    def enum(self, value: Any, options: Any, where: str) -> bool:
        if not isinstance(value, str) or value not in options:
            self.error("enum", where, f"expected one of {', '.join(sorted(options))}")
            return False
        return True

    def strings(self, value: Any, where: str, nonempty: bool = False) -> list[str]:
        items = self.sequence(value, where, nonempty)
        result = []
        for index, item in enumerate(items):
            if self.string(item, f"{where}[{index}]"):
                result.append(item)
        if len(result) != len(set(result)):
            self.error("duplicate", where, "duplicate values are not allowed")
        return result

    def digest(self, value: Any, where: str) -> bool:
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            self.error("sha256", where, "expected a lowercase SHA-256 hex digest")
            return False
        return True

    def local_path(self, value: Any, where: str) -> Path | None:
        if not self.string(value, where):
            return None
        # Reject platform-specific absolute paths, ADS, traversal, and ambiguous spelling.
        path = PurePosixPath(value)
        if (
            "\\" in value or ":" in value or path.is_absolute()
            or any(part in {".", "..", ""} for part in value.split("/"))
        ):
            self.error("path", where, "use a normalized relative POSIX path inside root")
            return None
        resolved = (self.root / Path(*path.parts)).resolve()
        if not resolved.is_relative_to(self.root):
            self.error("path_escape", where, "resolved path escapes root (including symlinks)")
            return None
        return resolved

    def file_ref(self, value: Any, where: str, versioned: bool = False) -> bool:
        before = len(self.errors)
        item = self.mapping(value, where)
        path = self.local_path(item.get("path"), where + ".path")
        good_hash = self.digest(item.get("sha256"), where + ".sha256")
        if versioned:
            self.string(item.get("version"), where + ".version")
        if path is not None:
            if not path.is_file():
                self.error("missing_file", where, f"file does not exist: {item.get('path')}")
            elif good_hash:
                try:
                    if path not in self._file_hashes:
                        digest = hashlib.sha256()
                        with path.open("rb") as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(chunk)
                        self._file_hashes[path] = digest.hexdigest()
                    if self._file_hashes[path] != item["sha256"]:
                        self.error("hash_mismatch", where, f"file bytes changed: {item['path']}")
                except OSError as exc:
                    self.error("read_error", where, str(exc))
        return len(self.errors) == before

    def file_list(self, value: Any, where: str, nonempty: bool = True) -> list[dict[str, Any]]:
        items = self.sequence(value, where, nonempty)
        result = []
        for index, item in enumerate(items):
            if self.file_ref(item, f"{where}[{index}]"):
                result.append(item)
        paths = [item["path"] for item in result]
        if len(set(paths)) != len(paths):
            self.error("duplicate_path", where, "a file path may appear only once")
        return result

    def evidence_refs(self, value: Any, where: str, nonempty: bool = False) -> list[dict[str, Any]]:
        ids = self.strings(value, where, nonempty)
        found = []
        for evidence_id in ids:
            if evidence_id not in self.evidence:
                self.error("missing_evidence", where, f"unknown evidence ID: {evidence_id}")
            else:
                found.append(self.evidence[evidence_id])
        return found

    def receipt(self, evidence: dict[str, Any], where: str) -> dict[str, Any]:
        path = self.local_path(evidence.get("path"), where + ".path")
        if path is None or not path.is_file():
            return {}
        try:
            return self.mapping(load_json(path), where)
        except (OSError, ValueError, UnicodeError) as exc:
            self.error("receipt", where, f"cannot read JSON receipt: {exc}")
            return {}

    def no_holdout(self, refs: list[dict[str, Any]], files: list[dict[str, Any]], where: str) -> None:
        # A renamed/copied holdout with the same bytes is still a leak.
        holdout_hashes = {
            e["sha256"] for e in self.evidence.values()
            if e.get("role") == "holdout" and isinstance(e.get("sha256"), str)
        }
        for item in refs + files:
            item_hash = item.get("sha256")
            if item.get("role") == "holdout" or (isinstance(item_hash, str) and item_hash in holdout_hashes):
                self.error("holdout_leakage", where, f"holdout bytes enter production: {item.get('id', item.get('path'))}")

    def check_evidence(self, manifest: dict[str, Any]) -> None:
        for index, raw in enumerate(self.sequence(manifest.get("evidence"), "evidence")):
            where = f"evidence[{index}]"
            item = self.mapping(raw, where)
            valid_id = self.string(item.get("id"), where + ".id")
            self.file_ref(item, where)
            self.enum(item.get("role"), ROLES, where + ".role")
            self.enum(item.get("kind"), KINDS, where + ".kind")
            if valid_id:
                if item["id"] in self.evidence:
                    self.error("duplicate_id", where, f"duplicate evidence ID: {item['id']}")
                else:
                    self.evidence[item["id"]] = item

    def check_result(self, result: Any, run: dict[str, Any], attempt: dict[str, Any],
                     check: str, outputs: list[dict[str, Any]], where: str) -> None:
        result = self.mapping(result, where)
        status = result.get("status")
        self.enum(status, {"pass", "fail", "not_run"}, where + ".status")
        refs = self.evidence_refs(result.get("evidence"), where + ".evidence", status != "not_run")
        if status == "not_run" and refs:
            self.error("not_run_evidence", where, "unexecuted checks cannot carry result evidence")
        for evidence in refs:
            if evidence.get("kind") != check + "_result":
                self.error("result_kind", where, f"expected {check}_result evidence, not a generic record")
                continue
            receipt = self.receipt(evidence, where + ".receipt")
            expected = {
                "run_id": run.get("run_id"), "attempt": attempt.get("attempt"),
                "check": check, "status": status, "skill_digest": run.get("skill_digest"),
                "input_digest": run.get("input_digest"), "output_digest": files_digest(outputs),
            }
            for key, value in expected.items():
                if not json_equal(receipt.get(key), value):
                    self.error("result_binding", where, f"result receipt {key} does not match this attempt")
            self.string(receipt.get("observations"), where + ".receipt.observations")
            supporting = self.evidence_refs(receipt.get("supporting_evidence"), where + ".receipt.supporting_evidence")
            if check == "game" and status == "pass":
                captures = [e for e in supporting if e.get("kind") == "game_capture"]
                if not captures:
                    self.error("game_capture", where, "game pass requires a game_capture evidence file")
                for capture in captures:
                    for key, value in {
                        "run_id": run.get("run_id"), "attempt": attempt.get("attempt"),
                        "game_version": run.get("game_version"), "output_digest": files_digest(outputs),
                    }.items():
                        if not json_equal(capture.get(key), value):
                            self.error("capture_binding", where, f"game capture {key} does not match this attempt")
                    path = self.local_path(capture.get("path"), where + ".capture.path")
                    if path is not None and path.is_file():
                        try:
                            with path.open("rb") as stream:
                                header = stream.read(12)
                            if not (
                                header.startswith(b"\x89PNG\r\n\x1a\n")
                                or header.startswith(b"\xff\xd8\xff")
                                or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
                            ):
                                self.error("capture_format", where, "game_capture must be PNG, JPEG, or WebP image bytes")
                        except OSError as exc:
                            self.error("read_error", where, str(exc))
                if receipt.get("game_version") != run.get("game_version"):
                    self.error("game_version", where, "game evidence must identify this run's game version")
            if status == "pass" and not outputs:
                self.error("missing_outputs", where, "a passing check requires actual hashed outputs")

    def check_run(self, raw: Any, index: int) -> None:
        where = f"runs[{index}]"
        run = self.mapping(raw, where)
        run_id = run.get("run_id")
        if self.string(run_id, where + ".run_id"):
            if run_id in self.runs:
                self.error("duplicate_id", where, f"duplicate run ID: {run_id}")
            else:
                self.runs[run_id] = run
        self.enum(run.get("test_case"), TEST_CASES, where + ".test_case")
        self.string(run.get("session_id"), where + ".session_id")
        if run.get("fresh_session") is not True:
            self.error("session", where, "actual eval runs require a fresh independent session")
        self.string(run.get("agent_version"), where + ".agent_version")
        self.string(run.get("game_version"), where + ".game_version")
        self.strings(run.get("scope"), where + ".scope", True)
        self.string(run.get("vehicle"), where + ".vehicle")
        self.string(run.get("theme"), where + ".theme")
        self.string(run.get("started_at"), where + ".started_at")
        execution = self.evidence_refs(run.get("execution_evidence"), where + ".execution_evidence", True)
        if not any(item.get("kind") == "run_record" for item in execution):
            self.error("execution_evidence", where, "run requires a run_record, not only output hashes")
        context = self.evidence_refs(run.get("context_sources"), where + ".context_sources")
        inputs = self.mapping(run.get("inputs"), where + ".inputs")
        input_files = []
        for key in ("brief", "profile", "tools", "rubric"):
            if self.file_ref(inputs.get(key), where + ".inputs." + key, versioned=True):
                input_files.append(inputs[key])
        input_files.extend(self.file_list(inputs.get("files"), where + ".inputs.files", nonempty=False))
        randomness = self.mapping(inputs.get("randomness"), where + ".inputs.randomness")
        self.enum(randomness.get("policy"), {"fixed", "unspecified", "unsupported"}, where + ".inputs.randomness.policy")
        if "seed" not in randomness:
            self.error("missing_seed_policy", where, "record a seed value or explicit null")
        if randomness.get("policy") == "fixed" and randomness.get("seed") is None:
            self.error("seed", where, "fixed policy requires a seed")
        if randomness.get("policy") in ("unspecified", "unsupported") and randomness.get("seed") is not None:
            self.error("seed", where, "unspecified/unsupported policy uses a null seed")
        prod = self.evidence_refs(run.get("production_inputs"), where + ".production_inputs")
        self.no_holdout(prod, input_files, where)
        skill = self.mapping(run.get("skill"), where + ".skill")
        self.string(skill.get("version"), where + ".skill.version")
        skill_files = self.file_list(skill.get("files"), where + ".skill.files")
        self.no_holdout([], skill_files, where + ".skill")
        if self.digest(run.get("skill_digest"), where + ".skill_digest") and run["skill_digest"] != files_digest(skill_files):
            self.error("skill_digest", where, "skill digest differs from its hashed file manifest")
        input_hash_valid = self.digest(run.get("input_digest"), where + ".input_digest")
        if input_hash_valid and all(
            isinstance(item.get("sha256"), str) and SHA256.fullmatch(item["sha256"]) for item in prod + context
        ):
            if run["input_digest"] != input_digest(inputs, prod, context):
                self.error("input_digest", where, "input digest differs from actual frozen input manifest")
        attempts = self.sequence(run.get("attempts"), where + ".attempts", True)
        for attempt_index, raw_attempt in enumerate(attempts, 1):
            loc = f"{where}.attempts[{attempt_index - 1}]"
            attempt = self.mapping(raw_attempt, loc)
            if type(attempt.get("attempt")) is not int or attempt["attempt"] != attempt_index:
                self.error("attempt_sequence", loc, "retain attempts numbered consecutively from 1")
            outputs = self.file_list(attempt.get("outputs"), loc + ".outputs", nonempty=False)
            for intervention_index, raw_intervention in enumerate(self.sequence(
                attempt.get("human_interventions"), loc + ".human_interventions"
            )):
                iloc = f"{loc}.human_interventions[{intervention_index}]"
                intervention = self.mapping(raw_intervention, iloc)
                self.string(intervention.get("description"), iloc + ".description")
                intervention_refs = self.evidence_refs(intervention.get("evidence"), iloc + ".evidence", True)
                self.no_holdout(intervention_refs, [], iloc + ".evidence")
            outcomes = self.mapping(attempt.get("outcomes"), loc + ".outcomes")
            for check in CHECKS:
                self.check_result(outcomes.get(check), run, attempt, check, outputs, loc + ".outcomes." + check)
        if type(run.get("attempt_count")) is not int or run["attempt_count"] != len(attempts):
            self.error("attempt_count", where, "attempt_count must equal the complete attempt array")
        for item in execution:
            if item.get("kind") != "run_record":
                continue
            record = self.receipt(item, where + ".execution_evidence")
            for key in ("run_id", "session_id", "fresh_session", "input_digest", "skill_digest",
                        "attempt_count", "context_sources", "agent_version", "started_at",
                        "scope", "vehicle", "theme"):
                if not json_equal(record.get(key), run.get(key)):
                    self.error("execution_binding", where, f"run_record {key} does not match this run")
            if not json_equal(record.get("recorded_attempts"), list(range(1, len(attempts) + 1))):
                self.error("execution_attempts", where, "run_record must account for every attempt")
            self.string(record.get("observations"), where + ".execution_evidence.observations")

    @staticmethod
    def successful(run: dict[str, Any], checks: list[str] | tuple[str, ...] = CHECKS) -> bool:
        attempts = run.get("attempts")
        if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
            return False
        outcomes = attempts[-1].get("outcomes")
        return isinstance(outcomes, dict) and all(
            isinstance(outcomes.get(check), dict) and outcomes[check].get("status") == "pass"
            for check in checks
        )

    def check_matrix(self) -> None:
        runs = list(self.runs.values())
        by_case: dict[str, list[dict[str, Any]]] = {
            case: [run for run in runs if run.get("test_case") == case]
            for case in TEST_CASES
        }
        repeats = [run for run in runs if run.get("test_case") in TEST_CASES[1:4]]
        if repeats:
            first = repeats[0]
            for run in repeats[1:]:
                for key in ("input_digest", "skill_digest", "agent_version", "vehicle", "theme"):
                    if run.get(key) != first.get(key):
                        self.error("repeat_mismatch", "runs", f"T01 repeats must preserve {key}")
        sessions = [run.get("session_id") for run in runs if isinstance(run.get("session_id"), str)]
        if len(sessions) != len(set(sessions)):
            self.error("session_reuse", "runs", "each eval run must use a distinct session_id")
        prior_answers = {
            e["id"] for e in self.evidence.values()
            if e.get("kind") in {"run_record", "technical_result", "visual_result", "game_result", "game_capture", "user_review"}
        }
        answer_hashes = {
            e["sha256"] for e in self.evidence.values() if e["id"] in prior_answers
        }
        answer_hashes.update(
            output["sha256"] for run in runs for attempt in run["attempts"] for output in attempt["outputs"]
        )
        for run in runs:
            if any(item in prior_answers for item in run.get("context_sources", []) if isinstance(item, str)):
                self.error("answer_leakage", "runs", f"{run.get('run_id')} context includes prior output/feedback")
            context = self.evidence_refs(run.get("context_sources"), "runs.context_sources")
            self.no_holdout(context, [], "runs.context_sources")
            declared_inputs = context + [
                self.evidence[eid] for eid in run["production_inputs"]
            ] + [
                run["inputs"][key] for key in ("brief", "profile", "tools", "rubric")
            ] + run["inputs"]["files"]
            if any(item["sha256"] in answer_hashes for item in declared_inputs):
                self.error("answer_leakage", "runs", f"{run.get('run_id')} input includes eval output or feedback bytes")
            if run.get("test_case") != "T00" and run.get("skill_digest") != self.current_digest:
                self.gap("stale_run", f"{run.get('run_id')} tests a different candidate; it cannot qualify this revision")
        if repeats:
            first = repeats[0]
            for baseline in by_case["T00"]:
                for key in ("brief", "profile", "tools", "rubric"):
                    left = baseline.get("inputs", {}).get(key, {})
                    right = first.get("inputs", {}).get(key, {})
                    if left.get("sha256") != right.get("sha256") or left.get("version") != right.get("version"):
                        self.error("baseline_mismatch", "runs", f"T00 must preserve {key} bytes and version")
                for key in ("randomness",):
                    if baseline.get("inputs", {}).get(key) != first.get("inputs", {}).get(key):
                        self.error("baseline_mismatch", "runs", f"T00 must preserve {key}")
                if baseline.get("agent_version") != first.get("agent_version"):
                    self.error("baseline_mismatch", "runs", "T00 must preserve agent_version")
                if baseline.get("skill_digest") == first.get("skill_digest"):
                    self.error("baseline_skill", "runs", "T00 must omit the tested style module")
                elif {item["sha256"] for item in baseline["skill"]["files"]} == {
                    item["sha256"] for item in first["skill"]["files"]
                }:
                    self.error("baseline_skill", "runs", "renaming identical Skill files is not a baseline ablation")
            for transfer in by_case["T02"]:
                if transfer.get("vehicle") == first.get("vehicle"):
                    self.error("transfer_vehicle", "runs", "T02 requires a different vehicle")
            for variant in by_case["T03"]:
                if variant.get("vehicle") != first.get("vehicle"):
                    self.error("variant_vehicle", "runs", "T03 preserves the tested vehicle")
                if variant.get("inputs", {}).get("brief", {}).get("sha256") == first.get("inputs", {}).get("brief", {}).get("sha256"):
                    self.error("variant_brief", "runs", "T03 requires an actual changed brief")
            for changed in by_case["T02"] + by_case["T03"]:
                for key in ("tools", "rubric"):
                    if any(changed["inputs"][key][field] != first["inputs"][key][field] for field in ("sha256", "version")):
                        self.error("transfer_controls", "runs", f"T02/T03 must preserve {key} bytes and version")
                if changed["agent_version"] != first["agent_version"]:
                    self.error("transfer_controls", "runs", "T02/T03 must preserve agent_version")

    def check_review(self, raw: Any, rule: dict[str, Any], where: str) -> str | None:
        review = self.mapping(raw, where)
        status = review.get("status")
        self.enum(status, {"pending", "accepted", "rejected"}, where + ".status")
        refs = self.evidence_refs(review.get("evidence"), where + ".evidence", status in ("accepted", "rejected"))
        for item in refs:
            if item.get("kind") != "user_review":
                self.error("review_evidence", where, "review decisions require user_review receipts")
                continue
            receipt = self.receipt(item, where + ".receipt")
            if receipt.get("decision") != status or receipt.get("candidate_digest") != self.current_digest:
                self.error("review_binding", where, "review decision and candidate digest must match")
            if rule.get("id") not in self.strings(receipt.get("rule_ids"), where + ".receipt.rule_ids", True):
                self.error("review_scope", where, "receipt does not cover this rule")
            if receipt.get("rule_digest") != rule_digest(rule, self.evidence):
                self.error("review_rule_digest", where, "review does not cover the current rule definition and evidence")
            self.string(receipt.get("reviewer"), where + ".receipt.reviewer")
            self.string(receipt.get("provenance"), where + ".receipt.provenance")
        return status if isinstance(status, str) else None

    def check_rules(self, manifest: dict[str, Any]) -> None:
        ids: set[str] = set()
        rules = self.sequence(manifest.get("rules"), "rules")
        if not rules:
            self.gap("no_rules", "no scoped rules are available for review or publication")
        for index, raw in enumerate(rules):
            where = f"rules[{index}]"
            rule = self.mapping(raw, where)
            rule_id = rule.get("id")
            if self.string(rule_id, where + ".id"):
                if rule_id in ids:
                    self.error("duplicate_id", where, f"duplicate rule ID: {rule_id}")
                ids.add(rule_id)
            scope = self.strings(rule.get("scope"), where + ".scope", True)
            self.string(rule.get("claim"), where + ".claim")
            required = self.strings(rule.get("required_checks"), where + ".required_checks", True)
            for check in required:
                self.enum(check, CHECKS, where + ".required_checks")
            refs = self.evidence_refs(rule.get("evidence"), where + ".evidence", True)
            validation = rule.get("validation")
            self.enum(validation, {"unverified", "tested_local", "tested_transfer"}, where + ".validation")
            review = self.check_review(rule.get("review"), rule, where + ".review")
            if review != "accepted":
                self.gap("rule_review", f"{rule_id}: review is {review or 'invalid'}")
            if validation == "unverified":
                self.gap("unverified_rule", f"{rule_id}: claim has not been empirically verified")
            elif validation in ("tested_local", "tested_transfer"):
                eligible = []
                for run in self.runs.values():
                    if run.get("test_case") == "T00" or run.get("skill_digest") != self.current_digest:
                        continue
                    if not set(scope).issubset(set(run.get("scope", []))) or not self.successful(run, required):
                        continue
                    last = run["attempts"][-1]
                    used_ids = {
                        eid for check in required
                        for eid in last["outcomes"][check].get("evidence", [])
                    }
                    if used_ids.issubset({item["id"] for item in refs}):
                        eligible.append(run)
                local = any(run.get("test_case") in TEST_CASES[1:4] for run in eligible)
                transfer = any(run.get("test_case") in {"T02", "T03"} for run in eligible)
                if not local or (validation == "tested_transfer" and not transfer):
                    self.error("unsupported_claim", where, "tested claim lacks applicable successful current-candidate result evidence")
            self.no_holdout(refs, [], where + ".evidence")

    def check_publication(self, manifest: dict[str, Any]) -> None:
        publication = self.mapping(manifest.get("publication"), "publication")
        required = self.strings(publication.get("required_test_cases"), "publication.required_test_cases", True)
        for case in required:
            self.enum(case, TEST_CASES, "publication.required_test_cases")
        for run in self.runs.values():
            if run["test_case"] != "T00" and run["skill_digest"] == self.current_digest and not self.successful(run):
                self.gap("unfinished_recorded_run", f"{run['run_id']}: a recorded candidate failure/unfinished check cannot be hidden by narrowing required_test_cases")
            elif run["test_case"] == "T00" and any(
                run["attempts"][-1]["outcomes"][check]["status"] == "not_run" for check in CHECKS
            ):
                self.gap("unfinished_recorded_baseline", f"{run['run_id']}: recorded baseline comparison is unfinished")
        # The pilot can have narrower declared tests; missing repeats/transfer still limit claims.
        for case in required:
            candidates = [
                run for run in self.runs.values()
                if run.get("test_case") == case
                and (case == "T00" or run.get("skill_digest") == self.current_digest)
            ]
            if not candidates:
                self.gap("missing_test", f"{case}: no run of the applicable candidate")
            elif case == "T00":
                if not all(
                    run["attempts"] and all(
                        run["attempts"][-1]["outcomes"][check]["status"] != "not_run"
                        for check in CHECKS
                    )
                    for run in candidates
                ):
                    self.gap("unfinished_baseline", "T00: complete all comparison checks; honest failures remain valid baseline results")
            elif not all(self.successful(run) for run in candidates):
                self.gap("unfinished_test", f"{case}: every recorded applicable run must finish technical, visual and game checks")
        authorization = publication.get("authorization")
        if authorization is None:
            self.gap("authorization", "no explicit scoped publication authorization")
            return
        refs = self.evidence_refs([authorization], "publication.authorization", True)
        if not refs:
            return
        item = refs[0]
        if item.get("kind") != "publication_authorization":
            self.error("authorization_kind", "publication", "authorization must reference a publication_authorization receipt")
            return
        receipt = self.receipt(item, "publication.authorization.receipt")
        if receipt.get("action") != "publish" or receipt.get("authorized") is not True:
            self.error("authorization_action", "publication", "receipt must explicitly authorize publishing")
        if receipt.get("candidate_digest") != self.current_digest:
            self.error("authorization_digest", "publication", "authorization is for different candidate bytes")
        # Rules live in the study manifest, so bind them in addition to candidate files.
        if not self.errors and receipt.get("rules_digest") != rules_digest(manifest["rules"], self.evidence):
            self.error("authorization_rules_digest", "publication", "authorization is for different rule definitions")
        self.string(receipt.get("authorized_by"), "publication.authorization.authorized_by")
        self.string(receipt.get("provenance"), "publication.authorization.provenance")
        self.string(receipt.get("authorized_at"), "publication.authorization.authorized_at")
        scoped = self.file_list(receipt.get("files"), "publication.authorization.files")
        if files_digest(scoped) != self.current_digest:
            self.error("authorization_scope", "publication", "authorized files must exactly match current candidate files and hashes")

    def validate(self) -> dict[str, Any]:
        manifest = self.mapping(self.manifest, "manifest")
        if manifest.get("schema_version") != 1 or type(manifest.get("schema_version")) is not int:
            self.error("schema_version", "manifest", "schema_version must be integer 1")
        self.string(manifest.get("study_id"), "study_id")
        candidate = self.mapping(manifest.get("candidate"), "candidate")
        self.string(candidate.get("version"), "candidate.version")
        files = self.file_list(candidate.get("files"), "candidate.files")
        self.current_digest = files_digest(files)
        self.check_evidence(manifest)
        prod = self.evidence_refs(manifest.get("production_inputs"), "production_inputs")
        self.no_holdout(prod, files, "candidate")
        for index, run in enumerate(self.sequence(manifest.get("runs"), "runs")):
            self.check_run(run, index)
        # Shape errors must not cause secondary Python exceptions in relationship checks.
        if not self.errors:
            self.check_matrix()
            self.check_rules(manifest)
            self.check_publication(manifest)
        valid = not self.errors
        ready = valid and not self.gaps
        return {
            "schema_version": 1,
            "study_id": manifest.get("study_id"),
            "structural_valid": valid,
            "ready_for_publication": ready,
            "candidate_digest": self.current_digest,
            "errors": self.errors,
            "readiness_gaps": self.gaps,
            "counts": {"evidence": len(self.evidence), "runs": len(self.runs)},
            "run_results": [
                {
                    "run_id": run.get("run_id"),
                    "test_case": run.get("test_case"),
                    "attempt_count": run.get("attempt_count"),
                    "first_attempt_passed": self.successful({"attempts": run.get("attempts", [])[:1]}),
                    "final_attempt_passed": self.successful(run),
                }
                for run in self.runs.values() if isinstance(run.get("attempts"), list)
            ],
            "limits": [
                "Checks local records and byte identity; does not authenticate human authorship or infer visual quality.",
                "Missing, omitted, or undeclared context cannot be discovered from this manifest alone.",
                "No installation, upload, release, or publication is performed.",
            ],
        }


def validate_manifest(manifest: Any, root: str | Path) -> dict[str, Any]:
    return Validator(manifest, Path(root)).validate()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", type=Path, help="path root; defaults to manifest parent")
    parser.add_argument("--json", action="store_true", help="write machine-readable result")
    args = parser.parse_args(argv)
    try:
        result = validate_manifest(load_json(args.manifest), args.root or args.manifest.parent)
    except (OSError, ValueError, UnicodeError) as exc:
        result = {
            "structural_valid": False, "ready_for_publication": False,
            "errors": [{"code": "manifest_read", "location": str(args.manifest), "message": str(exc)}],
            "readiness_gaps": [],
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Structural integrity: " + ("VALID" if result["structural_valid"] else "INVALID"))
        print("Publication readiness: " + ("READY" if result["ready_for_publication"] else "NOT READY"))
        for error in result["errors"]:
            print(f"ERROR {error['code']} [{error['location']}]: {error['message']}")
        for gap in result["readiness_gaps"]:
            print(f"PENDING {gap['code']}: {gap['message']}")
    return 0 if result["structural_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
