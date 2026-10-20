"""Content preservation regressions using small synthetic archives."""
import hashlib
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("release_content", Path(__file__).resolve().parents[1] / "tools/verify_release_content.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ReleaseContentTests(unittest.TestCase):
    def check(self, entries):
        payload = b"original"
        package = {"id": "sample", "tag": "sample/v1.0",
                   "files": [{"path": "SKILL.md", "bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest()}]}
        with tempfile.TemporaryDirectory(prefix="wt-release-content-") as directory:
            target = Path(directory).resolve()
            self.assertTrue(target.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            archive = target / "sample.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                for name, data in entries:
                    bundle.writestr(name, data)
            return checker.verify_archive(archive, package)

    def test_original_bytes(self):
        self.assertTrue(self.check([("sample/SKILL.md", b"original")])["ok"])

    def test_changed_content(self):
        result = self.check([("sample/SKILL.md", b"modified")])
        self.assertEqual(result["changed"], ["SKILL.md"])

    def test_unexpected_file(self):
        result = self.check([("sample/SKILL.md", b"original"), ("sample/unreviewed.txt", b"extra")])
        self.assertEqual(result["extra"], ["unreviewed.txt"])

    def test_wrong_root(self):
        with self.assertRaises(ValueError):
            self.check([("other/SKILL.md", b"original")])

    def test_traversal(self):
        with self.assertRaises(ValueError):
            self.check([("sample/../SKILL.md", b"original")])

    def test_noncanonical_path(self):
        with self.assertRaises(ValueError):
            self.check([("sample//SKILL.md", b"original")])

    def test_symlink_disguised_as_matching_file(self):
        entry = zipfile.ZipInfo("sample/SKILL.md")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            self.check([(entry, b"original")])


if __name__ == "__main__":
    unittest.main()
