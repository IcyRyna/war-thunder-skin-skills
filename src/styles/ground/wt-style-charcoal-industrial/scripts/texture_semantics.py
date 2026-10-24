"""Texture filtering with explicit alpha meaning.

``fixed_rgb`` stores replacement colour whose alpha is independent data (often
zero). ``packed_data`` and ``scalar_data`` are linear data textures. ``opacity``
stores straight colour plus real coverage; filtering uses premultiplied linear
colour and returns straight RGBA. Never infer these meanings from pixel values.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from PIL import Image


ALPHA_SEMANTICS = frozenset({"fixed_rgb", "packed_data", "scalar_data", "opacity"})
TEXTURE_ROLES = frozenset({"color", "normal", "ao"})
ROLE_SEMANTICS = {
    "color": frozenset({"fixed_rgb", "opacity"}),
    "normal": frozenset({"packed_data"}),
    "ao": frozenset({"scalar_data"}),
}


def validate_color_space(color_space: str | None, semantics: str) -> str:
    """Resolve the documented colour/data default and reject invalid metadata."""
    validate_alpha_semantics(semantics)
    if color_space is None:
        color_space = "linear" if semantics in {"packed_data", "scalar_data"} else "srgb"
    if color_space not in {"linear", "srgb"}:
        raise ValueError(f"Unknown texture colour space: {color_space!r}")
    if semantics in {"packed_data", "scalar_data"} and color_space != "linear":
        raise ValueError("Packed/scalar texture data must use linear colour space")
    return color_space


def validate_alpha_semantics(semantics: str | None, role: str | None = None) -> str:
    if not isinstance(semantics, str) or semantics not in ALPHA_SEMANTICS:
        raise ValueError(f"Unknown alpha semantics {semantics!r}; declare one of {sorted(ALPHA_SEMANTICS)}")
    if role is not None:
        if role not in TEXTURE_ROLES:
            raise ValueError(f"Unknown texture role: {role!r}")
        if semantics not in ROLE_SEMANTICS[role]:
            raise ValueError(f"Alpha semantics {semantics!r} are incompatible with {role!r}")
    return semantics


def binding_alpha_semantics(binding: Mapping, profile: Mapping | None = None) -> dict[str, str]:
    """Merge role defaults and explicit binding declarations; validate all given values.

    Missing roles remain missing for compatible rendering of old <=8192 inputs.
    Any path needing downscaling must subsequently supply an explicit meaning.
    """
    profile = profile or {}
    defaults = profile.get("texture_alpha_semantics", {})
    local = binding.get("alpha_semantics", {})
    if not isinstance(defaults, Mapping) or not isinstance(local, Mapping):
        raise ValueError("texture_alpha_semantics and binding alpha_semantics must be role mappings")
    result = dict(defaults)
    result.update(local)
    return {role: validate_alpha_semantics(semantics, role) for role, semantics in result.items()}


def _dimensions(size: tuple[int, int]) -> tuple[int, int]:
    if len(size) != 2 or any(type(value) is not int or value < 1 for value in size):
        raise ValueError("Output dimensions must be positive integers")
    return size


def _float_resize(values: np.ndarray, size: tuple[int, int], resample: Image.Resampling) -> np.ndarray:
    return np.asarray(Image.fromarray(values.astype(np.float32, copy=False)).resize(size, resample), dtype=np.float32)


def _to_linear(values: np.ndarray) -> np.ndarray:
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def _to_srgb(values: np.ndarray) -> np.ndarray:
    # Keep temporary arrays bounded on native 16k atlases. A single np.where
    # over the whole atlas otherwise retains several gigabyte-sized buffers.
    output = np.empty_like(values)
    flat, destination = values.reshape(-1), output.reshape(-1)
    for start in range(0, flat.size, 1024 * 1024):
        block = np.maximum(flat[start:start + 1024 * 1024], 0)
        destination[start:start + block.size] = np.where(
            block <= 0.0031308, block * 12.92, 1.055 * block ** (1 / 2.4) - 0.055)
    return output


_SRGB_TO_LINEAR = _to_linear(np.arange(256, dtype=np.float32) / 255.0)


def _byte_band(values: np.ndarray) -> Image.Image:
    output = np.empty(values.shape, dtype=np.uint8)
    flat, destination = values.reshape(-1), output.reshape(-1)
    for start in range(0, flat.size, 1024 * 1024):
        block = flat[start:start + 1024 * 1024]
        destination[start:start + block.size] = np.rint(np.clip(block, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(output)


def resize_texture(
    image: Image.Image,
    size: tuple[int, int],
    semantics: str,
    color_space: str | None = None,
    resample: Image.Resampling = Image.Resampling.BILINEAR,
) -> Image.Image:
    """Filter a texture without confusing independent data with coverage.

    Data channels are filtered independently. sRGB colour is filtered in linear
    light; only real opacity is multiplied into colour before filtering. Alpha
    remains independent for fixed replacement colour, even if every value is 0.
    """
    validate_alpha_semantics(semantics)
    _dimensions(size)
    color_space = validate_color_space(color_space, semantics)
    rgba = image if image.mode == 'RGBA' else image.convert("RGBA")
    if rgba.size == size:
        return rgba.copy()
    if semantics in {"packed_data", "scalar_data"} or (semantics == "fixed_rgb" and color_space == "linear"):
        return Image.merge("RGBA", tuple(rgba.getchannel(band).resize(size, resample) for band in 'RGBA'))

    if semantics == 'opacity':
        alpha = np.asarray(rgba.getchannel('A'), dtype=np.float32) / 255.0
        resized_alpha = np.clip(_float_resize(alpha, size, resample), 0, 1)
        alpha_output = _byte_band(resized_alpha)
    else:
        alpha_output = rgba.getchannel('A').resize(size, resample)
    output_bands = []
    for band in 'RGB':
        encoded = np.asarray(rgba.getchannel(band))
        if color_space == "srgb":
            values = _SRGB_TO_LINEAR[encoded]
        else:
            values = encoded.astype(np.float32) / 255.0
        if semantics == "opacity":
            values *= alpha
        filtered = _float_resize(values, size, resample)
        if semantics == "opacity":
            # Fully transparent samples have no visible colour contribution.
            filtered = np.divide(filtered, resized_alpha, out=np.zeros_like(filtered), where=resized_alpha > 1e-8)
        if color_space == "srgb":
            filtered = _to_srgb(filtered)
        output_bands.append(_byte_band(filtered))
    output_bands.append(alpha_output)
    return Image.merge("RGBA", output_bands)


def resize_for_preview(
    image: Image.Image,
    semantics: str | None,
    max_size: int = 8192,
    *,
    color_space: str | None = None,
) -> Image.Image:
    """Keep native <=8192 inputs; require explicit semantics above the limit."""
    if type(max_size) is not int or max_size < 1:
        raise ValueError("Preview maximum size must be a positive integer")
    if max(image.size) <= max_size:
        if semantics is not None:
            validate_alpha_semantics(semantics)
            validate_color_space(color_space, semantics)
        elif color_space is not None:
            raise ValueError("A colour space declaration requires explicit alpha semantics")
        return image.convert("RGBA")
    validate_alpha_semantics(semantics)
    scale = max_size / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return resize_texture(image, size, semantics, color_space=color_space)


def iter_mipmaps(image: Image.Image, semantics: str, color_space: str | None = None):
    """Yield a complete semantic mip chain, including the unmodified top level.

    Packed normals are material channels rather than an RGB vector: no normal
    renormalization or colour transform is applied to them. Odd dimensions use
    the DDS floor-halving convention and every chain ends at 1 x 1.
    """
    validate_alpha_semantics(semantics)
    color_space = validate_color_space(color_space, semantics)
    current = image.convert("RGBA")
    yield current
    while current.size != (1, 1):
        size = (max(1, current.width // 2), max(1, current.height // 2))
        current = resize_texture(current, size, semantics, color_space, Image.Resampling.BOX)
        yield current
