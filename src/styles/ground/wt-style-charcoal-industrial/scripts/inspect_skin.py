"""Read-only BLK/DDS inspection with optional explicit texture semantics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct

from artifact_io import ArtifactTransaction
from tank_core import load_image, write_json
from texture_semantics import validate_alpha_semantics, validate_color_space


def _relative(value: str) -> Path:
    path = PurePosixPath(value.replace('\\', '/'))
    if not value or path.is_absolute() or '..' in path.parts or ':' in value:
        raise ValueError(f'Texture path must stay inside the skin folder: {value!r}')
    return Path(*path.parts)


def _metadata(path: Path) -> dict:
    if path.suffix.lower() != '.dds':
        return {'container': path.suffix[1:].lower(), 'mip_count': 1}
    with path.open('rb') as stream:
        header = stream.read(148)
    if len(header) < 128 or header[:4] != b'DDS ' or struct.unpack_from('<I', header, 4)[0] != 124:
        raise ValueError(f'Invalid DDS header: {path}')
    fourcc = header[84:88]
    result = {'container': 'dds', 'mip_count': max(1, struct.unpack_from('<I', header, 28)[0])}
    if fourcc == b'DX10':
        if len(header) < 148:
            raise ValueError(f'Truncated DDS DX10 header: {path}')
        result['dxgi_format'] = struct.unpack_from('<I', header, 128)[0]
    else:
        result['fourcc'] = fourcc.rstrip(b'\0').decode('ascii', errors='replace') or None
        result['rgb_bits'] = struct.unpack_from('<I', header, 88)[0]
    return result


def inspect(folder: Path, materials: Path | None = None, manifest: Path | None = None,
            profile: Path | None = None) -> dict:
    folder = folder.resolve(strict=True)
    blks = list(folder.glob('*.blk'))
    if len(blks) != 1:
        raise ValueError('Expected exactly one BLK in selected skin folder')
    issues, notes, rows, resources = [], [], [], []
    profile_data = json.loads(profile.read_text(encoding='utf-8-sig')) if profile else {}
    defaults = profile_data.get('texture_alpha_semantics', {})
    if not isinstance(defaults, dict):
        raise ValueError('Profile texture_alpha_semantics must be a role mapping')
    for role, value in defaults.items():
        validate_alpha_semantics(value, role)
    declarations = {}
    if manifest:
        data = json.loads(manifest.read_text(encoding='utf-8-sig'))
        if not isinstance(data.get('textures'), list):
            raise ValueError('Manifest textures must be an array')
        for row in data['textures']:
            name = _relative(row['file']).as_posix()
            role = row['role']
            semantics = validate_alpha_semantics(row.get('alpha_semantics'), role)
            color_space = validate_color_space(row.get('color_space'), semantics)
            declaration = {'role': role, 'alpha_semantics': semantics, 'color_space': color_space}
            # Build manifests may name PNG/TGA sources; emitted DDS retains the stem.
            for target in {name, str(PurePosixPath(name).with_suffix('.dds'))}:
                key = target.casefold()
                if key in declarations and declarations[key] != declaration:
                    raise ValueError(f'Conflicting manifest declarations for {target}')
                declarations[key] = declaration
    text = blks[0].read_text(encoding='utf-8-sig')
    text = re.sub(r'(?m)//[^\n]*|#[^\n]*', '', text)
    mappings = re.findall(r'\b(replace_tex|set_tex)\s*\{([^{}]*)\}', text, re.S)
    if not mappings:
        issues.append('BLK contains no texture mappings')
    for kind, body in mappings:
        source = re.search(r'\bfrom:t\s*=\s*"([^"\n]+)"', body)
        target = re.search(r'\bto:t\s*=\s*"([^"\n]+)"', body)
        if source is None or target is None:
            issues.append('Incomplete ' + kind + ' mapping')
            continue
        resource = source.group(1)
        try:
            relative = _relative(target.group(1))
        except ValueError as error:
            issues.append(str(error))
            continue
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder):
            issues.append('Target escapes skin folder: ' + str(relative))
            continue
        if not path.is_file():
            issues.append('Missing texture: ' + str(relative))
            continue
        if path.suffix.lower() not in {'.dds', '.tga'}:
            issues.append('Unsupported game texture: ' + str(relative))
            continue
        if kind == 'set_tex' and 'camo_skin_tex' not in body:
            issues.append('set_tex is missing camo_skin_tex: ' + str(relative))
        if resource in resources:
            issues.append('Duplicate source resource: ' + resource)
        resources.append(resource)
        declaration = declarations.get(relative.as_posix().casefold())
        role = (declaration or {}).get('role')
        inferred = role is None
        if role is None:
            role = 'normal' if re.search(r'_n(?:_dmg)?\*?$', resource) else ('ao' if '_ao' in resource else 'color')
        semantics = (declaration or {}).get('alpha_semantics', defaults.get(role))
        color_space = (declaration or {}).get('color_space')
        if semantics is not None:
            color_space = validate_color_space(color_space, semantics)
        if manifest and declaration is None:
            issues.append('Mapped texture has no manifest declaration: ' + relative.as_posix())
        try:
            image = load_image(path)
            metadata = _metadata(path)
        except (OSError, ValueError) as error:
            issues.append(f'Unreadable texture {relative.as_posix()}: {error}')
            continue
        extrema = dict(zip(image.getbands(), image.getextrema()))
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        rows.append({'resource': resource, 'target': relative.as_posix(), 'mapping': kind,
                     'role': role, 'role_source': 'filename_inference' if inferred else 'manifest',
                     'alpha_semantics': semantics, 'color_space': color_space,
                     'dimensions': list(image.size), 'mode': image.mode,
                     'channel_extrema': extrema, 'bytes': path.stat().st_size,
                     'sha256': digest, **metadata})
        if role == 'color' and semantics is None:
            notes.append('Declare colour alpha semantics explicitly; pixel alpha does not establish opacity: ' + relative.as_posix())
    if materials:
        data = json.loads(materials.read_text(encoding='utf-8-sig'))
        aliases = {value.rstrip('*') for material in data['materials'] for value in material.get('texture_slots', []) if value}
        issues.extend('Resource absent in model: ' + resource for resource in resources if resource.rstrip('*') not in aliases)
    targets = {row['target'].casefold() for row in rows}
    notes.extend('Unreferenced texture: ' + path.relative_to(folder).as_posix()
                 for path in folder.rglob('*') if path.is_file() and path.suffix.lower() in {'.dds', '.tga'}
                 and path.relative_to(folder).as_posix().casefold() not in targets)
    counts = {role: len({row['target'].casefold() for row in rows if row['role'] == role})
              for role in ('color', 'normal', 'ao')}
    expected = profile_data.get('texture_counts')
    if expected is not None and counts != expected:
        issues.append(f'Texture counts differ from profile: got {counts}, expected {expected}')
    return {'folder': str(folder), 'blk': blks[0].name, 'texture_count': len(rows), 'role_counts': counts,
            'textures': rows, 'issues': issues, 'notes': notes, 'passed': not issues}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--materials', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--profile', type=Path)
    args = parser.parse_args()
    result = inspect(args.folder, args.materials, args.manifest, args.profile)
    if args.out:
        with ArtifactTransaction([args.out], [args.folder], label='skin-inspection') as transaction:
            write_json(transaction.stage(args.out), result)
            transaction.commit()
    print(json.dumps({key: result[key] for key in ('passed', 'texture_count', 'role_counts', 'issues', 'notes')},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
