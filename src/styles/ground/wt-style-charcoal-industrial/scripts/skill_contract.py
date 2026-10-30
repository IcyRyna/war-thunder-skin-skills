"""Canonical charcoal policy, identity, and strict input helpers."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def identity():
    return read_json(ROOT / "VERSION.json")


def policy():
    return read_json(ROOT / "references/data/style-policy.json")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be a concrete nonempty description")
    if value.strip().casefold() in {"todo", "pending", "unresolved", "tbd", "待填"}:
        raise ValueError(label + " is unresolved")
    return value


def number(value, label, low, high, integer=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high or (integer and int(value) != value)):
        raise ValueError(f"{label} must be {'an integer' if integer else 'finite'} in {low}..{high}")
    return int(value) if integer else float(value)


def rgb(value, label="RGB"):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(label + " must contain three bytes")
    return [number(v, label, 0, 255, integer=True) for v in value]


def binary(value, label="mask", shape=None):
    result = np.asarray(value)
    if (result.ndim != 2 or (shape is not None and result.shape != shape)
            or not np.isin(result, (0, 1, 255)).all()):
        raise ValueError(label + " must be a matching binary mask")
    return result.astype(bool)


def checked_file(root, spec, label):
    if not isinstance(spec, dict):
        raise ValueError(label + " requires file and sha256")
    value = require_text(spec.get("file"), label + " file")
    if value.startswith('asset-pack:'):
        from asset_pack import reference
        path = reference(value)
    else:
        path = (Path(root) / value).resolve(strict=True)
    if not path.is_file() or sha(path) != spec.get("sha256"):
        raise ValueError(label + " hash mismatch")
    return path


def load_mask(root, spec, label, shape=None):
    path = checked_file(root, spec, label)
    with Image.open(path) as image:
        if image.mode != "L":
            raise ValueError(label + " must be an L image")
        return binary(np.array(image), label, shape)


def material_parameters(record):
    """Resolve explicit C/R/B; never invent cross-vehicle metal values."""
    rules = policy()["materials"]
    role = record.get("role")
    if role not in rules["roles"]:
        raise ValueError("Unknown material role: " + str(role))
    state = record.get("state")
    require_text(record.get("reason"), "material reason")
    if state in {"preserve", "not_applicable"}:
        if record.get("parameters"):
            raise ValueError("Preserved/absent material cannot carry paint parameters")
        return {"role": role, "state": state, "reason": record["reason"]}
    if state != "paint":
        raise ValueError("Material state must be paint, preserve or not_applicable")
    if role in {"glass", "rubber", "net"}:
        raise ValueError("Special materials use their native route; preserve here and record separate treatment")
    params = record.get("parameters", {})
    color_mode=record.get("color_mode","neutral")
    paint_roles=[]
    if color_mode=="paint_roles":
        if "color_srgb" in params:
            raise ValueError("Role-based material color cannot carry an ignored color_srgb")
        paint_roles=params.get("paint_roles")
        if not isinstance(paint_roles,list) or not paint_roles or len(set(paint_roles))!=len(paint_roles) or not set(paint_roles)<=set(policy()["paint_roles"]):
            raise ValueError("Material must name actual A/B/C/F paint roles")
        color=None
    else:
        color=rgb(params.get("color_srgb"),"material color")
        if color_mode=="neutral":
            if max(color)!=min(color):raise ValueError("Neutral material requires R=G=B")
        elif color_mode=="tinted":
            require_text(record.get("tint_reason"),"intentional tint reason")
        else:raise ValueError("Unknown material color mode")
    if record.get("packed_n_semantics") != rules["packed_n_semantics"]:
        raise ValueError("Verify target packed N semantics before using R/B parameters")
    require_text(record.get("shader_evidence"), "target shader evidence")
    return {"role": role, "state": state, "color_srgb": color, "color_mode": color_mode, "paint_roles": paint_roles,
            "inverse_roughness_center": number(params.get("inverse_roughness_center"), "R", 0, 255, True),
            "metallic": number(params.get("metallic"), "B", 0, 255, True),
            "normal_policy": "preserve structural G/A; use explicit RNM for added microstructure"}
