"""Export a material-aware, original-coordinate UV guide for a layered editor.

The PNG is a diagnostic unit-tile guide, never a new UV unwrap or game channel.
"""
from pathlib import Path
import argparse
import fnmatch
import hashlib
import json
import numpy as np
from PIL import Image, ImageDraw


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(geometry, base, out, materials, nodes=None):
    geometry, base, out = Path(geometry).resolve(), Path(base).resolve(), Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new/empty review directory')
    if out in geometry.parents or out in base.parents:
        raise ValueError('Review output must not contain its inputs')
    fingerprints = {str(p): sha(p) for p in [geometry, base]}
    with np.load(geometry, allow_pickle=False) as data:
        uv = np.asarray(data['uvs'], dtype=np.float64)
        ids, names = data['node_ids'], data['names'].astype(str)
        mids, mnames = data['material_ids'], data['material_names'].astype(str)
    if uv.ndim != 3 or uv.shape[1:] != (3, 2) or not np.isfinite(uv).all():
        raise ValueError('UVs must be finite (N,3,2)')
    if ids.shape != (len(uv),) or mids.shape != (len(uv),) or np.any(ids < 0) or np.any(ids >= len(names)) or np.any(mids < 0) or np.any(mids >= len(mnames)):
        raise ValueError('Invalid node/material indexing')
    chosen_materials = [i for i, n in enumerate(mnames) if any(fnmatch.fnmatchcase(n, p) for p in materials)]
    selected = np.isin(mids, chosen_materials)
    if nodes:
        selected &= np.asarray([any(fnmatch.fnmatchcase(n, p) for p in nodes) for n in names[ids]])
    if not selected.any():
        raise ValueError('Material/node selection is empty')
    with Image.open(base) as image:
        colour = image.convert('RGBA')
    w, h = colour.size
    if not 16 <= w <= 8192 or not 16 <= h <= 8192:
        raise ValueError('Review image dimensions must be within 16..8192')
    wire = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    carrier = Image.new('L', (w, h), 0)
    wd, cd = ImageDraw.Draw(wire), ImageDraw.Draw(carrier)
    outside = []
    for i in np.flatnonzero(selected):
        u = uv[i]
        if np.any((u < 0) | (u > 1)):
            outside.append(int(i))
        points = [(float(x * (w - 1)), float((1 - y) * (h - 1))) for x, y in u]
        wd.line(points + [points[0]], fill=(0, 220, 255, 220), width=1)
        cd.polygon(points, fill=255)
    out.mkdir(parents=True, exist_ok=True)
    outputs = {'base': out / 'base-colour.png', 'wire': out / 'UV_GUIDE_HIDE_FOR_EXPORT.png', 'carrier': out / 'selected-carrier.png'}
    colour.save(outputs['base']); wire.save(outputs['wire']); carrier.save(outputs['carrier'])
    preview_base = colour.copy(); preview_base.putalpha(255)
    preview = Image.alpha_composite(preview_base, wire)
    preview.thumbnail((1100, 1100)); preview.convert('RGB').save(out / 'uv-review-preview.jpg', quality=92)
    record = {'inputs': fingerprints, 'atlas_size': [w, h], 'selected_triangles': int(selected.sum()),
              'material_names': mnames[chosen_materials].tolist(), 'node_names': sorted(set(names[ids[selected]])),
              'out_of_tile_triangles': outside, 'coordinate_convention': 'x=u*(W-1), y=(1-v)*(H-1); original UV values unchanged',
              'scope': 'Unit-tile guide clipped only by the diagnostic canvas. Out-of-tile source coordinates are not clamped or wrapped; inspect them in Blender before assuming full coverage.',
              'outputs': {k: {'path': str(p), 'sha256': sha(p)} for k, p in outputs.items()},
              'source_files_unchanged': all(sha(Path(p)) == v for p, v in fingerprints.items())}
    if not record['source_files_unchanged']:
        raise ValueError('Input changed while exporting guide')
    (out / 'receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--geometry', type=Path, required=True)
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--material', action='append', required=True, help='Exact material name or explicit glob; repeatable')
    p.add_argument('--node', action='append', help='Optional node name/glob; repeatable')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    r = export(a.geometry, a.base, a.out, a.material, a.node)
    print(json.dumps({k: r[k] for k in ['atlas_size', 'selected_triangles', 'material_names', 'source_files_unchanged']}))
