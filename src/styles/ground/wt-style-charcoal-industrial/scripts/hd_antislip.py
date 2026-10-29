"""Native antislip material generated from one height field and explicit parameters."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from skill_contract import identity, number, policy, read_json, require_text, rgb, sha

PRESETS = {"square": (2048, 2048, 15051), "rectangle": (4096, 2048, 15052), "strip": (4096, 512, 15053)}


def resolve_parameters(grain_px=None, slope=None, *, color=None, inverse_roughness=None,
                       metallic=None, color_noise=None, roughness_noise=None,
                       grain_mm=None, texels_per_meter=None, required_mip=None,
                       tint_reason=None):
    defaults = policy()["materials"]["antislip"]
    values = {k: defaults[k] for k in (
        "color_srgb", "color_noise_sigma", "grain_sigma_px", "rms_height_slope",
        "inverse_roughness_center", "roughness_noise_sigma", "metallic", "required_grain_mip")}
    for name, value in [("color_srgb", color), ("grain_sigma_px", grain_px),
                        ("rms_height_slope", slope), ("inverse_roughness_center", inverse_roughness),
                        ("metallic", metallic), ("color_noise_sigma", color_noise),
                        ("roughness_noise_sigma", roughness_noise), ("required_grain_mip", required_mip)]:
        if value is not None:
            values[name] = value
    if (grain_mm is None) != (texels_per_meter is None):
        raise ValueError("Physical grain requires both grain-mm and texels-per-meter")
    if grain_mm is not None:
        if grain_px is not None:
            raise ValueError("Choose pixel sigma or physical diameter, not both")
        number(grain_mm, "grain diameter mm", .001, 1000)
        number(texels_per_meter, "texels per meter", .001, 1e7)
        values["grain_sigma_px"] = grain_mm * texels_per_meter / 2000
    values["color_srgb"] = rgb(values["color_srgb"])
    if max(values["color_srgb"]) != min(values["color_srgb"]):
        require_text(tint_reason, "intentional tint reason")
    values["tint_reason"] = tint_reason
    number(values["grain_sigma_px"], "grain sigma", .25, 64)
    number(values["rms_height_slope"], "RMS slope", .01, .5)
    for name in ("inverse_roughness_center", "metallic"):
        values[name] = number(values[name], name, 0, 255, True)
    for name in ("color_noise_sigma", "roughness_noise_sigma"):
        number(values[name], name, 0, 32)
    values["required_grain_mip"] = number(values["required_grain_mip"], "required grain mip", 0, 6, True)
    diameter = 2 * values["grain_sigma_px"] / 2**values["required_grain_mip"]
    if diameter < defaults["minimum_diameter_px"]:
        raise ValueError("Grain has fewer than two pixels at the required mip; choose physical size/resolution")
    values["physical_scale"] = {"diameter_mm": grain_mm, "texels_per_meter": texels_per_meter,
                                "definition": "characteristic diameter = 2 gaussian sigma"}
    return values


def make_patch(out, width, height, seed, grain_px=None, slope=None, **parameters):
    out = Path(out)
    width = number(width, "width", 32, 8192, True)
    height = number(height, "height", 32, 8192, True)
    seed = number(seed, "seed", 0, 2**63-1, True)
    if width * height > 33554432:
        raise ValueError("At most 32 megapixels per patch")
    if out.exists():
        raise FileExistsError("Use a new output directory")
    recipe = resolve_parameters(grain_px, slope, **parameters)
    if min(width, height) // 2**recipe["required_grain_mip"] < 4:
        raise ValueError("Required mip is too small to represent the patch")
    inset, radius = max(4, round(min(width, height)/64)), max(3, round(min(width, height)/40))
    yy, xx = np.ogrid[:height, :width]
    qx = np.abs(xx+.5-width/2)-(width/2-inset-radius)
    qy = np.abs(yy+.5-height/2)-(height/2-inset-radius)
    distance = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)-radius
    coverage = np.rint(np.clip(.5-distance, 0, 1)*255).astype("uint8")
    core = coverage == 255
    rng = np.random.default_rng(seed)
    grain = recipe["grain_sigma_px"]
    field = gaussian_filter(rng.standard_normal((height, width), dtype=np.float32), grain, mode="reflect")
    field -= gaussian_filter(field, max(2., grain*5), mode="reflect")
    deviation = float(field[core].std())
    if deviation < 1e-8:
        raise ValueError("Grain scale has no measurable detail at this patch size")
    field /= deviation
    dy, dx = np.gradient(field)
    factor = recipe["rms_height_slope"] / np.sqrt(np.mean(dx[core]**2+dy[core]**2))
    nx, ny = -dx*factor, dy*factor
    nz = 1/np.sqrt(1+nx*nx+ny*ny)
    normal = np.stack((nx*nz, ny*nz, nz), axis=-1)
    normal_rgb = np.rint(np.clip(normal*127.5+127.5, 0, 255)).astype("uint8")
    normal_rgb[coverage == 0] = [128, 128, 255]
    color = np.empty((height, width, 4), dtype="uint8")
    color[..., :3] = np.rint(np.clip(np.array(recipe["color_srgb"])+field[..., None]*recipe["color_noise_sigma"], 0, 255)).astype("uint8")
    color[..., 3] = coverage
    color[coverage == 0, :3] = 0
    packed = np.empty((height, width, 4), dtype="uint8")
    packed[..., 0] = np.rint(np.clip(recipe["inverse_roughness_center"]+field*recipe["roughness_noise_sigma"], 0, 255)).astype("uint8")
    packed[..., 1], packed[..., 2], packed[..., 3] = normal_rgb[..., 0], recipe["metallic"], normal_rgb[..., 1]
    packed[coverage == 0] = [recipe["inverse_roughness_center"], 128, recipe["metallic"], 128]
    out.mkdir(parents=True)
    outputs = {"color.png": color, "coverage.png": coverage, "normal-rgb.png": normal_rgb, "packed-n.png": packed}
    files = []
    for name, array in outputs.items():
        path = out/name
        Image.fromarray(array).save(path, compress_level=6)
        with Image.open(path) as image:
            if not np.array_equal(np.asarray(image), array):
                raise RuntimeError("PNG round trip failed: " + name)
        files.append({"file": name, "bytes": path.stat().st_size, "sha256": sha(path)})
    meta = {"schema_version": 2, "recipe": "charcoal-antislip-parameterized",
            "skill_version": identity()["version"], "seed": seed, "size": [width, height],
            "parameters": recipe, "color_srgb": recipe["color_srgb"],
            "grain_sigma_px": grain, "rms_height_slope": recipe["rms_height_slope"],
            "packed_n": policy()["materials"]["packed_n_semantics"],
            "normal_convention": "tangent +Y up; image-row gradient is +normal Y",
            "boundary": {"inset_px": inset, "corner_radius_px": radius, "raised_plate_edge": False},
            "alpha": "C straight coverage; N.A normal Y data, never coverage",
            "files": files, "visual_approval": "pending; candidate sample only"}
    (out/"recipe.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return meta


def verify_patch(folder):
    folder = Path(folder)
    meta = read_json(folder/"recipe.json")
    if meta.get("schema_version") != 2:
        raise ValueError("Legacy antislip recipe: preserve as historical evidence or regenerate explicitly")
    params = meta["parameters"]
    resolved = resolve_parameters(params["grain_sigma_px"], params["rms_height_slope"],
        color=params["color_srgb"], inverse_roughness=params["inverse_roughness_center"],
        metallic=params["metallic"], color_noise=params["color_noise_sigma"],
        roughness_noise=params["roughness_noise_sigma"], required_mip=params["required_grain_mip"],
        tint_reason=params.get("tint_reason"))
    expected = {"color.png": "RGBA", "coverage.png": "L", "normal-rgb.png": "RGB", "packed-n.png": "RGBA"}
    if {r["file"] for r in meta["files"]} != set(expected) or len(meta["files"]) != 4:
        raise ValueError("Exact four material maps required")
    arrays = {}
    for row in meta["files"]:
        path = folder/row["file"]
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("Material map hash changed")
        with Image.open(path) as image:
            if image.mode != expected[row["file"]] or list(image.size) != meta["size"]:
                raise ValueError("Material mode/dimensions mismatch")
            arrays[row["file"]] = np.array(image)
    c, mask, n, packed = [arrays[k] for k in ("color.png", "coverage.png", "normal-rgb.png", "packed-n.png")]
    solid, clear = mask == 255, mask == 0
    if not solid.any() or not clear.any():
        raise ValueError("Material needs opaque interior and transparent exterior")
    vectors = n[solid].astype("float32")/127.5-1
    error = float(np.max(np.abs(np.linalg.norm(vectors, axis=-1)-1)))
    checks = {
        "coverage_alpha": np.array_equal(c[..., 3], mask),
        "transparent_rgb_zero": np.all(c[clear, :3] == 0),
        "outside_flat_normal": np.all(n[clear] == [128,128,255]),
        "data_alpha_not_coverage": not np.array_equal(packed[..., 3], mask),
        "packed_x_matches": np.array_equal(n[..., 0], packed[..., 1]),
        "packed_y_matches": np.array_equal(n[..., 1], packed[..., 3]),
        "metallic_matches_parameters": np.all(packed[..., 2] == resolved["metallic"]),
        "roughness_matches_parameters": abs(float(np.median(packed[solid,0]))-resolved["inverse_roughness_center"]) <= 1,
        "color_matches_parameters": np.max(np.abs(np.median(c[solid, :3], axis=0)-resolved["color_srgb"])) <= 1,
        "unit_normals": error < .012,
    }
    if not params.get("tint_reason"):
        checks["neutral_color"] = np.all(c[solid, 0] == c[solid, 1]) and np.all(c[solid, 1] == c[solid, 2])
    if not all(checks.values()):
        raise ValueError("Material validation failed: " + str(checks))
    # Diagnostic mip decay is expected. Only the explicitly required mip has a sampling gate.
    mip_metrics = []
    working = c[..., 1].astype("float32")
    for level in range(4):
        mip_metrics.append({"level": level, "diameter_px": 2*params["grain_sigma_px"]/2**level,
                            "sampled_std": float(working[working.shape[0]//4:3*working.shape[0]//4,
                                                         working.shape[1]//4:3*working.shape[1]//4].std())})
        working = np.asarray(Image.fromarray(working).resize((max(1,working.shape[1]//2),max(1,working.shape[0]//2)), Image.Resampling.BOX))
    return {"folder": folder.name, "passed": True, "size": meta["size"],
            "checks": {k: bool(v) for k,v in checks.items()}, "maximum_normal_length_error": error,
            "files_checked": 4, "mip_diagnostics": mip_metrics,
            "visual_approval": "not inferred; final compressed DDS still requires target review"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--preset", choices=PRESETS)
    for name, typ in [("width",int),("height",int),("seed",int),("grain-px",float),("slope",float),
                      ("inverse-roughness",int),("metallic",int),("color-noise",float),
                      ("roughness-noise",float),("grain-mm",float),("texels-per-meter",float),("required-mip",int)]:
        g.add_argument("--"+name, type=typ)
    g.add_argument("--color", type=int, nargs=3)
    g.add_argument("--tint-reason")
    v = sub.add_parser("verify")
    v.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        result = verify_patch(args.folder)
    else:
        if args.preset:
            if args.width is not None or args.height is not None:
                parser.error("Choose preset or dimensions")
            width, height, seed = PRESETS[args.preset]
        else:
            if args.width is None or args.height is None:
                parser.error("Provide preset or width and height")
            width, height, seed = args.width, args.height, 15051
        names = ("color","inverse_roughness","metallic","color_noise","roughness_noise","grain_mm","texels_per_meter","required_mip","tint_reason")
        make_patch(args.out, width, height, seed if args.seed is None else args.seed,
                   args.grain_px, args.slope, **{n:getattr(args,n) for n in names})
        result = verify_patch(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
