"""Draw editable side and plan markings from a chosen aircraft's prepared flight geometry."""
from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from artifact_io import ArtifactTransaction
from surface_preview import load_geometry


def direction(axis):
    return np.eye(3)["xyz".index(axis[-1])] * (-1 if axis.startswith("-") else 1)


def select_nodes(geometry, patterns):
    names = [str(v) for v in geometry["names"]]
    present = {names[i] for i in np.unique(geometry["node_ids"])}
    selected = set()
    for pattern in patterns:
        found = {name for name in present if fnmatchcase(name, pattern)}
        if not found:
            raise ValueError(f"No geometry matches node pattern {pattern!r}")
        selected.update(found)
    mask = np.isin(geometry["node_ids"], [i for i, name in enumerate(names) if name in selected])
    return geometry["triangles"][mask], sorted(selected)


def project_outline(triangles, forward, upward, pixels, tolerance):
    try:
        import cv2
    except ImportError as exc:
        raise ValueError("aircraft_markings requires opencv-python for contour extraction") from exc
    # JSON coordinates use positive Y upwards. PNG coordinates use positive Y downwards.
    xy = np.stack((triangles @ forward, triangles @ upward), axis=-1)
    low = xy.min(axis=(0, 1))
    high = xy.max(axis=(0, 1))
    length, height = high - low
    if min(length, height) <= 0:
        raise ValueError("The selected geometry has no two-dimensional extent in this view")
    scale = (pixels - 1) / length
    h = math.ceil(height * scale) + 5
    if h > 4096 or pixels + 4 > 4100:
        raise ValueError("Projected image exceeds supported dimensions; verify nose/up axes or reduce --pixels")
    mask = np.zeros((h, pixels + 4), np.uint8)
    projected = np.array(xy, dtype=np.float64)
    projected[:, :, 0] = (xy[:, :, 0]-low[0])*scale+2
    projected[:, :, 1] = (high[1]-xy[:, :, 1])*scale+2
    for face in np.rint(projected).astype(np.int32):
        cv2.fillConvexPoly(mask, face, 255)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        raise ValueError("The selected geometry has no visible silhouette")

    def points(index):
        outline = cv2.approxPolyDP(contours[index], tolerance, True).reshape(-1, 2)
        if len(outline) < 3 or cv2.contourArea(outline) == 0:
            return []
        local = outline.astype(np.float64)
        local[:, 0] = (local[:, 0] - 2) / (pixels-1) - .5
        local[:, 1] = height/(2*length) - (local[:, 1]-2)/(pixels-1)
        return np.round(local, 7).tolist()

    parts = []
    tree = hierarchy[0]
    for i in sorted(range(len(contours)), key=lambda i: cv2.contourArea(contours[i]), reverse=True):
        if tree[i, 3] >= 0:
            continue
        outer = points(i)
        if not outer:
            continue
        holes = []
        child = tree[i, 2]
        while child >= 0:
            ring = points(child)
            if ring:
                holes.append(ring)
            child = tree[child, 0]
        parts.append(dict(points=outer, holes=holes))
    if not parts:
        raise ValueError("Contour tolerance removed the outline")
    rgba = Image.new("RGBA", (mask.shape[1], mask.shape[0]), "white")
    rgba.putalpha(Image.fromarray(mask))
    return rgba, {"length_m": float(length), "height_m": float(height), "parts": parts}


def place_outline(outline, *, chart, prefix, center, nose, upper, length, fill):
    """Convert one normalized view into editable vector_paint polygon items in chart metres."""
    origin, front, up = (np.asarray(v, dtype=float) for v in (center, nose, upper))
    if any(v.shape != (2,) or not np.isfinite(v).all() for v in (origin, front, up)):
        raise ValueError("center, nose and upper must be finite chart-coordinate pairs")
    if not math.isfinite(length) or length <= 0 or min(np.linalg.norm(front), np.linalg.norm(up)) == 0:
        raise ValueError("length and direction lengths must be positive")
    front = front / np.linalg.norm(front)
    up = up / np.linalg.norm(up)
    if abs(front @ up) > 1e-5:
        raise ValueError("nose and upper must be perpendicular in chart metres")

    def transform(rows):
        return np.round(origin + (np.asarray(rows) @ np.stack((front, up))) * length, 7).tolist()

    items = []
    for n, part in enumerate(outline["parts"], 1):
        item = dict(id=f"{prefix}-{n}", type="polygon", chart=chart, points=transform(part["points"]), fill=fill)
        if part["holes"]:
            item["holes"] = [transform(ring) for ring in part["holes"]]
        items.append(item)
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    axes = ["x","-x","y","-y","z","-z"]
    parser.add_argument("--nose", choices=axes, required=True)
    parser.add_argument("--up", choices=axes, required=True)
    parser.add_argument("--node", action="append", required=True, help="Include a verified node name or glob; repeat for the flight silhouette")
    parser.add_argument("--pixels", type=int, default=1024, help="Projected pixels along the nose-to-tail dimension")
    parser.add_argument("--tolerance", type=float, default=1.0, help="Vector approximation tolerance in projected pixels")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not 64 <= args.pixels <= 4096 or not 0 <= args.tolerance <= 4:
            raise ValueError("Use 64..4096 pixels and a contour tolerance of 0..4 px")
        nose, up = direction(args.nose), direction(args.up)
        if nose @ up:
            raise ValueError("--nose and --up must use different axes")
        geometry = load_geometry(args.geometry, allow_repeat_uv=True)
        triangles, nodes = select_nodes(geometry, args.node)
        report = dict(schema_version=1, geometry_sha256=geometry["_sha256"], nodes=nodes, triangles=len(triangles),
                      nose_axis=args.nose, up_axis=args.up, pixels=args.pixels, tolerance_px=args.tolerance,
                      coordinates="Unit nose-to-tail length; +X is nose. +Y is fin-up for side, port for plan.", views={})
        targets = [args.out/"side.png", args.out/"plan.png", args.out/"outlines.json"]
        with ArtifactTransaction(targets, inputs=[args.geometry], label="aircraft-markings") as tx:
            for name, vertical, target in (("side",up,targets[0]), ("plan",-np.cross(nose,up),targets[1])):
                image, report["views"][name] = project_outline(triangles, nose, vertical, args.pixels, args.tolerance)
                image.save(tx.stage(target))
            tx.stage(targets[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n",encoding="utf8")
            tx.commit()
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
