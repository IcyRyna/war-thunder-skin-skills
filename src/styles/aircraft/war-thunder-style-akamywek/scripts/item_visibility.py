"""Measure a design item's RGB contribution on the front-most surfaces of one saved layout camera.

Bake the original design and one copy with just that item removed. Sample their finished
colours using the camera's recorded triangle owners, UV addressing and bilinear filtering.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

import vector_paint as paint
from artifact_io import ArtifactTransaction
from scene_preview import file_hash
from surface_preview import camera_fingerprint, load_geometry, validate_camera, validate_visibility


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def check_file(path, digest):
    if file_hash(path) != digest:
        raise ValueError(f'Input differs from the recorded SHA-256: {path}')


def image_rgb(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB'))


def registered_view(view, geometry, material):
    meta = read(view)
    if meta.get('mode') != 'layout':
        raise ValueError('Only scene_preview layout views have unlit RGB suitable for this check')
    basis, center, scale, width, height = validate_camera(meta)
    if camera_fingerprint(meta) != meta['camera_sha256'] or meta['geometry_sha256'] != geometry['_sha256']:
        raise ValueError('Wrong geometry or camera fingerprint')
    # Sibling files also work after an evidence directory is moved intact.
    scene_path = view.parent / Path(meta['scene']).name
    if not scene_path.is_file():
        scene_path = Path(meta['scene'])
    png = view.parent / Path(meta['image']).name
    depths = view.parent / Path(meta['depth_file']).name
    for path, key in ((scene_path, 'scene_sha256'), (png, 'image_sha256'), (depths, 'depth_sha256')):
        check_file(path, meta[key])
    scene = read(scene_path)
    names = geometry['material_names'].tolist()
    materials = sorted(scene['materials'], key=lambda m: m['id'])
    if ([m['id'] for m in materials] != list(range(len(names))) or
            [m['name'] for m in materials] != names or meta['material_names'] != names or material not in names):
        raise ValueError('Material names/IDs do not identify this geometry')
    color = materials[names.index(material)].get('color')
    if not color:
        raise ValueError('Selected material has no colour texture bound by the camera receipt')
    # Different material resources can initially contain identical images.
    # Editing one cannot affect the other: bind the file identity as well as its bytes.
    scene_root = Path(meta['scene']).parent
    def texture_key(record):
        if not record:
            return None
        return (scene_root / record['path']).resolve(), record['sha256']
    key = texture_key(color)
    if key not in {(Path(e['path']).resolve(), e['sha256']) for e in meta['source_inputs']}:
        raise ValueError('Colour binding disagrees with the camera receipt')
    bound = np.array([texture_key(m.get('color')) == key for m in materials])
    repeats = np.array([m.get('uv_mode', 'unit') == 'repeat' for m in materials])
    actual = image_rgb(png)
    if actual.shape[:2] != (height, width):
        raise ValueError('Saved render differs from camera dimensions')
    with np.load(depths, allow_pickle=False) as data:
        if str(data['geometry_sha256']) != geometry['_sha256'] or str(data['camera_sha256']) != meta['camera_sha256']:
            raise ValueError('Foreign camera depth/owners')
        _, owners = validate_visibility(data['depth'], data['owners'], len(geometry['triangles']), (height, width))
    yy, xx = np.where((owners >= 0) & bound[geometry['material_ids'][np.maximum(owners, 0)]])
    tri = owners[yy, xx]
    screen = geometry['triangles'] @ basis.T
    screen[:, :, 0] = (screen[:, :, 0] - center[0]) * scale + width * .5
    screen[:, :, 1] = (center[1] - screen[:, :, 1]) * scale + height * .5
    # Same barycentric pixel centre as scene_preview.draw. Only visible material samples
    # are needed, and those samples can be reused across all requested design items.
    points = np.moveaxis(screen[tri, :, :2].astype(np.float64), 1, 0)
    (ax, ay), (bx, by), (cx, cy) = [p.T for p in points]
    den = (by-cy)*(ax-cx) + (cx-bx)*(ay-cy)
    if (abs(den) < 1e-12).any():
        raise ValueError('Degenerate front-most triangle')
    sx, sy = xx + .5 - cx, yy + .5 - cy
    a = ((by-cy)*sx + (cx-bx)*sy) / den
    b = ((cy-ay)*sx + (ax-cx)*sy) / den
    vert = geometry['uvs'][tri]
    uv = a[:, None]*vert[:, 0] + b[:, None]*vert[:, 1] + (1-a-b)[:, None]*vert[:, 2]
    repeat = repeats[geometry['material_ids'][tri]]
    uv[repeat] %= 1
    companions = {str(p.resolve()): meta[key] for p, key in
                  ((scene_path,'scene_sha256'), (png,'image_sha256'), (depths,'depth_sha256'))}
    return xx, yy, tri, uv.clip(0, 1), actual[yy, xx], meta, color['sha256'], companions, bound


def sample(atlas, uv):
    """scene_preview's bilinear layout RGB, including the 8-bit display conversion."""
    h, w = atlas.shape[:2]
    x, y = uv[:, 0] * (w-1), (1-uv[:, 1]) * (h-1)
    x0, y0 = x.astype(int), y.astype(int)
    x1, y1 = np.minimum(x0+1, w-1), np.minimum(y0+1, h-1)
    dx, dy = (x-x0)[:, None], (y-y0)[:, None]
    values = ((atlas[y0,x0]*(1-dx) + atlas[y0,x1]*dx)*(1-dy)
              + (atlas[y1,x0]*(1-dx) + atlas[y1,x1]*dx)*dy)
    return ((values / 255.) * 255.).clip(0,255).astype(np.uint8)


