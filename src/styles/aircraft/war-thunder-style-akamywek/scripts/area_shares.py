"""Classify registered model-view pixels by their paint roles or explicit RGB swatches."""

from pathlib import Path
import json
import hashlib
import re

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from artifact_io import ArtifactTransaction
from surface_preview import camera_fingerprint, load_geometry

ROLES = ("other", "dark", "signature", "tint", "white", "portrait", "mechanical")


def sha(path):
    with path.open("rb") as f:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def layer_atlas(path):
    spec = json.loads(path.read_text("utf8"))
    geo = (path.parent / spec["geometry"]).resolve()
    g = load_geometry(geo, allow_repeat_uv=True)
    materials = spec["atlas_materials"]
    if not materials or not set(materials) <= set(g["material_names"]):
        raise ValueError("Unknown or empty atlas_materials")
    layers = spec["layers"]
    if not layers:
        raise ValueError("Empty role layer list")
    # Ordinary layers follow their paint order. Semantic ownership overrides colour.
    ranks = {"portrait": 1, "mechanical": 2}
    atlas = None
    inputs = [path, geo]
    for row in sorted(layers, key=lambda r: ranks.get(r["role"], 0)):
        role = ROLES.index(row["role"])
        file = (path.parent / row["mask"]).resolve()
        inputs.append(file)
        cut = row.get("threshold", 128)
        if type(cut) is not int or not 1 <= cut <= 255:
            raise ValueError("threshold must be 1..255")
        with Image.open(file) as im:
            if im.mode not in ("L", "RGBA", "LA"):
                raise ValueError("Expected L mask or image alpha")
            mask = np.asarray(im if im.mode == "L" else im.getchannel("A"))
        if atlas is None:
            atlas = np.zeros(mask.shape, np.uint8)
        if mask.shape != atlas.shape:
            raise ValueError("Role layers must have matching native dimensions")
        selected = mask >= cut
        if row.get("exclude_mask"):
            exclude = (path.parent / row["exclude_mask"]).resolve()
            inputs.append(exclude)
            with Image.open(exclude) as im:
                if im.mode != "L" or im.size != (mask.shape[1], mask.shape[0]):
                    raise ValueError("exclude_mask must be a native-size L protection mask")
                selected &= np.asarray(im) == 0
        atlas[selected] = role
    return g, atlas, np.isin(g["material_names"][g["material_ids"]], materials), inputs


def project_roles(bundle, root, name, image, mask):
    g, atlas, body, _ = bundle
    receipt = root / (name + ".json")
    depth = root / (name + "-depth.npz")
    meta = json.loads(receipt.read_text("utf8"))
    if (
        meta["geometry_sha256"] != g["_sha256"]
        or meta["image_sha256"] != sha(image)
        or meta["depth_sha256"] != sha(depth)
        or meta["camera_sha256"] != camera_fingerprint(meta)
    ):
        raise ValueError("Camera, geometry, colour view or depth receipt mismatch")
    with np.load(depth, allow_pickle=False) as data:
        owners = data["owners"]
        if (
            str(data["geometry_sha256"]) != g["_sha256"]
            or str(data["camera_sha256"]) != meta["camera_sha256"]
        ):
            raise ValueError("Foreign depth/owners")
    if (
        owners.shape != (meta["height"], meta["width"])
        or owners.dtype.kind != "i"
        or np.any(owners < -1)
        or np.any(owners >= len(body))
        or not np.array_equal(owners >= 0, mask)
    ):
        raise ValueError("Invalid or mismatching model-view owners")
    screen = g["triangles"] @ np.asarray(meta["basis"], np.float32).T
    screen[:, :, 0] = (screen[:, :, 0] - meta["center"][0]) * meta["scale"] + meta["width"] * 0.5
    screen[:, :, 1] = (meta["center"][1] - screen[:, :, 1]) * meta["scale"] + meta["height"] * 0.5
    result = np.zeros(mask.shape, np.uint8)
    for start in range(0, len(mask), 128):
        sl = slice(start, start + 128)
        visible = mask[sl] & body[np.maximum(owners[sl], 0)]
        y, x = np.nonzero(visible)
        tri = owners[sl][y, x]
        a, b, c = np.moveaxis(screen[tri, :, :2].astype(float), 1, 0)
        ex, fx = b - a, c - a
        dx = x + 0.5 - a[:, 0]
        dy = start + y + 0.5 - a[:, 1]
        det = ex[:, 0] * fx[:, 1] - ex[:, 1] * fx[:, 0]
        if np.any(abs(det) < 1e-12):
            raise ValueError("Degenerate visible triangle")
        w1 = (dx * fx[:, 1] - dy * fx[:, 0]) / det
        w2 = (ex[:, 0] * dy - ex[:, 1] * dx) / det
        a, b, c = np.moveaxis(g["uvs"][tri], 1, 0)
        uv = (a + w1[:, None] * (b - a) + w2[:, None] * (c - a)).clip(0, 1)
        tx = np.rint(uv[:, 0] * (atlas.shape[1] - 1)).astype(int)
        ty = np.rint((1 - uv[:, 1]) * (atlas.shape[0] - 1)).astype(int)
        result[sl][y, x] = atlas[ty, tx]
    return result, [receipt, depth]


def colour(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"Expected #rrggbb, got {value!r}")
    return np.array(list(bytes.fromhex(value[1:])), dtype=float)


