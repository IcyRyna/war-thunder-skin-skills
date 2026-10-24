import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location("ddsx_preview", Path(__file__).resolve().parents[1] / "tools/ddsx_preview.py")
ddsx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ddsx)


class DDSxTests(unittest.TestCase):
    def test_rectangular_chain_uses_correct_raw_axis_order(self):
        # Legacy archive API labels raw w=8,h=4 as height=8,width=4.
        meta = {"height": 8, "width": 4, "flags": 0x40000, "mips": 2, "fourcc": "DXT1", "depth": 0}
        data, _ = ddsx.top_mip(b"L" * 8 + b"T" * 16, meta)
        self.assertEqual(struct.unpack_from("<II", data, 12), (4, 8))
        self.assertEqual(data[128:], b"T" * 16)

    def test_truncated_and_paired_data_fail(self):
        meta = {"height": 8, "width": 4, "flags": 0, "mips": 1, "fourcc": "DXT1", "depth": 0}
        with self.assertRaises(ValueError):
            ddsx.top_mip(b"T" * 15, meta)
        meta["flags"] = 0x20000
        with self.assertRaisesRegex(ValueError, "paired-base"):
            ddsx.top_mip(b"T" * 16, meta)


if __name__ == "__main__":
    unittest.main()