def summary(full, without, owner_chart, target_chart, xx, yy, recorded):
    delta = abs(full.astype(np.int16) - without).max(axis=1)
    baseline = abs(full.astype(np.int16) - recorded).max(axis=1)
    changed = delta > 0
    own = changed & (owner_chart == target_chart)
    def region(mask):
        if not mask.any():
            return dict(pixels=0, max_rgb_delta=0, rows=0, box_xyxy_inclusive=None)
        return dict(pixels=int(mask.sum()), max_rgb_delta=int(delta[mask].max()),
                    rows=len(np.unique(yy[mask])), box_xyxy_inclusive=[int(xx[mask].min()), int(yy[mask].min()),
                    int(xx[mask].max()), int(yy[mask].max())])
    return dict(on_carrier=region(own), other_shared_surface=region(changed & ~own),
                changed_pixels=int(changed.sum()), delta_over_one_level=int((delta > 1).sum()),
                full_proof_differs_from_saved_gt1_on_changed=int((changed & (baseline > 1)).sum()))


def classify(hits, atlas_changed, result):
    if not hits:
        return 'no_paint_hits'
    if not atlas_changed:
        return 'no_composite_rgb_difference'
    own = result['on_carrier']
    if not own['pixels']:
        return 'only_other_surface' if result['changed_pixels'] else 'no_screen_difference'
    if own['pixels'] == 1 or own['max_rgb_delta'] <= 1:
        return 'trace_only'
    return 'visible_rgb_difference'


def without_item(design, layer, key, index):
    result = copy.deepcopy(design)
    group = result['layers'][layer]
    del group[key][index]
    if not group[key]:
        del group[key]
    if not group.get('images') and not group.get('items'):
        del result['layers'][layer]
    return result


