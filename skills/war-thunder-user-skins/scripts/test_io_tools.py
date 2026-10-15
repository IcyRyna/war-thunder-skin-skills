"""Failure-path integration regressions for public skin I/O helpers."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import build_skin
import compare_skin
import fetch_asset


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.url = 'https://example.invalid/image.bmp'
        self.headers = {'Content-Length': str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, size):
        yield self.payload


def fixture(root, *, size=(32, 16), malformed=''):
    """Make a non-flat two-map package with original alpha and normal data."""
    root.mkdir()
    width, height = size
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(width, dtype=np.uint8)
    pixels[:, :, 1:] = [90, 120, 160]
    Image.fromarray(pixels).save(root / 'color.tga')
    Image.new('RGBA', size, (18, 126, 35, 127)).save(root / 'material.tga')
    (root / 'plane.blk').write_text(
        'name:t="user"\n'
        'replace_tex{from:t="plane_c*" to:t="color.tga"' + malformed + '}\n'
        'replace_tex{from:t="plane_n*" to:t="material.tga"}\n', encoding='utf-8')
    return root


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob('*') if p.is_file()}


class BasicIoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def image_response(self):
        stream = io.BytesIO()
        Image.new('RGB', (8, 4), (30, 60, 90)).save(stream, format='BMP')
        return Response(stream.getvalue())

    def fetch(self, name='portrait.bmp'):
        return fetch_asset.fetch('https://example.invalid/image.bmp', self.root / name,
                                 page='https://example.invalid/source', credit='Fixture',
                                 license_note='Test only', limit=1024 * 1024)

    def test_fetch_rejects_existing_proxy_before_download(self):
        proxy = self.root / 'portrait.png'
        proxy.write_bytes(b'original proxy')
        with patch.object(fetch_asset.requests, 'get') as network:
            with self.assertRaises((OSError, ValueError)):
                self.fetch()
        network.assert_not_called()
        self.assertEqual(proxy.read_bytes(), b'original proxy')
        self.assertFalse((self.root / 'portrait.bmp').exists())

    def test_fetch_commits_source_proxy_and_provenance_together(self):
        with patch.object(fetch_asset.requests, 'get', return_value=self.image_response()):
            record = self.fetch()
        source = self.root / 'portrait.bmp'
        self.assertEqual(source.stat().st_size, record['bytes'])
        self.assertEqual(json.loads((self.root / 'portrait.bmp.source.json').read_text())['sha256'],
                         record['sha256'])
        with Image.open(self.root / 'portrait.png') as bitmap:
            self.assertEqual(bitmap.size, (8, 4))

    def test_failed_provenance_write_leaves_no_download_or_proxy(self):
        original = Path.write_text

        def failing_write(path, *args, **kwargs):
            if path.name.endswith('.source.json'):
                raise OSError('injected provenance write failure')
            return original(path, *args, **kwargs)

        with patch.object(fetch_asset.requests, 'get', return_value=self.image_response()):
            with patch.object(Path, 'write_text', failing_write):
                with self.assertRaises(OSError):
                    self.fetch()
        for name in ['portrait.bmp', 'portrait.png', 'portrait.bmp.source.json']:
            self.assertFalse((self.root / name).exists(), name)
        self.assertTrue(list((self.root / '.artifact-failures').glob('*.json')))

    def test_existing_provenance_prevents_network_and_preserves_bytes(self):
        provenance = self.root / 'portrait.bmp.source.json'
        provenance.write_bytes(b'earlier provenance')
        with patch.object(fetch_asset.requests, 'get') as network:
            with self.assertRaises((OSError, ValueError)):
                self.fetch()
        network.assert_not_called()
        self.assertEqual(provenance.read_bytes(), b'earlier provenance')

    def build_inputs(self, malformed=''):
        template = fixture(self.root / 'template', malformed=malformed)
        paint = self.root / 'paint.png'
        Image.new('RGB', (32, 16), (150, 160, 170)).save(paint)
        return template, {'plane_c*': paint}

    def test_build_rejects_duplicate_fields_even_with_explicit_reference(self):
        template, paint = self.build_inputs(' to:t="missing.tga"')
        before = snapshot(template)
        with self.assertRaisesRegex(ValueError, 'duplicate_field'):
            build_skin.build(template, paint, {'plane_c*': template / 'color.tga'}, self.root / 'skin')
        self.assertEqual(snapshot(template), before)
        self.assertFalse((self.root / 'skin.zip').exists())

    def test_build_reference_can_resolve_missing_texture(self):
        template, paint = self.build_inputs()
        reference = self.root / 'reference.tga'
        (template / 'color.tga').replace(reference)
        report = build_skin.build(template, paint, {'plane_c*': reference}, self.root / 'skin')
        self.assertEqual(report['static_validation_errors'], 0)
        self.assertTrue((self.root / 'skin.zip').is_file())
        self.assertFalse((template / 'color.tga').exists())

    def test_old_zip_conflict_is_rejected_before_partial_skin(self):
        template, paint = self.build_inputs()
        old = self.root / 'skin.zip'
        old.write_bytes(b'previous release')
        with self.assertRaises((OSError, ValueError)):
            build_skin.build(template, paint, {}, self.root / 'skin')
        self.assertEqual(old.read_bytes(), b'previous release')
        self.assertFalse((self.root / 'skin' / 'plane_c.tga').exists())

    def test_failed_build_record_rolls_back_every_new_artifact(self):
        template, paint = self.build_inputs()
        before = snapshot(template)
        original = build_skin.write_json

        def failing_report(path, value):
            if path.name.endswith('.build.json'):
                raise OSError('injected build report failure')
            return original(path, value)

        with patch.object(build_skin, 'write_json', failing_report):
            with self.assertRaises(OSError):
                build_skin.build(template, paint, {}, self.root / 'skin')
        self.assertEqual(snapshot(template), before)
        for path in [self.root / 'skin.zip', self.root / 'skin.build.json',
                     self.root / 'skin' / 'plane_c.tga', self.root / 'skin' / 'plane.blk']:
            self.assertFalse(path.exists(), str(path))

    def comparison_args(self):
        import argparse
        template = fixture(self.root / 'template', size=(256, 128))
        skin = fixture(self.root / 'candidate', size=(256, 128))
        return argparse.Namespace(template=template, skin=[skin], reference_albedo=None,
                                  reference_material=None, uv_mask=None, size=128,
                                  out=self.root / 'comparison')

    def test_rectangular_atlas_preserves_ratio(self):
        args = self.comparison_args()
        with redirect_stdout(io.StringIO()):
            compare_skin.run(args)
        result = json.loads((args.out / 'comparison.json').read_text())
        self.assertEqual(result['comparison_resolution'], [128, 64])
        with Image.open(args.out / 'candidate_rgb.png') as bitmap:
            self.assertEqual(bitmap.size, (128, 64))

    def test_rectangular_rounding_does_not_reject_matching_source_atlases(self):
        args = self.comparison_args()
        for folder in [args.template, *args.skin]:
            for name in ['color.tga', 'material.tga']:
                with Image.open(folder / name) as bitmap:
                    resized = bitmap.resize((257, 129))
                resized.save(folder / name)
                resized.close()
        with redirect_stdout(io.StringIO()):
            compare_skin.run(args)
        result = json.loads((args.out / 'comparison.json').read_text())
        self.assertEqual(result['comparison_resolution'], [128, 64])

    def test_comparison_cannot_replace_explicit_reference(self):
        args = self.comparison_args()
        args.out.mkdir()
        args.reference_albedo = args.out / 'comparison.png'
        args.reference_albedo.write_bytes(b'external original must survive')
        with self.assertRaises((OSError, ValueError)):
            compare_skin.run(args)
        self.assertEqual(args.reference_albedo.read_bytes(), b'external original must survive')
        self.assertFalse((args.out / 'comparison.json').exists())

    def test_comparison_cannot_replace_uv_mask(self):
        args = self.comparison_args()
        args.out.mkdir()
        args.uv_mask = args.out / 'comparison.png'
        Image.new('L', (256, 128), 255).save(args.uv_mask)
        before = args.uv_mask.read_bytes()
        with self.assertRaises((OSError, ValueError)):
            compare_skin.run(args)
        self.assertEqual(args.uv_mask.read_bytes(), before)

    def test_comparison_failure_has_no_partial_output(self):
        args = self.comparison_args()
        before = snapshot(args.template)
        with patch.object(compare_skin, 'overview', side_effect=OSError('injected image write failure')):
            with self.assertRaises(OSError):
                compare_skin.run(args)
        self.assertEqual(snapshot(args.template), before)
        self.assertFalse((args.out / 'comparison.json').exists())
        self.assertFalse((args.out / 'candidate_rgb.png').exists())


if __name__ == '__main__':
    unittest.main()
