"""Regressions for preview's >8192 branch and independent ground texture data."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from texture_semantics import binding_alpha_semantics, iter_mipmaps, resize_for_preview, resize_texture


class PreviewResizeTests(unittest.TestCase):
    def test_8192_boundary_keeps_legacy_unknown_but_8193_requires_declaration(self):
        at_limit = Image.new("RGBA", (8192, 1), (90, 150, 200, 0))
        self.assertEqual(resize_for_preview(at_limit, None).tobytes(), at_limit.tobytes())
        over_limit = Image.new("RGBA", (8193, 1), (90, 150, 200, 0))
        with self.assertRaisesRegex(ValueError, "Unknown alpha semantics"):
            resize_for_preview(over_limit, None)
        with self.assertRaisesRegex(ValueError, "Unknown alpha semantics"):
            resize_for_preview(over_limit, "probably opacity")

    def test_fixed_replacement_preserves_nonzero_rgb_under_zero_alpha_above_8192(self):
        source = Image.new("RGBA", (8193, 3), (247, 226, 55, 0))
        result = resize_for_preview(source, "fixed_rgb")
        self.assertEqual(result.size, (8192, 3))
        self.assertEqual(result.getextrema(), ((247, 247), (226, 226), (55, 55), (0, 0)))

    def test_packed_normal_components_filter_independently_above_8192(self):
        data = np.zeros((2, 8193, 4), dtype=np.uint8)
        data[:, :, 0] = np.arange(8193, dtype=np.uint16) % 256
        data[:, :, 1] = 128
        data[:, :, 2] = np.arange(8193, dtype=np.uint16)[::-1] % 256
        data[:, 1::2, 3] = 255
        source = Image.fromarray(data)
        result = resize_for_preview(source, "packed_data")
        expected = Image.merge("RGBA", tuple(band.resize(result.size, Image.Resampling.BILINEAR) for band in source.split()))
        self.assertEqual(result.tobytes(), expected.tobytes())
        self.assertGreater(result.getextrema()[0][1], 200)
        self.assertEqual(result.getextrema()[1], (128, 128))

    def test_scalar_ao_has_no_alpha_multiplication(self):
        source = Image.new("RGBA", (8193, 1), (200, 40, 80, 0))
        result = resize_for_preview(source, "scalar_data")
        self.assertEqual(result.getpixel((0, 0)), (200, 40, 80, 0))

    def test_opacity_above_8192_excludes_transparent_colour_bleeding(self):
        data = np.zeros((1, 8193, 4), dtype=np.uint8)
        data[:, :4096] = (255, 0, 0, 255)
        data[:, 4096:] = (0, 0, 255, 0)
        result = np.asarray(resize_for_preview(Image.fromarray(data), "opacity"))
        covered = result[:, :, 3] > 0
        self.assertTrue(np.any((result[:, :, 3] > 0) & (result[:, :, 3] < 255)))
        self.assertTrue(np.all(result[:, :, 0][covered] == 255))
        self.assertTrue(np.all(result[:, :, 2][covered] == 0))


class TextureFilteringTests(unittest.TestCase):
    def test_opacity_premultiplies_before_filtering_and_returns_straight_colour(self):
        source = Image.fromarray(np.array([[(255, 0, 0, 255), (0, 0, 255, 0)]], dtype=np.uint8))
        self.assertEqual(resize_texture(source, (1, 1), "opacity").getpixel((0, 0)), (255, 0, 0, 128))

    def test_srgb_colour_filters_in_linear_light_even_when_alpha_is_zero(self):
        source = Image.fromarray(np.array([[(0, 0, 0, 0), (255, 255, 255, 0)]], dtype=np.uint8))
        self.assertEqual(resize_texture(source, (1, 1), "fixed_rgb").getpixel((0, 0)), (188, 188, 188, 0))
        self.assertEqual(resize_texture(source, (1, 1), "fixed_rgb", "linear").getpixel((0, 0)), (128, 128, 128, 0))

    def test_fully_transparent_opacity_is_finite_and_zero(self):
        source = Image.new("RGBA", (4, 3), (255, 20, 30, 0))
        self.assertEqual(resize_texture(source, (1, 1), "opacity").getpixel((0, 0)), (0, 0, 0, 0))

    def test_invalid_data_color_space_and_dimensions_rejected(self):
        source = Image.new("RGBA", (2, 2))
        with self.assertRaisesRegex(ValueError, "must use linear"):
            resize_texture(source, (1, 1), "packed_data", "srgb")
        for size in ((0, 1), (1, -1), (True, 1), (1.0, 1)):
            with self.assertRaises(ValueError):
                resize_texture(source, size, "fixed_rgb")

    def test_profile_defaults_and_binding_override_are_validated(self):
        profile = {"texture_alpha_semantics": {"color": "fixed_rgb", "normal": "packed_data", "ao": "scalar_data"}}
        result = binding_alpha_semantics({"alpha_semantics": {"color": "opacity"}}, profile)
        self.assertEqual(result, {"color": "opacity", "normal": "packed_data", "ao": "scalar_data"})
        with self.assertRaisesRegex(ValueError, "incompatible"):
            binding_alpha_semantics({"alpha_semantics": {"normal": "opacity"}}, profile)
        self.assertEqual(binding_alpha_semantics({}), {})

    def test_native_inputs_still_validate_explicit_color_space(self):
        source = Image.new('RGBA', (2, 2))
        with self.assertRaisesRegex(ValueError, 'must use linear'):
            resize_for_preview(source, 'packed_data', color_space='srgb')
        with self.assertRaisesRegex(ValueError, 'requires explicit'):
            resize_for_preview(source, None, color_space='linear')

    def test_complete_rectangular_mips_preserve_independent_channels(self):
        source = Image.new('RGBA', (7, 3), (18, 128, 230, 0))
        levels = list(iter_mipmaps(source, 'packed_data'))
        self.assertEqual([level.size for level in levels], [(7, 3), (3, 1), (1, 1)])
        for level in levels:
            self.assertEqual(level.getpixel((0, 0)), (18, 128, 230, 0))
        self.assertEqual(levels[0].tobytes(), source.tobytes())

    def test_opacity_linear_color_is_premultiplied_independently_of_srgb(self):
        source = Image.fromarray(np.array([[(0, 255, 0, 255), (255, 0, 255, 0)]], dtype=np.uint8))
        self.assertEqual(resize_texture(source, (1, 1), 'opacity', 'linear').getpixel((0, 0)), (0, 255, 0, 128))


if __name__ == "__main__":
    unittest.main()
