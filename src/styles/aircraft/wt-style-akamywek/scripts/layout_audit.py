"""Audit declared source-critical pixels through an affine portrait placement.

Checks real source pixels against the carrier and the exported instance layer.
This is a 2-D consistency check, not a 3-D visibility or aesthetic score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = 8192 * 8192


class AuditError(ValueError):
    """Invalid or unverifiable audit input."""


def asset(root: Path, record: dict, mode: str) -> tuple[np.ndarray, dict]:
    if not isinstance(record, dict):
        raise AuditError('Image reference must contain path and sha256')
    name = record.get('path')
    if not isinstance(name, str) or not name or '\\' in name:
        raise AuditError('Use a nonempty portable relative image path')
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or any(':' in x for x in rel.parts):
        raise AuditError(f'Image path escapes plan directory: {name}')
    path = root.joinpath(*rel.parts)
    for part in [path, *path.parents]:
        if part == root.parent:
            break
        if part.is_symlink() or (part.exists() and getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
            raise AuditError(f'Linked image path is not supported: {name}')
    try:
        path.resolve().relative_to(root.resolve())
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != record.get('sha256'):
            raise AuditError(f'Image hash mismatch: {name}')
        with Image.open(path) as im:
            if min(im.size) < 1 or max(im.size) > 8192:
                raise AuditError(f'Unsupported dimensions: {name}: {im.size}')
            if mode == 'RGBA' and 'A' not in im.getbands():
                raise AuditError(f'Actual RGBA instance/source required: {name}')
            values = np.asarray(im.convert(mode)).copy()
    except (OSError, ValueError) as exc:
        if isinstance(exc, AuditError):
            raise
        raise AuditError(f'Cannot read {name}: {exc}') from exc
    return values, {'path': name, 'sha256': digest, 'size': [values.shape[1], values.shape[0]]}


def audit(plan_path: Path) -> dict:
    root = plan_path.resolve().parent
    try:
        plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise AuditError(f'Cannot read plan: {exc}') from exc
    if not isinstance(plan, dict) or plan.get('schema_version') != 1:
        raise AuditError('Expected layout audit schema_version 1')
    canvas = plan.get('canvas')
    if (not isinstance(canvas, list) or len(canvas) != 2 or
            any(type(v) is not int or not 1 <= v <= 8192 for v in canvas)):
        raise AuditError('canvas must be [width, height], each 1..8192')
    instances = plan.get('instances')
    if not isinstance(instances, list) or not 1 <= len(instances) <= 64:
        raise AuditError('Provide 1..64 actual portrait instances')
    width, height = canvas
    results, identifiers = [], set()
    for instance in instances:
        if not isinstance(instance, dict):
            raise AuditError('Each instance must be an object')
        ident = instance.get('id')
        if not isinstance(ident, str) or not ident or ident in identifiers:
            raise AuditError('Instance IDs must be nonempty and unique')
        identifiers.add(ident)
        matrix = instance.get('source_to_canvas')
        if (not isinstance(matrix, list) or len(matrix) != 6 or
                any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e6 for x in matrix)):
            raise AuditError(f'{ident}: six finite affine coefficients required')
        a, b, c, d, e, f = matrix
        determinant = a * e - b * d
        if abs(determinant) < 1e-10:
            raise AuditError(f'{ident}: singular transform')
        if determinant < 0 and instance.get('allow_mirror') is not True:
            raise AuditError(f'{ident}: mirrored art needs an explicit allow_mirror decision')
        threshold = instance.get('alpha_min', 128)
        if type(threshold) is not int or not 1 <= threshold <= 255:
            raise AuditError(f'{ident}: alpha_min must be an integer 1..255')
        source, source_id = asset(root, instance.get('source'), 'RGBA')
        critical, critical_id = asset(root, instance.get('critical'), 'L')
        layer, layer_id = asset(root, instance.get('actual_layer'), 'RGBA')
        carrier, carrier_id = asset(root, instance.get('carrier'), 'L')
        if source.shape[:2] != critical.shape or carrier.shape != (height, width) or layer.shape[:2] != (height, width):
            raise AuditError(f'{ident}: source/core or canvas/layer/carrier dimensions disagree')
        if np.any((critical > 0) & (source[:, :, 3] < threshold)):
            raise AuditError(f'{ident}: critical mask includes absent/transparent source pixels')
        total = int(np.count_nonzero(critical))
        if total == 0:
            raise AuditError(f'{ident}: empty critical mask cannot prove preservation')
        counts = {'outside_canvas': 0, 'outside_carrier': 0, 'missing_export_alpha': 0}
        examples = []
        # Bounded chunks avoid building full-size coordinate grids for 8K art.
        for y0 in range(0, critical.shape[0], 128):
            ys, xs = np.nonzero(critical[y0:y0 + 128] > 0)
            ys += y0
            u = np.floor(a * (xs + .5) + b * (ys + .5) + c).astype(np.int64)
            v = np.floor(d * (xs + .5) + e * (ys + .5) + f).astype(np.int64)
            inside = (u >= 0) & (u < width) & (v >= 0) & (v < height)
            counts['outside_canvas'] += int(np.count_nonzero(~inside))
            valid = np.flatnonzero(inside)
            off = np.zeros(len(xs), dtype=bool)
            lost = np.zeros(len(xs), dtype=bool)
            off[valid] = carrier[v[valid], u[valid]] < threshold
            lost[valid] = layer[v[valid], u[valid], 3] < threshold
            counts['outside_carrier'] += int(np.count_nonzero(off))
            counts['missing_export_alpha'] += int(np.count_nonzero(lost))
            for j in np.flatnonzero((~inside) | off | lost)[:max(0, 12 - len(examples))]:
                examples.append({'source_pixel': [int(xs[j]), int(ys[j])],
                                 'output_pixel': [int(u[j]), int(v[j])],
                                 'outside_canvas': bool(not inside[j]),
                                 'outside_carrier': bool(off[j]),
                                 'missing_export_alpha': bool(lost[j])})
        results.append({'id': ident, 'passed': not any(counts.values()),
                        'critical_source_pixels': total, 'failure_counts': counts,
                        'examples': examples, 'alpha_min': threshold,
                        'source_to_canvas': matrix, 'determinant': determinant,
                        'inputs': {'source': source_id, 'critical': critical_id,
                                   'actual_layer': layer_id, 'carrier': carrier_id}})
    return {'schema_version': 1, 'passed': all(x['passed'] for x in results),
            'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            'canvas': canvas, 'instances': results,
            'measurement': 'Each declared source-critical pixel centre maps by affine transform to a target pixel; counts use source pixels and may overlap across failure categories.',
            'limits': ['2-D affine mapping only; no nonlinear bake or 3-D visibility proof',
                       'Checks alpha/carrier, not identity of RGB content or aesthetic quality',
                       'Caller must verify the critical mask actually covers the required anatomy',
                       'Many-to-one downsampling may pass this test; inspect detail at final scale']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.plan)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'passed': result['passed'], 'out': str(args.out)}, ensure_ascii=False))
        return 0 if result['passed'] else 1
    except (AuditError, OSError) as exc:
        print(f'layout-audit: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
