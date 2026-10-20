"""Behavioral tests for portable, independent candidate reconstruction."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "repository.py"
SPEC = importlib.util.spec_from_file_location("repository", SCRIPT)
repository = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "src" / "demo-skill"
        self.source.mkdir(parents=True)
        self.skill = self.source / "SKILL.md"
        self.skill.write_text(
            "---\nname: demo-skill\ndescription: A portable test Skill.\n---\n\n"
            "Use [the script](scripts/run.py).\n", encoding="utf-8",
        )
        self.toolkit = self.root / "toolkits" / "scripts"
        self.toolkit.mkdir(parents=True)
        (self.toolkit / "helper.py").write_text("VALUE = 'independent package'\n", encoding="utf-8")
        (self.toolkit / "run.py").write_text("from helper import VALUE\nprint(VALUE)\n", encoding="utf-8")
        self.package = {
            "id": "demo-skill", "kind": "build", "status": "development",
            "source": "src/demo-skill",
            "includes": [{"source": "toolkits/scripts", "target": "scripts"}],
            "supplements": [],
            "baseline": {"version": "1.0", "tag": "demo-skill/v1.0", "package_sha256": "0" * 64},
        }
        self.save_catalog()

    def save_catalog(self):
        (self.root / "catalog.json").write_text(
            json.dumps({"schema_version": 1, "packages": [self.package]}), encoding="utf-8",
        )

    def assemble(self):
        return repository.assemble(self.root, self.package)

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = repository.main(["--root", str(self.root), *args])
        return code, output.getvalue(), errors.getvalue()

    def supplement(self, payload=b"reference image", *, extra_member=None):
        archive = self.root / "released.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("demo-skill/assets/reference.png", payload)
            if extra_member:
                package.writestr(extra_member, b"unsafe")
        supplement = {
            "archive_sha256": repository.file_digest(archive),
            "archive_member": "demo-skill/assets/reference.png",
            "target": "assets/reference.png",
            "sha256": repository.digest(payload), "bytes": len(payload),
        }
        self.package["supplements"] = [supplement]
        self.save_catalog()
        return archive, supplement

    def test_build_is_standalone_and_receipt_distinguishes_baseline(self):
        tree = self.assemble()
        result = repository.build(tree, self.root / "dist")
        archive_path = Path(result["archive"])
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(archive.namelist(), [
                "demo-skill/SKILL.md", "demo-skill/scripts/helper.py", "demo-skill/scripts/run.py",
            ])
            archive.extractall(self.root / "extracted")
            for info in archive.infolist():
                self.assertEqual(info.date_time, repository.ZIP_DATE)
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o644)
        shutil.rmtree(self.source)
        shutil.rmtree(self.toolkit)
        process = subprocess.run(
            [sys.executable, "-B", str(self.root / "extracted/demo-skill/scripts/run.py")],
            cwd=self.root, check=True, capture_output=True, text=True,
        )
        self.assertEqual(process.stdout.strip(), "independent package")
        receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["artifact_type"], "reconstructed-candidate")
        self.assertFalse(receipt["official_version_assigned"])
        self.assertFalse(receipt["baseline_archive_bytes_reproduced"])
        self.assertEqual(receipt["baseline"], self.package["baseline"])
        self.assertEqual(receipt["archive"]["sha256"], repository.file_digest(archive_path))
        with zipfile.ZipFile(archive_path) as archive:
            for entry in receipt["files"]:
                data = archive.read("demo-skill/" + entry["path"])
                self.assertEqual(entry["sha256"], repository.digest(data))
                self.assertEqual(entry["bytes"], len(data))

    def test_deterministic_across_locations_order_timestamps_and_modes(self):
        (self.source / "中文.txt").write_bytes(b"unchanged bytes\r\n")
        first = repository.build(self.assemble(), self.root / "dist/one")
        relocated = self.root / "relocated"
        shutil.copytree(self.source, relocated / self.package["source"])
        shutil.copytree(self.toolkit, relocated / "toolkits/scripts")
        for path in relocated.rglob("*"):
            os.utime(path, (1234567890, 1234567890))
        second_tree = repository.assemble(relocated, copy.deepcopy(self.package))
        second = repository.build(second_tree, relocated / "dist")
        self.assertEqual(Path(first["archive"]).read_bytes(), Path(second["archive"]).read_bytes())
        self.assertEqual(Path(first["receipt"]).read_bytes(), Path(second["receipt"]).read_bytes())

    def test_cli_can_run_from_unrelated_working_directory(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--root", str(self.root), "check", "--require-assets"],
            cwd=self.root.parent, check=True, capture_output=True, text=True,
        )
        self.assertIn("PASS demo-skill", result.stdout)

    def test_file_include_has_explicit_target(self):
        schema = self.root / "schema.json"
        schema.write_text('{"type":"object"}', encoding="utf-8")
        self.package["includes"].append({"source": "schema.json", "target": "references/schema.json"})
        self.assertEqual(self.assemble().files["references/schema.json"]["data"], schema.read_bytes())

    def test_duplicate_includes_are_rejected_even_when_identical(self):
        self.package["includes"].append(dict(self.package["includes"][0]))
        with self.assertRaisesRegex(repository.RepositoryError, "collision"):
            self.assemble()

    def test_casefold_output_collision_is_rejected(self):
        (self.source / "scripts").mkdir()
        (self.source / "scripts/HELPER.py").write_text("same name", encoding="utf-8")
        with self.assertRaisesRegex(repository.RepositoryError, "collision"):
            self.assemble()

    def test_file_directory_collision_is_rejected(self):
        (self.source / "scripts").write_bytes(b"a file")
        with self.assertRaisesRegex(repository.RepositoryError, "collision"):
            self.assemble()

    def test_directory_case_collision_is_rejected(self):
        (self.root / "another.py").write_bytes(b"another file")
        self.package["includes"].append({"source": "another.py", "target": "Scripts/another.py"})
        with self.assertRaisesRegex(repository.RepositoryError, "case collision"):
            self.assemble()

    def test_unreadable_subtree_cannot_silently_make_an_incomplete_package(self):
        private = self.source / "private"
        private.mkdir()
        (private / "required.py").write_bytes(b"required")
        original = os.scandir

        def denied(path):
            if Path(path) == private:
                raise PermissionError("test directory enumeration failure")
            return original(path)

        with mock.patch.object(repository.os, "scandir", side_effect=denied):
            with self.assertRaisesRegex(repository.RepositoryError, "Cannot enumerate"):
                self.assemble()

    def test_source_traversal_absolute_and_windows_paths_are_rejected(self):
        for value in ("../outside", "/absolute", "C:/outside", "src\\demo-skill"):
            with self.subTest(value=value):
                self.package["source"] = value
                with self.assertRaises(repository.RepositoryError):
                    self.assemble()

    def test_include_target_traversal_and_reserved_names_are_rejected(self):
        for target in ("../scripts", "/scripts", "C:/scripts", "CON", "scripts/../other", "scripts."):
            with self.subTest(target=target):
                self.package["includes"][0]["target"] = target
                with self.assertRaises(repository.RepositoryError):
                    self.assemble()

    def test_symlink_source_is_rejected(self):
        link = self.root / "linked-scripts"
        try:
            link.symlink_to(self.toolkit, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"OS does not permit unprivileged symlinks: {exc}")
        self.package["includes"][0]["source"] = "linked-scripts"
        with self.assertRaisesRegex(repository.RepositoryError, "Symlink|reparse"):
            self.assemble()

    def test_nested_symlink_is_rejected(self):
        link = self.source / "linked"
        try:
            link.symlink_to(self.toolkit, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"OS does not permit unprivileged symlinks: {exc}")
        with self.assertRaisesRegex(repository.RepositoryError, "Symlink|reparse"):
            self.assemble()

    def test_cache_files_and_empty_cache_directories_are_rejected(self):
        for name in ("__pycache__", ".numba-cache"):
            with self.subTest(name=name):
                path = self.source / name
                path.mkdir()
                with self.assertRaisesRegex(repository.RepositoryError, "Cache|cache"):
                    self.assemble()
                path.rmdir()
        (self.source / "bad.pyc").write_bytes(b"cache")
        with self.assertRaisesRegex(repository.RepositoryError, "cache"):
            self.assemble()

    def test_markdown_links_validate_injected_files_and_relative_references(self):
        reference = self.source / "references"
        reference.mkdir()
        (reference / "guide.md").write_text(
            "[injected](../scripts/helper.py#anchor)\n[skill](../SKILL.md)\n"
            "[remote](https://example.com/not-downloaded)\n"
            "[reference][ref]\n\n[ref]: ../scripts/run.py\n", encoding="utf-8",
        )
        self.assemble()

    def test_missing_markdown_links_are_rejected(self):
        self.skill.write_text(self.skill.read_text(encoding="utf-8") + "[missing](references/missing.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(repository.RepositoryError, "Missing package link"):
            self.assemble()

    def test_missing_reference_style_links_are_rejected(self):
        self.skill.write_text(self.skill.read_text(encoding="utf-8") + "[missing][ref]\n[ref]: missing.md\n", encoding="utf-8")
        with self.assertRaisesRegex(repository.RepositoryError, "Missing package link"):
            self.assemble()

    def test_link_traversal_and_absolute_paths_are_rejected(self):
        original = self.skill.read_text(encoding="utf-8")
        for link in ("../outside.md", "%2e%2e/outside.md", "/absolute.md", "C:/local.md", "file:///local.md"):
            with self.subTest(link=link):
                self.skill.write_text(original + f"[unsafe]({link})\n", encoding="utf-8")
                with self.assertRaises(repository.RepositoryError):
                    self.assemble()

    def test_markdown_link_parentheses_escapes_and_spaces(self):
        for name in ("guide(v2).md", "guide space.md"):
            (self.source / name).write_text("guide", encoding="utf-8")
        self.skill.write_text(
            self.skill.read_text(encoding="utf-8") +
            "\n[guide](guide(v2).md)\n[escaped](guide\\(v2\\).md)\n"
            "[space](<guide space.md>)\n[ref][guide]\n[guide]: guide(v2).md\n",
            encoding="utf-8",
        )
        self.assemble()
        (self.source / "guide(v2).md").unlink()
        with self.assertRaisesRegex(repository.RepositoryError, "Missing package link"):
            self.assemble()

    def test_prose_and_fenced_examples_are_not_guessed_as_links(self):
        self.skill.write_text(
            self.skill.read_text(encoding="utf-8") +
            "\nThe user supplies input.png and output.json.\n`[example](not-a-file.md)`\n"
            "```md\n[example](also-not-a-file.md)\n```\n", encoding="utf-8",
        )
        self.assemble()

    def test_frontmatter_name_and_description_are_checked(self):
        for body in (
            "No frontmatter\n",
            "---\nname: wrong\ndescription: valid\n---\n",
            "---\nname: demo-skill\ndescription:\n---\n",
            "---\nname: demo-skill\ndescription: null\n---\n",
            "---\nname: demo-skill\nname: demo-skill\ndescription: valid\n---\n",
        ):
            with self.subTest(body=body):
                self.skill.write_text(body, encoding="utf-8")
                with self.assertRaises(repository.RepositoryError):
                    self.assemble()

    def test_multiline_frontmatter_description_is_supported(self):
        self.skill.write_text("---\nname: demo-skill\ndescription: >-\n  Line one\n  Line two\n---\n", encoding="utf-8")
        self.assemble()

    def test_missing_assets_are_reported_and_required_check_fails(self):
        _, supplement = self.supplement()
        self.skill.write_text(self.skill.read_text(encoding="utf-8") + "![reference](assets/reference.png)\n", encoding="utf-8")
        tree = self.assemble()
        self.assertEqual(tree.missing_assets[0]["target"], supplement["target"])
        code, output, _ = self.cli("check")
        self.assertEqual(code, 0)
        self.assertIn("NEEDS-ASSETS", output)
        self.assertEqual(self.cli("check", "--require-assets")[0], 1)
        with self.assertRaisesRegex(repository.RepositoryError, "external assets required"):
            repository.build(tree, self.root / "dist")
        self.assertFalse((self.root / "dist").exists())

    def test_assets_are_loaded_only_from_exact_release_and_member_hash(self):
        archive, supplement = self.supplement()
        archives = repository.archive_index([archive])
        tree = repository.assemble(self.root, self.package, archives)
        self.assertEqual(tree.files["assets/reference.png"]["data"], b"reference image")
        self.assertFalse(tree.missing_assets)
        self.assertEqual(self.cli("check", "--require-assets", "--asset-archive", str(archive))[0], 0)
        supplement["sha256"] = "1" * 64
        with self.assertRaisesRegex(repository.RepositoryError, "SHA-256 mismatch"):
            repository.assemble(self.root, self.package, archives)

    def test_asset_size_tamper_is_rejected(self):
        archive, supplement = self.supplement()
        supplement["bytes"] += 1
        with self.assertRaisesRegex(repository.RepositoryError, "size mismatch"):
            repository.assemble(self.root, self.package, repository.archive_index([archive]))

    def test_wrong_archive_digest_is_rejected_by_cli(self):
        archive, _ = self.supplement()
        with archive.open("ab") as stream:
            stream.write(b"tampered")
        code, _, errors = self.cli("check", "--asset-archive", str(archive))
        self.assertEqual(code, 1)
        self.assertIn("SHA-256 not declared", errors)

    def test_unsafe_member_in_asset_archive_is_rejected(self):
        archive, _ = self.supplement(extra_member="../outside")
        with self.assertRaisesRegex(repository.RepositoryError, "Unsafe"):
            repository.assemble(self.root, self.package, repository.archive_index([archive]))

    def test_duplicate_member_in_asset_archive_is_rejected(self):
        archive, _ = self.supplement(extra_member="DEMO-SKILL/assets/reference.png")
        with self.assertRaisesRegex(repository.RepositoryError, "Duplicate"):
            repository.assemble(self.root, self.package, repository.archive_index([archive]))

    def test_archive_symlink_is_rejected(self):
        archive, supplement = self.supplement()
        with zipfile.ZipFile(archive, "a") as package:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(info, "outside")
        supplement["archive_sha256"] = repository.file_digest(archive)
        with self.assertRaisesRegex(repository.RepositoryError, "symlink"):
            repository.assemble(self.root, self.package, repository.archive_index([archive]))

    def test_changed_candidates_require_explicit_force(self):
        first = repository.build(self.assemble(), self.root / "dist")
        original = Path(first["archive"]).read_bytes()
        repository.build(self.assemble(), self.root / "dist")
        (self.source / "new.txt").write_bytes(b"new content")
        with self.assertRaisesRegex(repository.RepositoryError, "Refusing"):
            repository.build(self.assemble(), self.root / "dist")
        self.assertEqual(Path(first["archive"]).read_bytes(), original)
        changed = repository.build(self.assemble(), self.root / "dist", force=True)
        self.assertNotEqual(first["sha256"], changed["sha256"])
        self.assertFalse(list((self.root / "dist").glob(".package-*")))
        self.assertFalse(list((self.root / "dist").glob(".receipt-*")))

    def test_different_receipt_also_requires_force(self):
        first = repository.build(self.assemble(), self.root / "dist")
        Path(first["receipt"]).write_bytes(b"tampered receipt")
        with self.assertRaisesRegex(repository.RepositoryError, "different receipt"):
            repository.build(self.assemble(), self.root / "dist")

    def test_output_is_confined_to_dist(self):
        for directory in ("src/demo-skill", "../dist", "dist/../src", str(self.root.parent / "external")):
            with self.subTest(directory=directory):
                with self.assertRaises(repository.RepositoryError):
                    repository.output_directory(self.root, directory)
        self.assertEqual(repository.output_directory(self.root, "dist/test"), self.root / "dist/test")

    def test_cli_list_json_and_unknown_id(self):
        code, output, _ = self.cli("list", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)[0]["id"], "demo-skill")
        code, _, errors = self.cli("check", "unknown-skill")
        self.assertEqual(code, 1)
        self.assertIn("Unknown package", errors)

    def test_invalid_catalog_reports_an_error_without_traceback(self):
        (self.root / "catalog.json").write_text("{", encoding="utf-8")
        code, _, errors = self.cli("check")
        self.assertEqual(code, 1)
        self.assertIn("Invalid catalog", errors)

    def test_malformed_supplements_report_errors_without_traceback(self):
        for supplement in ({}, None, {"archive_sha256": "not-a-digest"}):
            with self.subTest(supplement=supplement):
                self.package["supplements"] = [supplement]
                self.save_catalog()
                code, _, errors = self.cli("check")
                self.assertEqual(code, 1)
                self.assertIn("ERROR:", errors)

    def test_atomic_publication_will_not_clobber_a_racing_writer(self):
        pending = self.root / "pending"
        target = self.root / "target"
        pending.write_bytes(b"new")
        target.write_bytes(b"another builder won")
        with self.assertRaisesRegex(repository.RepositoryError, "Refusing"):
            repository.publish_file(pending, target, repository.digest(b"new"), force=False)
        self.assertEqual(target.read_bytes(), b"another builder won")
        repository.publish_file(pending, target, repository.digest(b"new"), force=True)
        self.assertEqual(target.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
