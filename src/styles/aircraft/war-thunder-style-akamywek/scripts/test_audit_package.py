"""Behavioral checks for final ZIP contents, installed bytes and cross-resolution material masks."""
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image

from coat_material import protection_mask
from inspect_skins import texture_header
from legacy_dds import header
from verify_game_zip import verify


class PackageTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.folder = self.root / "UserSkins" / "Copper"
        self.folder.mkdir(parents=True)
        self.dds = self.folder / "c.dds"
        self.dds.write_bytes(header(8, 4) + bytes(range(128)))
        (self.folder / "jet.blk").write_text('name:t="user"\nreplace_tex{from:t="jet_c*" to:t="c.dds"}', encoding="utf8")

    def pack(self, skip=None, extra=False):
        p = self.root / "skin.zip"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.folder.iterdir():
                if f.name != skip:
                    z.write(f, "Copper/" + f.name)
            if extra:
                z.writestr("Copper/credits.txt", "not game data")
        return p

    def test_exact_install_and_mismatch(self):
        package = self.pack()
        receipt = verify(package, self.folder.parent)
        self.assertEqual(len(receipt["files"]), 2)
        row = receipt["files"]["c.dds"]
        self.assertEqual(row["zip_sha256"], row["installed_sha256"])
        data = bytearray(self.dds.read_bytes()); data[-1] ^= 1; self.dds.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "differs"):
            verify(package, self.folder.parent)

    def test_missing_member_even_when_installed_exists(self):
        with self.assertRaisesRegex(ValueError, "missing_texture"):
            verify(self.pack(skip="c.dds"), self.folder.parent)

    def test_source_artifact_is_not_game_content(self):
        with self.assertRaisesRegex(ValueError, "Unexpected game ZIP member"):
            verify(self.pack(extra=True))

    def test_truncated_uncompressed_formats(self):
        # 1 byte missing in each; a valid-looking header is insufficient.
        self.dds.write_bytes(self.dds.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "Truncated DDS"):
            verify(self.pack())
        raw = self.root / "data.tga"
        Image.new("RGBA", (5, 4)).save(raw)
        raw.write_bytes(raw.read_bytes()[:18 + 5*4*4-1])
        with self.assertRaisesRegex(ValueError, "TGA pixel payload"):
            texture_header(raw)

    def test_dds_padded_rows_and_tail_mip(self):
        words = list(struct.unpack("<31I", header(8, 4)[4:]))
        words[4], words[6] = 40, 2
        data = b"DDS " + struct.pack("<31I", *words) + bytes(40*4 + 4*2*4)
        self.dds.write_bytes(data)
        self.assertEqual(texture_header(self.dds)["mip_count"], 2)
        self.dds.write_bytes(data[:-1])
        with self.assertRaisesRegex(ValueError, "Truncated DDS"):
            texture_header(self.dds)

    def test_fine_material_protection_survives_downsampling(self):
        mask = np.zeros((8, 8), np.uint8)
        mask[0, 0], mask[6, 7] = 1, 255
        path = self.root / "mechanical.png"
        Image.fromarray(mask).save(path)
        result, mode = protection_mask(path, (4, 4))
        self.assertEqual(mode, "any-covered-down")
        self.assertEqual(np.argwhere(result).tolist(), [[0, 0], [3, 3]])
        with self.assertRaisesRegex(ValueError, "aspect"):
            protection_mask(path, (4, 2))


if __name__ == "__main__":
    unittest.main()