def palette_index(spec):
    groups = spec.get("swatches", {})
    if not isinstance(groups, dict) or set(groups) - set(ROLES[1:5]):
        raise ValueError("Swatches must name dark, signature, tint or white")
    points, labels = [], []
    for name, rows in groups.items():
        if not isinstance(rows, list) or not rows:
            raise ValueError("Each swatch role requires a nonempty list")
        for sample in rows:
            # A nested list is an ordered ramp, e.g. [jade, gold]. Simple entries
            # are independent colours; no interpolation between unrelated swatches.
            stops = [colour(v) for v in sample] if isinstance(sample, list) else [colour(sample)]
            if not stops:
                raise ValueError("Empty gradient")
            samples = [stops[0]]
            for start, end in zip(stops, stops[1:]):
                samples.extend(np.linspace(start, end, 1 + max(1, int(np.ceil(abs(end - start).max())))))
            points.extend(samples)
            labels.extend([ROLES.index(name)] * len(samples))
    radius = float(spec.get("max_rgb_distance", 24))
    if not points or not 0 <= radius <= 442:
        raise ValueError("Need at least one swatch and max_rgb_distance in [0,442]")
    return cKDTree(np.array(points)), np.array(labels, np.uint8), radius


def measure(rgb, mask, roles=None, palette=None):
    if roles is None and palette is None:
        raise ValueError("Provide labelled role masks or a palette")
    if rgb.shape[:2] != mask.shape or (roles is not None and roles.shape != mask.shape):
        raise ValueError("Model mask, role mask and render must have identical dimensions")
    labels = np.zeros(mask.shape, np.uint8) if roles is None else roles.copy()
    if labels.dtype != np.uint8 or np.any(labels > 6):
        raise ValueError("Role mask must contain integer IDs 0..6")
    if palette is not None:
        tree, index, radius = palette
        for y in range(0, len(mask), 128):
            sl = slice(y, y + 128)
            todo = mask[sl] & (labels[sl] == 0)
            if todo.any():
                dist, nearest = tree.query(rgb[sl][todo])
                labels[sl][todo] = np.where(dist <= radius, index[nearest], 0)
    counts = np.bincount(labels[mask], minlength=len(ROLES))
    return dict(
        pixels=dict(zip(ROLES, map(int, counts))),
        total=int(counts.sum()),
        percent={name: round(100 * int(n) / max(1, counts.sum()), 3) for name, n in zip(ROLES, counts)},
        semantic_masks_used=roles is not None,
    )


def report(args, legacy, legacy_classes):
    root = Path(args.views)
    if not (args.palette or args.roles or args.layer_roles or args.legacy_f2a):
        raise ValueError("Select --palette, --roles or --layer-roles, or explicitly select --legacy-f2a")
    if args.roles and args.layer_roles:
        raise ValueError("Choose either view masks or native role layers")
    if args.legacy_f2a and (args.palette or args.roles or args.layer_roles):
        raise ValueError("--legacy-f2a is a separate historical metric")
    palette = palette_index(json.loads(args.palette.read_text("utf8"))) if args.palette else None
    views = {}
    inputs = [args.palette] if args.palette else []
    bundle = layer_atlas(args.layer_roles) if args.layer_roles else None
    if bundle:
        inputs.extend(bundle[3])
    for name in args.view or ("top", "bottom", "left"):
        if not re.fullmatch(r"[\w-]+", name):
            raise ValueError("Invalid camera name")
        image = root / (name + ".png")
        maskfile = root / (name + "-mask.png")
        inputs.extend([image, maskfile])
        with Image.open(image) as im, Image.open(maskfile) as m:
            rgb = np.asarray(im.convert("RGB"))
            mask = np.asarray(m.convert("L")) > 127
        roles = None
        if args.roles:
            f = args.roles / (name + "-roles.png")
            inputs.append(f)
            with Image.open(f) as im:
                if im.mode not in ("P", "L"):
                    raise ValueError("Role masks must use L or indexed P")
                roles = np.array(im)
        elif bundle:
            roles, refs = project_roles(bundle, root, name, image, mask)
            inputs.extend(refs)
        views[name] = legacy(rgb, mask) if args.legacy_f2a else measure(rgb, mask, roles, palette)
    result = dict(method="legacy-f2a" if args.legacy_f2a else "roles-and-swatches", views=views)
    if args.legacy_f2a:
        result["classes"] = legacy_classes
    out = args.out or root / "area-shares.json"
    with ArtifactTransaction([out], inputs=list(dict.fromkeys(inputs)), label="area-shares") as tx:
        tx.stage(out).write_text(json.dumps(result, indent=2, ensure_ascii=False), "utf8")
        tx.commit()
    return result


def seven(args):
    paths = [
        Path(args.views) / (n + ".png") for n in ("top", "bottom", "left", "right", "front", "rear", "iso")
    ]
    with ArtifactTransaction([args.out], inputs=paths, label="seven-views") as tx:
        with Image.open(paths[0]) as ref:
            w, h = ref.size
        sheet = Image.new("RGB", (4 * w, 2 * h), (238, 238, 238))
        for i, path in enumerate(paths):
            with Image.open(path) as im:
                tile = im.convert("RGB")
                tile.thumbnail((w, h), Image.Resampling.LANCZOS)
                sheet.paste(
                    tile, ((i % 4) * w + (w - tile.width) // 2, (i // 4) * h + (h - tile.height) // 2)
                )
        sheet.save(tx.stage(args.out), format="PNG")
        tx.commit()
