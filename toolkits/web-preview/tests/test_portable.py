import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portable import download, unpack


class PortableTests(unittest.TestCase):
    def test_archive_paths_and_links_cannot_escape(self):
        for name, linked in [('../outside', False), ('C:/outside', False), ('..\\outside', False), ('link', True)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                folder = Path(folder)
                archive = folder / 'input.zip'
                with zipfile.ZipFile(archive, 'w') as output:
                    info = zipfile.ZipInfo(name)
                    info.filename = name  # Bypass ZipInfo's host-OS separator normalization.
                    if linked:
                        info.external_attr = (0o120777 << 16)
                    output.writestr(info, b'payload')
                with self.assertRaises(ValueError):
                    unpack(archive, folder / 'out')
                self.assertFalse((folder / 'outside').exists())

    def test_prefix_extracts_only_selected_decoder_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            archive = folder / 'input.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('repo/src/module.py', b'code')
                output.writestr('repo/.git/config', b'private')
            unpack(archive, folder / 'out', 'repo/src/')
            self.assertEqual((folder / 'out/module.py').read_bytes(), b'code')
            self.assertEqual(len(list((folder / 'out').rglob('*'))), 1)

    def test_download_rejects_corrupted_payload(self):
        with tempfile.TemporaryDirectory() as folder, patch('portable.urllib.request.urlopen', side_effect=lambda *a, **kw: io.BytesIO(b'bad')), patch('portable.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '校验失败'):
                download({'name': 'test', 'url': 'https://example.test/file', 'bytes': 3, 'sha256': '0' * 64}, Path(folder) / 'file')

    def test_plain_http_is_rejected(self):
        with self.assertRaises(ValueError):
            download({'url': 'http://example.test/file'}, Path('unused'))


if __name__ == '__main__':
    unittest.main()
