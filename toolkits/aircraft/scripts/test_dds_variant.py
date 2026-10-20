"""File-protection, decoding, and real pinned-texconv semantic regressions."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

import dds_variant as dds


TOOL = Path(__file__).resolve().parents[3] / "tools/texture-conversion/directxtex-may2026/texconv.exe"


class DdsVariantTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        y, x = np.mgrid[:8, :16]
        color = np.stack((x * 17, y * 31, (x + y) * 11, (x * 13 + y * 17) % 256), axis=2).astype(np.uint8)
        data = np.stack(((x * 9 + y * 7) % 256, 80 + y * 15, x * 15, (x * 11 + y * 13) % 256), axis=2).astype(np.uint8)
        zero = color.copy()
        zero[:, :, 3] = 0
        for name, pixels in (("test_c", color), ("test_n", data), ("zero_c", zero), ("zero_n", zero)):
            Image.fromarray(pixels).save(self.source / (name + ".tga"))
        text = 'name:t="user"\n' + '\n'.join('replace_tex{from:t="' + name + '*" to:t="' + name + '.tga"}'
                                             for name in ("test_c", "test_n", "zero_c", "zero_n"))
        (self.source / "vehicle.blk").write_text(text, encoding="utf-8")
        self.before = self.hashes()

    def hashes(self):
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.source.iterdir()}

    @contextmanager
    def fake_tool(self, mode):
        def run(command, timeout=180):
            destination = Path(command[command.index("-o") + 1]) / (Path(command[-1]).stem + ".dds")
            if mode == "nonzero":
                raise ValueError("texconv failed with return code 7")
            if mode == "partial":
                destination.write_bytes(b"DDS ")
            return {"command": command, "returncode": 0, "stdout": "", "stderr": ""}
        with patch.object(dds, "validate_tool", return_value={"test": True}), patch.object(dds, "_run", side_effect=run):
            yield

    def test_input_and_nested_output_rejected_without_changes(self):
        for target in (self.source, self.source / "variant", self.source.parent):
            with self.assertRaises((ValueError, FileExistsError)):
                dds.convert(self.source, target, TOOL)
        self.assertEqual(self.hashes(), self.before)

    def test_existing_zip_and_report_protected(self):
        for suffix in (".zip", ".dds.json", ".mips.zip"):
            target = self.root / ("output" + suffix)
            target.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                dds.convert(self.source, self.root / "output", TOOL)
            self.assertEqual(target.read_bytes(), b"existing")
            self.assertFalse((self.root / "output").exists())
            target.unlink()
        self.assertEqual(self.hashes(), self.before)

    def test_invalid_tool_leaves_failure_evidence_no_outputs(self):
        with self.assertRaises(ValueError):
            dds.convert(self.source, self.root / "output", self.root / "missing.exe")
        self.assertEqual(len(list((self.root / ".artifact-failures").glob("*.json"))), 1)
        self.assertFalse((self.root / "output.zip").exists())
        self.assertEqual(self.hashes(), self.before)

    def test_nonzero_tool_and_partial_output_rollback(self):
        for mode in ("nonzero", "partial", "missing"):
            with self.fake_tool(mode), self.assertRaises(ValueError):
                dds.convert(self.source, self.root / mode, TOOL)
            self.assertFalse((self.root / (mode + ".zip")).exists())
            self.assertFalse((self.root / (mode + ".dds.json")).exists())
            self.assertFalse((self.root / mode).exists())
        self.assertEqual(len(list((self.root / ".artifact-failures").glob("*.json"))), 3)
        self.assertEqual(self.hashes(), self.before)

    def test_case_insensitive_generated_collision_rejected(self):
        # README source file would become the color map's DDS target.
        (self.source / "test_c.dds").write_bytes(b"existing")
        with self.assertRaises(ValueError):
            dds.convert(self.source, self.root / "output", TOOL)

    def test_decode_rejects_truncated_and_wrong_mip_count(self):
        path = self.root / "bad.dds"
        path.write_bytes(dds._single_mip_header(2, 2, 28) + bytes(16))
        with self.assertRaisesRegex(ValueError, "complete mip chain"):
            dds.decode_mips(path)
        path.write_bytes(dds._single_mip_header(1, 1, 28) + b"\x01\x02")
        with self.assertRaisesRegex(ValueError, "Truncated"):
            dds.decode_mips(path)

    def test_source_hash_binds_decoded_bytes_during_concurrent_replacement(self):
        source = self.source / "test_c.tga"
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        original_open = Image.open
        changed = False

        def concurrent_open(value, *args, **kwargs):
            nonlocal changed
            image = original_open(value, *args, **kwargs)
            if not changed:
                changed = True
                content = bytearray(source.read_bytes())
                content[18] ^= 0xFF
                source.write_bytes(content)
            return image

        with patch.object(dds.Image, "open", side_effect=concurrent_open):
            _, textures, _, _ = dds._plan(self.source, {})
        self.assertEqual(textures[0]["input_sha256"], expected)
        self.assertNotEqual(textures[0]["input_sha256"], dds.sha256(source))

    def test_blk_change_during_planning_rejected_before_conversion(self):
        original_plan = dds._plan

        def concurrent_plan(*args, **kwargs):
            result = original_plan(*args, **kwargs)
            source = self.source / "vehicle.blk"
            source.write_bytes(source.read_bytes() + b"\n// concurrent edit\n")
            return result

        with patch.object(dds, "_plan", side_effect=concurrent_plan), self.assertRaisesRegex(ValueError, "changed"):
            dds.convert(self.source, self.root / "output", TOOL)
        self.assertFalse((self.root / "output").exists())
        self.assertFalse((self.root / "output.zip").exists())

    def test_independent_reference_uses_srgb_and_preserves_zero_alpha(self):
        pixels = np.array([[[0, 0, 0, 0], [255, 255, 255, 0]],
                           [[0, 0, 0, 0], [255, 255, 255, 0]]], dtype=np.uint8)
        color = dds.reference_mips(pixels, "color")[-1][0, 0]
        data = dds.reference_mips(pixels, "data")[-1][0, 0]
        self.assertEqual(color.tolist(), [188, 188, 188, 0])
        self.assertEqual(data.tolist(), [128, 128, 128, 0])

    def test_rectangular_one_pixel_tail_averages_both_samples(self):
        pixels = np.zeros((1, 8, 4), dtype=np.uint8)
        pixels[0, :, 0] = np.arange(8) * 32
        pixels[0, :, 1] = 170
        pixels[0, :, 2] = 51
        pixels[0, :, 3] = np.arange(8) * 16
        self.assertEqual(dds.reference_mips(pixels, "data")[-1][0, 0].tolist(), [112, 170, 51, 56])
        self.assertEqual(dds.reference_mips(pixels.transpose(1, 0, 2), "data")[-1][0, 0].tolist(),
                         [112, 170, 51, 56])

    @unittest.skipUnless(TOOL.is_file(), "Pinned May 2026 texconv is not installed")
    def test_real_rgba8_rectangular_chain_top_ga_and_hidden_rgb(self):
        result = dds.convert(self.source, self.root / "rgba8", TOOL)
        self.assertFalse(result["experimental_compression"])
        self.assertEqual(len(result["textures"]), 4)
        for texture in result["textures"]:
            self.assertTrue(texture["top_rgba_exact"])
            self.assertTrue(texture["top_ga_exact"])
            self.assertEqual([(m["width"], m["height"]) for m in texture["mips"]],
                             [(16, 8), (8, 4), (4, 2), (2, 1), (1, 1)])
            self.assertEqual(max(max(m["max_abs_vs_uncompressed_semantic_mip"]) for m in texture["mips"]), 0)
        with zipfile.ZipFile(result["mips_zip"]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(len(archive.namelist()), 20)
            for name in archive.namelist():
                with archive.open(name) as stream, Image.open(stream) as image:
                    image.load()
        self.assertEqual(self.hashes(), self.before)

    @unittest.skipUnless(TOOL.is_file(), "Pinned May 2026 texconv is not installed")
    def test_real_color_gamma_probe_and_data_numeric_mips(self):
        for name in ("test_c", "test_n", "zero_c", "zero_n"):
            pixels = np.array([[[0, 0, 0, 0], [255, 255, 255, 0]],
                               [[0, 0, 0, 0], [255, 255, 255, 0]]], dtype=np.uint8)
            Image.fromarray(pixels).save(self.source / (name + ".tga"))
        result = dds.convert(self.source, self.root / "probe", TOOL)
        for texture in result["textures"]:
            header, mips = dds.decode_mips(self.root / "probe" / texture["target"])
            expected = 188 if texture["semantic"] == "color" else 128
            self.assertEqual(mips[-1][0, 0].tolist(), [expected, expected, expected, 0])

    @unittest.skipUnless(TOOL.is_file(), "Pinned May 2026 texconv is not installed")
    def test_real_bc3_every_mip_decoded_and_marked_experimental(self):
        result = dds.convert(self.source, self.root / "bc3", TOOL, "bc3")
        self.assertTrue(result["experimental_compression"])
        self.assertEqual(self.hashes(), self.before)
        for texture in result["textures"]:
            self.assertTrue(texture["header"]["all_mips_decoded"])
            self.assertTrue(texture["baseline_top_rgba_exact"])
            self.assertEqual(texture["header"]["mip_count"], 5)
            self.assertEqual(len(texture["commands"]), 1)
            self.assertEqual(texture["mips"][-1]["width"], 1)
            if texture["source"].startswith("zero_"):
                self.assertTrue(all(m["channel_max"][3] == 0 for m in texture["mips"]))

    @unittest.skipUnless(TOOL.is_file(), "Pinned May 2026 texconv is not installed")
    def test_real_bc3_uses_precomputed_linear_light_color_mips(self):
        for name in ("test_c", "test_n", "zero_c", "zero_n"):
            pixels = np.zeros((4, 4, 4), dtype=np.uint8)
            pixels[:, 2:, :3] = 255
            pixels[:, :, 3] = 128
            Image.fromarray(pixels).save(self.source / (name + ".tga"))
        result = dds.convert(self.source, self.root / "probe_bc3", TOOL, "bc3")
        for texture in result["textures"]:
            _, mips = dds.decode_mips(self.root / "probe_bc3" / texture["target"])
            expected = 188 if texture["semantic"] == "color" else 128
            self.assertTrue(np.all(np.abs(mips[-1][0, 0, :3].astype(int) - expected) <= 4))


if __name__ == "__main__":
    unittest.main()
