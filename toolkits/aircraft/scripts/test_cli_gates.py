"""CLI checks for requested decoding, strict exits, and protected outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from inspect_skins import texture_header


SCRIPT = Path(__file__).with_name("inspect_skins.py")


def truncated_texture(path: Path) -> None:
    """Use valid headers whose uncompressed top-level pixels are incomplete."""
    if path.suffix == ".tga":
        header = bytearray(18)
        header[2] = 2
        struct.pack_into("<HH", header, 12, 4, 4)
        header[16:18] = bytes((32, 0x28))
        path.write_bytes(header + bytes((3, 2, 1, 255)))
    else:
        values = [0] * 31
        values[0:7] = [124, 0x100F, 4, 4, 16, 0, 1]
        values[18:27] = [32, 0x41, 0, 32, 0xFF, 0xFF00, 0xFF0000, 0xFF000000, 0x1000]
        path.write_bytes(b"DDS " + struct.pack("<31I", *values) + bytes((1, 2, 3, 255)))


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


class InspectionCliTests(unittest.TestCase):
    def fixture(self, root: Path, suffix: str = ".tga", *, truncated: bool = False) -> Path:
        source = root / "source"
        source.mkdir()
        texture = source / f"texture{suffix}"
        if truncated:
            truncated_texture(texture)
        else:
            Image.new("RGBA", (4, 4), (10, 20, 30, 77)).save(texture)
        (source / "plane.blk").write_text(
            f'name:t="user"\nreplace_tex{{from:t="plane_c*" to:t="{texture.name}"}}\n',
            encoding="utf-8")
        return source

    def run_cli(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, arguments)],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_header_only_strict_scan_does_not_claim_pixel_decode(self):
        for suffix in (".tga", ".dds"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.fixture(root, suffix, truncated=True)
                before = tree_hashes(source)
                meta = texture_header(source / f"texture{suffix}")
                self.assertEqual((meta["width"], meta["height"]), (4, 4))
                output = root / "inspection"
                result = self.run_cli("scan", source, "--out", output, "--strict")
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
                self.assertEqual(data["summary"]["issue_levels"].get("error", 0), 0)
                self.assertNotIn("preview_attempted", data["summary"])
                self.assertFalse((output / "previews.json").exists())
                self.assertEqual(tree_hashes(source), before)

    def test_requested_truncated_preview_is_reported_and_fails_strict(self):
        for suffix in (".tga", ".dds"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.fixture(root, suffix, truncated=True)
                before = tree_hashes(source)
                output = root / "inspection"
                result = self.run_cli("scan", source, "--out", output, "--previews", 1, "--strict")
                self.assertEqual(result.returncode, 2, result.stderr)
                data = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
                self.assertEqual(data["summary"]["preview_attempted"], 1)
                self.assertEqual(data["summary"]["preview_decode_errors"], 1)
                self.assertEqual(data["summary"]["issue_levels"]["error"], 1)
                self.assertEqual(data["summary"]["issue_codes"]["preview_decode_failed"], 1)
                issue = next(item for item in data["issues"] if item["code"] == "preview_decode_failed")
                self.assertEqual(issue["file"], f"texture{suffix}")
                report = (output / "report.md").read_text(encoding="utf-8")
                self.assertIn("preview_decode_failed", report)
                self.assertIn("1 failed", report)
                previews = json.loads((output / "previews.json").read_text(encoding="utf-8"))
                self.assertTrue(previews[0]["error"])
                self.assertTrue(previews[0]["placeholder"])
                self.assertTrue((output / previews[0]["preview"]).is_file())
                self.assertEqual(tree_hashes(source), before)

    def test_non_strict_scan_keeps_preview_errors_in_machine_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.fixture(root, truncated=True)
            output = root / "inspection"
            result = self.run_cli("scan", source, "--out", output, "--previews", 1)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(data["summary"]["issue_codes"]["preview_decode_failed"], 1)
            self.assertEqual(json.loads(result.stdout)["summary"], data["summary"])

    def test_existing_scan_report_rejects_all_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.fixture(root)
            output = root / "inspection"
            output.mkdir()
            (output / "report.md").write_bytes(b"preserved report")
            before = tree_hashes(root)
            result = self.run_cli("scan", source, "--out", output, "--previews", 1)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(tree_hashes(source), {name.removeprefix("source/"): digest
                                                 for name, digest in before.items()
                                                 if name.startswith("source/")})
            self.assertEqual((output / "report.md").read_bytes(), b"preserved report")
            self.assertFalse((output / "inventory.json").exists())
            self.assertFalse((output / "contact-sheet.png").exists())

    def test_existing_derived_contact_preview_rejects_report_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.fixture(root)
            output = root / "inspection"
            (output / "previews").mkdir(parents=True)
            existing = output / "previews" / "001.png"
            existing.write_bytes(b"preserved derived preview")
            before = tree_hashes(source)
            result = self.run_cli("scan", source, "--out", output, "--previews", 1)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(existing.read_bytes(), b"preserved derived preview")
            self.assertFalse((output / "inventory.json").exists())
            self.assertFalse((output / "report.md").exists())
            self.assertEqual(tree_hashes(source), before)

    def test_preview_succeeds_once_and_protects_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.fixture(root)
            texture = source / "texture.tga"
            output = root / "channels"
            before = tree_hashes(source)
            result = self.run_cli("preview", texture, "--out", output, "--size", 128)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = {"rgb.png", "r.png", "g.png", "b.png", "a.png", "channels.png", "texture.json"}
            self.assertEqual(set(tree_hashes(output)), expected)
            output_before = tree_hashes(output)
            repeated = self.run_cli("preview", texture, "--out", output, "--size", 128)
            self.assertEqual(repeated.returncode, 1)
            self.assertEqual(tree_hashes(output), output_before)
            self.assertEqual(tree_hashes(source), before)

    def test_existing_derived_channel_prevents_partial_preview_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.fixture(root)
            output = root / "channels"
            output.mkdir()
            (output / "a.png").write_bytes(b"preserved channel")
            before = tree_hashes(source)
            result = self.run_cli("preview", source / "texture.tga", "--out", output)
            self.assertEqual(result.returncode, 1)
            self.assertEqual((output / "a.png").read_bytes(), b"preserved channel")
            self.assertFalse((output / "rgb.png").exists())
            self.assertFalse((output / "texture.json").exists())
            self.assertEqual(tree_hashes(source), before)

    def test_input_directory_is_rejected_as_preview_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.fixture(root)
            before = tree_hashes(source)
            result = self.run_cli("preview", source / "texture.tga", "--out", source)
            self.assertEqual(result.returncode, 1)
            self.assertIn("outside the source", result.stderr)
            self.assertEqual(tree_hashes(source), before)


if __name__ == "__main__":
    unittest.main()
