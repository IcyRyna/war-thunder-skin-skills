"""Ground DDS semantics, BLK boundaries and real pinned-texconv CLI coverage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ground_dds
from dds_variant import TEXCONV_SHA256, decode_mips, mip_sizes


class SemanticMipsTests(unittest.TestCase):
    def test_opacity_filters_coverage_and_fixed_rgb_keeps_hidden_color(self):
        image = Image.fromarray(np.array([[[255, 0, 0, 0], [0, 0, 255, 255]]], dtype=np.uint8))
        opaque = ground_dds.semantic_mips(image, "opacity", "srgb")[-1][0, 0]
        fixed = ground_dds.semantic_mips(image, "fixed_rgb", "srgb")[-1][0, 0]
        np.testing.assert_array_equal(opaque, [0, 0, 255, 128])
        np.testing.assert_array_equal(fixed, [188, 0, 188, 128])

    def test_normal_and_ao_data_are_linear_and_preserve_independent_alpha(self):
        image = Image.fromarray(np.array([[[0, 0, 0, 255], [255, 255, 255, 0]]], dtype=np.uint8))
        for semantics in ("packed_data", "scalar_data"):
            with self.subTest(semantics=semantics):
                mip = ground_dds.semantic_mips(image, semantics, "linear")[-1][0, 0]
                np.testing.assert_array_equal(mip, [128, 128, 128, 128])

    def test_zero_alpha_fixed_color_survives_all_rectangular_mips(self):
        image = Image.new("RGBA", (9, 3), (213, 147, 25, 0))
        mips = ground_dds.semantic_mips(image, "fixed_rgb", "srgb")
        self.assertEqual([(p.shape[1], p.shape[0]) for p in mips], [(9, 3), (4, 1), (2, 1), (1, 1)])
        for pixels in mips:
            np.testing.assert_array_equal(pixels[0, 0], [213, 147, 25, 0])

    def test_16k_dimensions_supported_and_out_of_bound_rejected(self):
        self.assertEqual(mip_sizes(16384, 1)[-1], (1, 1))
        self.assertEqual(len(mip_sizes(16384, 16384)), 15)
        narrow = ground_dds.semantic_mips(Image.new("RGBA", (16384, 1), (17, 93, 204, 0)),
                                         "fixed_rgb", "srgb")
        self.assertEqual(len(narrow), 15)
        np.testing.assert_array_equal(narrow[-1][0, 0], [17, 93, 204, 0])
        with self.assertRaises(ValueError):
            mip_sizes(16385, 1)

    def test_decoder_hash_binds_exact_bytes_to_manifest(self):
        with tempfile.TemporaryDirectory(prefix="ground-dds-bytes-") as temporary:
            path = Path(temporary) / "source.tga"
            Image.new("RGBA", (2, 2), (255, 127, 0, 0)).save(path)
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                ground_dds._load_texture(path, "0" * 64)

    def test_small_texture_read_reserves_actual_file_size_instead_of_16k_cap(self):
        with tempfile.TemporaryDirectory(prefix='ground-dds-read-bound-') as temporary:
            path = Path(temporary) / 'small.tga'
            Image.new('RGBA', (2, 2), (213, 145, 28, 0)).save(path)
            encoded_size = path.stat().st_size
            reads = []
            original_open = Path.open

            class RecordingReader:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    self.stream.__enter__()
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def read(self, size=-1):
                    reads.append(size)
                    return self.stream.read(size)

            def monitored_open(opened_path, *args, **kwargs):
                stream = original_open(opened_path, *args, **kwargs)
                return RecordingReader(stream) if opened_path == path else stream

            with mock.patch.object(Path, 'open', new=monitored_open):
                decoded = ground_dds._load_texture(path)
            self.assertEqual(decoded.getpixel((0, 0)), (213, 145, 28, 0))
            self.assertEqual(reads, [encoded_size + 1])
            self.assertLess(reads[0], 1024)


class BlkTests(unittest.TestCase):
    def setUp(self):
        self.textures = {"body_c.tga": {"file": Path("body_c.tga"), "output": Path("body_c.dds"), "role": "color"}}

    def test_rewrites_exact_mappings_preserves_resource_and_parameter(self):
        text = '// original\nname:t="user"\nset_tex { from:t="tank_body_c*" to:t="body_c.tga" param:t="camo_skin_tex" }'
        rewritten, mappings = ground_dds.rewrite_blk(text, self.textures)
        self.assertIn('from:t="tank_body_c*"', rewritten)
        self.assertIn('to:t="body_c.dds"', rewritten)
        self.assertIn('param:t="camo_skin_tex"', rewritten)
        self.assertEqual(mappings[0]["role"], "color")

    def test_malformed_unknown_unmapped_and_traversal_are_rejected(self):
        failures = [
            'replace_tex { from:t="tank*" to:t="../body_c.tga" }',
            'replace_tex { from:t="tank*" to:t="missing.tga" }',
            'replace_tex { from:t="tank*" to:t="body_c.tga" extra:t="x" }',
            'replace_tex { from:t="tank*" to:t="body_c.tga"',
            'unknown { from:t="tank*" to:t="body_c.tga" }',
            'set_tex { from:t="tank*" to:t="body_c.tga" }',
        ]
        for text in failures:
            with self.subTest(text=text), self.assertRaises(ValueError):
                ground_dds.rewrite_blk(text, self.textures)


class RealTexconvCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("WT_TEXCONV")
        cls.texconv = Path(configured) if configured else None
        if cls.texconv is None or not cls.texconv.is_file():
            raise unittest.SkipTest("Set WT_TEXCONV to the pinned May 2026 texconv executable for the real CLI test")

    def _fixture(self, root: Path):
        source = root / "input"
        source.mkdir()
        textures, blocks = [], ['name:t="user"']
        for role, count in ground_dds.DEFAULT_COUNTS.items():
            for index in range(count):
                name = f"{role}_{index}.tga"
                semantics = "fixed_rgb" if role == "color" else "packed_data" if role == "normal" else "scalar_data"
                space = "srgb" if role == "color" else "linear"
                array = np.empty((3, 5, 4), np.uint8)
                for y in range(3):
                    for x in range(5):
                        array[y, x] = [x * 50, y * 100, (x + y) * 30, 0 if role == "color" else (x * 20 + y * 40)]
                if role == "color" and index == 1:
                    semantics = "opacity"
                    array[:, :2] = [255, 0, 0, 0]
                    array[:, 2:] = [0, 0, 255, 255]
                Image.fromarray(array).save(source / name)
                textures.append({"file": name, "role": role, "alpha_semantics": semantics, "color_space": space})
                blocks.append(f'replace_tex {{ from:t="tank_{role}_{index}*" to:t="{name}" }}')
        (source / "tank.blk").write_text("\n".join(blocks), encoding="utf-8")
        manifest, profile, config = (root / name for name in ("manifest.json", "profile.json", "tool-config.json"))
        manifest.write_text(json.dumps({"blk": "tank.blk", "textures": textures}), encoding="utf-8")
        profile.write_text(json.dumps({"id": "tiny-complete-ground", "texture_counts": ground_dds.DEFAULT_COUNTS}), encoding="utf-8")
        config.write_text(json.dumps({"texconv": {"path": str(self.texconv), "sha256": TEXCONV_SHA256}}), encoding="utf-8")
        return source, manifest, profile, config

    def test_cli_complete_rgba8_and_bc3_with_every_mip_decoded(self):
        with tempfile.TemporaryDirectory(prefix="ground-dds-test-") as temporary:
            root = Path(temporary)
            source, manifest, profile, config = self._fixture(root)
            originals = ground_dds._input_hashes(source)
            for output_format in ("rgba8", "bc3"):
                output = root / output_format
                command = [sys.executable, "-B", str(SCRIPTS / "ground_dds.py"), "--input", str(source),
                           "--manifest", str(manifest), "--profile", str(profile), "--config", str(config),
                           "--out", str(output)]
                if output_format != "rgba8":
                    command.extend(["--format", output_format])
                process = subprocess.run(command, capture_output=True, text=True, timeout=120)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                report = json.loads((output / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["texture_counts"], {"color": 4, "normal": 4, "ao": 3})
                self.assertEqual(len(list((output / "skin").glob("*.dds"))), 11)
                self.assertEqual(report["format"], output_format)
                self.assertEqual(report["tool"]["sha256"], TEXCONV_SHA256)
                self.assertEqual(report["input_file_hashes"], originals)
                for texture in report["textures"]:
                    header, decoded = decode_mips(output / "skin" / texture["target"])
                    self.assertEqual(header["mip_count"], 3)
                    self.assertEqual(decoded[-1].shape, (1, 1, 4))
                    self.assertEqual(texture["mips"][-1]["width"], 1)
                    self.assertEqual(texture["mips"][-1]["height"], 1)
                    if output_format == "rgba8":
                        self.assertTrue(texture["top_rgba_exact"])
                        self.assertTrue(all(m["max_abs_vs_semantic_mip"] == [0, 0, 0, 0] for m in texture["mips"]))
                with zipfile.ZipFile(output / "package.zip") as archive:
                    self.assertEqual(len(archive.namelist()), 12)
                    self.assertIn("skin/tank.blk", archive.namelist())
                with zipfile.ZipFile(output / "mips.zip") as archive:
                    self.assertEqual(len(archive.namelist()), 33)
                # A rerun must preserve the delivered bytes and report failure.
                rerun = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(rerun.returncode, 0)
                self.assertIn("fresh directory", rerun.stderr)
            self.assertEqual(ground_dds._input_hashes(source), originals)

    def test_wrong_tool_pin_and_missing_ao_leave_no_output(self):
        with tempfile.TemporaryDirectory(prefix="ground-dds-reject-") as temporary:
            root = Path(temporary)
            source, manifest, profile, config = self._fixture(root)
            tool_config = json.loads(config.read_text())
            tool_config["texconv"]["sha256"] = "0" * 64
            config.write_text(json.dumps(tool_config))
            with self.assertRaisesRegex(ValueError, "pinned"):
                ground_dds.convert(source, manifest, profile, config, root / "bad-pin")
            self.assertFalse((root / "bad-pin").exists())
            data = json.loads(manifest.read_text())
            data["textures"] = data["textures"][:-1]
            manifest.write_text(json.dumps(data))
            tool_config["texconv"]["sha256"] = TEXCONV_SHA256
            config.write_text(json.dumps(tool_config))
            with self.assertRaisesRegex(ValueError, "Incomplete texture set"):
                ground_dds.convert(source, manifest, profile, config, root / "missing-ao")
            self.assertFalse((root / "missing-ao").exists())


if __name__ == "__main__":
    unittest.main()
