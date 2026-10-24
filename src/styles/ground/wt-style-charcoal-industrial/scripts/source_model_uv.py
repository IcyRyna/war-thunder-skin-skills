"""Validate paired model/UV evidence before a SPECTRE42 placement is composed.

This checks identity and evidence completeness. It cannot judge whether a person
has correctly understood the pictured physical part or its functional purpose.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def checked_file(root, record, label, cache):
    if not isinstance(record, dict) or not record.get('file'):
        raise ValueError(label + ' needs a file and SHA-256')
    path = (root / record['file']).resolve()
    if not path.is_file():
        raise ValueError(label + ' file is missing: ' + str(path))
    if path not in cache:
        cache[path] = sha(path)
    if cache[path] != record.get('sha256'):
        raise ValueError(label + ' hash changed')
    return path


def validate_study(path):
    """Read a frozen study and return the locally checked region IDs."""
    path = Path(path).resolve()
    root = path.parent
    study = json.loads(path.read_text(encoding='utf-8-sig'))
    if study.get('schema_version') != 1:
        raise ValueError('Model/UV study schema_version must be 1')
    if not study.get('source_identity', {}).get('vehicle'):
        raise ValueError('Exact source vehicle and attachment state required')
    cache = {}
    checked_file(root, study.get('source_model'), 'Source model', cache)
    checked_file(root, study.get('material_binding'), 'Native material binding', cache)
    regions = {}
    for row in study.get('regions', []):
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in regions:
            raise ValueError('Unique nonempty source region IDs required')
        if row.get('state') != 'checked_local':
            raise ValueError('Source model/UV pairing is unresolved: ' + identifier)
        if not row.get('semantic_role') or not row.get('observed_parts'):
            raise ValueError('Source part identity and semantic role required')
        if not row.get('resource'):
            raise ValueError('Actual material resource required')
        model_view = checked_file(root, row.get('model_view'), 'Model view', cache)
        uv_view = checked_file(root, row.get('uv_view'), 'UV view', cache)
        texture = checked_file(root, row.get('source_texture'), 'Source texture', cache)
        if model_view == uv_view or model_view == texture:
            raise ValueError('Model and UV must be separate observations')
        uv = row.get('uv_region', {})
        size = uv.get('image_size')
        box = uv.get('box_xyxy')
        if uv.get('coordinate_space') != 'image_pixels_top_left':
            raise ValueError('Explicit image-pixel UV coordinate convention required')
        if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v < 1 for v in size):
            raise ValueError('Native source texture dimensions required')
        if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            raise ValueError('Finite UV source rectangle required')
        if not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
            raise ValueError('UV source rectangle outside native image')
        if row.get('orientation', {}).get('state') != 'checked_local':
            raise ValueError('Model and UV orientation must be compared')
        if row.get('sharing', {}).get('state') != 'checked_local':
            raise ValueError('Shared and mirrored UV effects must be compared')
        if row.get('sharing', {}).get('kind') not in ('unique', 'repeated', 'mirrored', 'mixed'):
            raise ValueError('Explicit source sharing classification required')
        if not row.get('observation'):
            raise ValueError('A concrete paired observation is required')
        regions[identifier] = row
    if not regions:
        raise ValueError('No paired model/UV regions')
    return regions


def validate_plan(plan_path, plan):
    """Require each placement to name a source region and target adaptation."""
    cache = {}
    root = Path(plan_path).resolve().parent
    path = checked_file(root, plan.get('source_study'), 'Paired model/UV source study', cache)
    regions = validate_study(path)
    for placement in plan.get('placements', []):
        identifier = placement.get('source_region')
        if identifier not in regions:
            raise ValueError('Placement needs a checked source model/UV region: ' + str(placement.get('id', '?')))
        adaptation = placement.get('target_correspondence', {})
        if not adaptation.get('role') or not adaptation.get('reason'):
            raise ValueError('Target part role and adaptation reason required')
        if adaptation.get('surface') != placement.get('surface'):
            raise ValueError('Target correspondence must identify this placement surface')
    return {'paired_regions': len(regions), 'placements_checked': len(plan.get('placements', [])),
        'semantic_judgment': 'requires visual comparison; not proved by this checker'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if bool(args.study) == bool(args.plan):
        parser.error('Choose exactly one of --study and --plan')
    if args.study:
        result = {'paired_regions': len(validate_study(args.study)), 'semantic_judgment': 'manual comparison still required'}
    else:
        result = validate_plan(args.plan, json.loads(args.plan.read_bytes()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