def inspect(args):
    design_path = args.design.resolve()
    design = read(design_path)
    external = []
    for layer in design['layers']:
        for row in layer.get('images', []):
            if 'source' in row:
                row['source'] = str((design_path.parent / row['source']).resolve(strict=True))
                external.append(Path(row['source']))
            elif 'text' in row:
                row['font'] = str(paint.resolve_font(row.get('font'), design_path.parent).resolve(strict=True))
                external.append(Path(row['font']))
    inputs = [design_path, args.geometry, args.view, args.base, *external]
    if args.protect:
        inputs.append(args.protect)
    hashes = {str(p.resolve()): file_hash(p) for p in set(inputs)}
    geometry = load_geometry(args.geometry, allow_repeat_uv=True)
    xx, yy, tri, uv, actual, meta, color_hash, companions, bound = registered_view(args.view, geometry, args.material)
    hashes.update(companions)
    with Image.open(args.base) as im:
        native = im.size
    width = args.width
    if width is None:
        # Choose an exactly proportional proof, e.g. a non-square atlas may not admit 1536.
        step = native[0] // math.gcd(*native)
        width = min(native[0], 1536) // step * step
        if width < 16 or native[1] * width // native[0] < 16:
            width = native[0]
    size = paint.proof_size(native, width) if width != native[0] else native
    assignments = paint.select_charts(design, geometry, native)[0]
    charts = [c['id'] for c in design['charts']]
    items = {}
    for li, layer in enumerate(design['layers']):
        for key in ('items','images'):
            for i, row in enumerate(layer.get(key, [])):
                if row.get('id') in args.item:
                    items.setdefault(row['id'], []).append((li,key,i,row['chart']))
    if any(len(items.get(n, [])) != 1 for n in args.item):
        raise ValueError('Each requested ID must occur exactly once in this design')
    atlas_charts = set(assignments[bound[geometry['material_ids']]].tolist())
    for name, locations in items.items():
        chart = locations[0][3]
        if charts.index(chart) not in atlas_charts:
            raise ValueError(f'{name}: chart {chart!r} has no carrier triangles on the selected colour resource')
    report = dict(method='original vs one item omitted, bilinear unlit RGB on recorded front-most triangles',
                  inputs=hashes, atlas_dimensions=list(size), native_dimensions=list(native), material=args.material,
                  registered_colour_sha256=color_hash, camera_sha256=meta['camera_sha256'], image_sha256=meta['image_sha256'],
                  depth_sha256=meta['depth_sha256'], scene_sha256=meta['scene_sha256'], sampled_pixels=len(xx), items={},
                  limits='This is a layout-camera check at the stated atlas resolution. Same-colour or covered art may make no RGB difference. A single pixel or one RGB level is only a trace. Inspect full-size DDS and game filtering separately.')
    def bake(directory, data):
        if not data['layers']:
            with Image.open(args.base) as image:
                rgb = image.convert('RGB')
                return np.asarray(rgb.resize(size, Image.Resampling.BOX) if rgb.size != size else rgb), {}
        ds = directory/'design.json'
        ds.parent.mkdir()
        ds.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        out = directory/'paint'
        receipt = paint.run(argparse.Namespace(geometry=args.geometry, design=ds, base=args.base, protect=args.protect,
                            out=out, proof_width=width if width != native[0] else None))
        return image_rgb(out/'composite.png'), receipt
    with tempfile.TemporaryDirectory(prefix='akamywek-item-view-') as tmp:
        original, receipt = bake(Path(tmp)/'full', design)
        full = sample(original, uv)
        report['full_proof_differs_from_saved_gt1'] = int((abs(full.astype(np.int16)-actual).max(axis=1)>1).sum())
        report['comparison_scope'] = ('no_material_on_camera' if not len(xx) else
                'reconstructed_proof_only' if report['full_proof_differs_from_saved_gt1'] else
                'reconstructed_rgb_matches_saved_view_within_one_level')
        hits = {row['id']:row['sample_hits'] for row in receipt['items'] + receipt['images']}
        for seq, name in enumerate(dict.fromkeys(args.item)):
            layer, key, index, chart = items[name][0]
            without, _ = bake(Path(tmp)/str(seq), without_item(design, layer, key, index))
            atlas_changed = sum(int(np.any(original[y:y+128]!=without[y:y+128],axis=2).sum())
                                for y in range(0,len(original),128))
            result = summary(full, sample(without, uv), assignments[tri], charts.index(chart), xx, yy, actual)
            status = classify(hits.get(name, 0), atlas_changed, result)
            report['items'][name] = dict(chart=chart, status=status, paint_sample_hits=hits.get(name,0),
                                         changed_atlas_texels=atlas_changed, **result)
    for path, digest in hashes.items():
        check_file(Path(path), digest)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('design','geometry','base','view','out'):
        ap.add_argument('--'+name, type=Path, required=True)
    ap.add_argument('--protect',type=Path,help='Use exactly the protection mask of the production bake')
    ap.add_argument('--material',required=True,help='Scene material bound to this colour atlas')
    ap.add_argument('--item',action='append',required=True,help='Exact unique design item ID; repeat for a few suspects')
    ap.add_argument('--width',type=int,help='Proof atlas width; default native or <=1536; use native width for final bake')
    args = ap.parse_args(argv)
    try:
        if args.out.exists():
            raise FileExistsError(args.out)
        report = inspect(args)
        with ArtifactTransaction([args.out],inputs=list(map(Path,report['inputs'])),label='item-visibility') as tx:
            tx.stage(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            tx.commit()
        return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:
        ap.exit(2, f'uninspected: {exc}\n')


if __name__ == '__main__':
    main()
