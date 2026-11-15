"""Check the intended reading direction of vector_paint text on a rendered aircraft."""
import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

import chart_diagnostics as charts
import surface_preview as surface
import vector_paint as paint
from artifact_io import ArtifactTransaction
from uv_ownership import surface_owners


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def bound_sidecar(receipt_path, stored_path, sibling_name, digest):
    for path in (receipt_path.with_name(sibling_name), receipt_path.parent / stored_path):
        if path.is_file() and surface.sha256_file(path) == digest:
            return path.resolve()
    raise ValueError(f'{receipt_path}: no matching {sibling_name} ({digest})')


def load_view(path, geometry):
    meta = read_json(path)
    if meta.get('schema_version') != 2 or meta.get('geometry_sha256') != geometry['_sha256']:
        raise ValueError(f'{path}: missing or mismatched geometry binding')
    fingerprint = surface.camera_fingerprint(meta)
    if fingerprint != meta.get('camera_sha256'):
        raise ValueError(f'{path}: camera fingerprint does not match')
    image = bound_sidecar(path, meta['image'], path.stem + '.png', meta['image_sha256'])
    sidecar = bound_sidecar(path, meta['depth_file'], path.stem + '-depth.npz', meta['depth_sha256'])
    raw = sidecar.read_bytes()
    if hashlib.sha256(raw).hexdigest() != meta['depth_sha256']:
        raise ValueError(f'{sidecar}: changed during inspection')
    surface._check_npz_size(io.BytesIO(raw))
    basis, center, scale, width, height = surface.validate_camera(meta)
    world = geometry['triangles']
    with np.load(io.BytesIO(raw), allow_pickle=False) as data:
        if str(data['geometry_sha256']) != geometry['_sha256'] or str(data['camera_sha256']) != fingerprint:
            raise ValueError(f'{sidecar}: geometry or camera inside archive does not match')
        depth, owners = surface.validate_visibility(data['depth'], data['owners'], len(world), (height, width))
    screen = world.astype(np.float64) @ basis.T
    screen[:, :, :2] = (screen[:, :, :2] - center) * [scale, -scale] + [width*.5, height*.5]
    return screen, depth, owners, dict(receipt=str(path), image=str(image), depth=str(sidecar),
                                      image_sha256=meta['image_sha256'], camera_sha256=fingerprint,
                                      depth_sha256=meta['depth_sha256'])


def coordinates(geometry, ids, axes, frame, size):
    if frame[0]:
        uv = geometry['uvs'][ids].astype(np.float64)
        pixels = np.stack([uv[:, :, 0]*(size[0]-1), (1-uv[:, :, 1])*(size[1]-1)], axis=2)
        return (pixels-frame[1:3]) @ frame[3:].reshape(2, 2).T, np.zeros((len(ids), 2), bool)
    xyz = geometry['triangles'][ids]
    result = xyz[:, :, [axes[0], axes[2]]].astype(np.float64)
    folded = np.zeros((len(ids), 2), bool)
    for index, sign in enumerate([axes[1], axes[3]]):
        if sign == 1:
            result[:, :, index] *= -1
        elif sign == 2:
            v = result[:, :, index]
            folded[:, index] = (v.min(axis=1) < 0) & (v.max(axis=1) > 0)
            result[:, :, index] = np.abs(v)
    return result, folded


def axis_status(baseline, head, expected, tolerance):
    length = np.linalg.norm(baseline) * np.linalg.norm(head)
    if not np.isfinite(length) or length < 1e-12:
        return 'undetermined', None, None
    cross = (baseline[0]*head[1] - baseline[1]*head[0]) / length
    direction = math.degrees(math.atan2(baseline[1], baseline[0]))
    head_angle = math.degrees(math.atan2(head[1], head[0]))
    error = abs((direction - expected + 180) % 360 - 180)
    if abs(cross) < .12:
        status = 'undetermined'
    elif cross > 0:  # Screen y points down: upright glyph coordinates change handedness.
        status = 'mirrored'
    elif error <= tolerance:
        status = 'pass'
    elif 180 - error <= tolerance:
        status = 'upside_down'
    else:
        status = 'off_axis'
    return status, direction, head_angle


def classify(shape, ids, coords, folded, view, expected, tolerance, uvs, atlas_owner=None, protect=None):
    screen, depth, owners, _ = view
    height, width = owners.shape
    im, corners = shape.image, np.asarray(shape[3])
    c, s = math.cos(im['angle']), math.sin(im['angle'])
    # Rows point to the right edge and to the top of the source glyph respectively.
    chart_axes = np.array([[c, s], [-s, c]]) * np.array([[-1 if im['flip'] else 1], [1]])
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    upper = coords.max(axis=1)
    lower = coords.min(axis=1)
    for i, sign in enumerate(folded.T):
        lower[sign, i] = 0
    candidates = np.flatnonzero(((upper >= lo) & (lower <= hi)).all(axis=1))
    votes, rejected = Counter(), Counter()
    axis_vectors = np.zeros((2, 2))
    visible_box = np.array([width, height, -1, -1])
    low_ink, high_ink = np.full(2, np.inf), np.full(2, -np.inf)
    carriers = set()
    off_frame, intersects_surface = 0, 0
    for i in candidates:
        tri = ids[i]
        if np.any(folded[i]):
            rejected['world_axis_fold'] += 1
            continue
        uv, p = coords[i], screen[tri]
        uv_edges, edges = uv[1:] - uv[0], p[1:, :2] - p[0, :2]
        if abs(np.linalg.det(uv_edges)) < 1e-12:
            continue
        # The triangle and glyph rectangle may overlap in their axis-aligned boxes only.
        normals = np.diff(uv[[0, 1, 2, 0]], axis=0)[:, ::-1] * [-1, 1]
        normals = np.vstack([normals, chart_axes])
        triangle_span, glyph_span = uv @ normals.T, corners @ normals.T
        if np.any((triangle_span.min(0) > glyph_span.max(0)) | (glyph_span.min(0) > triangle_span.max(0))):
            continue
        intersects_surface += 1
        if abs(np.linalg.det(edges)) < 1e-9:
            continue
        forward = np.linalg.solve(uv_edges, edges)
        glyph_corners = (corners - uv[0]) @ forward + p[0, :2]
        low = np.maximum(np.floor(glyph_corners.min(0)), np.floor(p[:, :2].min(0))).astype(int)
        high = np.minimum(np.ceil(glyph_corners.max(0)), np.ceil(p[:, :2].max(0))).astype(int)
        low = np.maximum(low, 0)
        high = np.minimum(high, [width-1, height-1])
        if np.any(low > high):
            off_frame += 1
            continue
        yy, xx = np.mgrid[low[1]:high[1]+1, low[0]:high[0]+1]
        xy = np.stack([xx+.5, yy+.5], axis=-1)
        bary = (xy - p[0, :2]) @ np.linalg.inv(edges)
        intersects = (bary.min(axis=2) >= -1e-4) & (bary.sum(axis=2) <= 1.0001)
        if not intersects.any():
            continue
        q = bary @ uv_edges + uv[0]
        ink = intersects & charts.footprint_mask(shape, q[:, :, 0], q[:, :, 1])
        if not ink.any():
            continue
        on_surface = owners[yy, xx] == tri
        visible = ink & on_surface
        if visible.any() and (atlas_owner is not None or protect is not None):
            # The scene sampler interpolates four texels. Require every contributing
            # texel to belong to this surface (and be paintable) before voting.
            uv3 = uvs[tri].astype(np.float64)
            native = uv3[0] + bary[visible] @ (uv3[1:] - uv3[0])
            ah, aw = (atlas_owner if atlas_owner is not None else protect).shape
            fx = np.clip(native[:, 0] * (aw-1), 0, aw-1)
            fy = np.clip((1-native[:, 1]) * (ah-1), 0, ah-1)
            ix, iy = fx.astype(int), fy.astype(int)
            safe = np.ones(len(ix), bool)
            for dx, dy in [(0,0), (1,0), (0,1), (1,1)]:
                used = ((fx-ix if dx else 1-(fx-ix)) * (fy-iy if dy else 1-(fy-iy))) > 1e-8
                ax, ay = np.minimum(ix+dx, aw-1), np.minimum(iy+dy, ah-1)
                if atlas_owner is not None:
                    safe &= ~used | (atlas_owner[ay, ax] == tri)
                if protect is not None:
                    safe &= ~used | ~protect[ay, ax]
            rejected['unverified_atlas_ink_samples'] += int((~safe).sum())
            visible[visible] = safe
        occluded = ink & ~on_surface & (depth[yy, xx] > p[0, 2] + bary @ (p[1:, 2] - p[0, 2]) + 1e-4)
        rejected['occluded_ink_samples'] += int(occluded.sum())
        rejected['unowned_ink_samples'] += int((ink & ~on_surface & ~occluded).sum())
        count = int(visible.sum())
        if not count:
            continue
        carriers.add(int(tri))
        baseline, head = chart_axes @ forward
        status, _, _ = axis_status(baseline, head, expected, tolerance)
        votes[status] += count
        axis_vectors += count * np.stack([baseline / np.linalg.norm(baseline), head / np.linalg.norm(head)])
        xs, ys = xx[visible], yy[visible]
        visible_box[:2] = np.minimum(visible_box[:2], [xs.min(), ys.min()])
        visible_box[2:] = np.maximum(visible_box[2:], [xs.max(), ys.max()])
        glyph = ((q[visible] - im['center']) @ chart_axes.T) / im['size']
        low_ink = np.minimum(low_ink, glyph.min(axis=0))
        high_ink = np.maximum(high_ink, glyph.max(axis=0))
    total = sum(votes.values())
    hidden = rejected['occluded_ink_samples']
    span = high_ink-low_ink if total else np.zeros(2)
    if not total:
        status = 'occluded' if hidden else ('out_of_frame' if intersects_surface and off_frame == intersects_surface and not rejected['world_axis_fold'] else 'undetermined')
    elif total < 5 or span[0] < .40 or span[1] < .15 or rejected['world_axis_fold']:
        status = 'undetermined'
    elif sorted(votes.values(), reverse=True)[0] != total:
        status = 'undetermined'
    else:
        status = votes.most_common(1)[0][0]
    angle = lambda vec: round(math.degrees(math.atan2(vec[1], vec[0])), 2) if np.linalg.norm(vec) > 1e-8 else None
    return dict(status=status, baseline_deg=angle(axis_vectors[0]), head_deg=angle(axis_vectors[1]),
                visible_ink_pixels=total, visible_triangles=len(carriers), orientation_votes=dict(votes),
                visibility=('partially_occluded' if hidden and total else 'occluded' if hidden else 'visible' if total else 'unverified'),
                baseline_span_fraction=round(float(span[0]), 3), head_span_fraction=round(float(span[1]), 3),
                visible_box_xyxy=visible_box.tolist() if total else None, **dict(rejected))


def run(design_path, geo_path, plan_path, out, paint_receipt=None, protect_path=None):
    plan = read_json(plan_path)
    checks = plan.get('checks')
    if not isinstance(checks, list) or not checks:
        raise ValueError('plan.checks must be a nonempty list')
    design, palette, _ = paint.load_design(design_path)
    geometry = surface.load_geometry(geo_path, allow_repeat_uv=True)
    geo_sha, design_sha = geometry['_sha256'], surface.sha256_file(design_path)
    placement_stats = {}
    if paint_receipt:
        baked = read_json(paint_receipt)
        if not {geo_sha, design_sha} <= set(baked['inputs'].values()):
            raise ValueError('Paint receipt does not bind this design and geometry')
        placement_stats = {item['id']: item for item in baked['images']}
    atlas = design['atlas']
    size = (int(atlas['width']), int(atlas['height']))
    if not all(16 <= v <= paint.MAX_ATLAS for v in size):
        raise ValueError('Invalid design atlas dimensions')
    assignment, axes, facing, _, _ = paint.select_charts(design, geometry, size)
    raster_size = size
    proof = baked.get('proof') if paint_receipt else None
    if paint_receipt:
        raster_size = (int(baked['atlas']['width']), int(baked['atlas']['height']))
        if raster_size != size:
            if not proof or tuple(proof['native_atlas']) != size or paint.proof_size(size, raster_size[0]) != raster_size:
                raise ValueError('Bake dimensions are not a verified reduced proof of this native design')
            if proof['assignment_sha256'] != hashlib.sha256(assignment.astype('<i4', copy=False)).hexdigest():
                raise ValueError('Reduced proof assigned different geometry triangles')
    protect = None
    if protect_path:
        if paint_receipt and surface.sha256_file(protect_path) not in baked['inputs'].values():
            raise ValueError('Paint receipt does not bind this protection mask')
        with Image.open(protect_path) as mask:
            if mask.size != size:
                raise ValueError('The bake protection mask must match the design atlas dimensions')
            protect = np.asarray(mask.convert('L')) != 0
        if raster_size != size:
            protect = paint.proof_protection(protect, raster_size)
    atlas_owner = None
    frames = paint.chart_frames(design)
    names = [ch['id'] for ch in design['charts']]
    requested = {r['item'] for r in checks}
    # Avoid loading unrelated character artwork or fonts from other placements.
    groups = [dict(name=layer['name'], images=[v for v in layer.get('images', []) if
                   v.get('id') in requested and 'text' in v]) for layer in design['layers']]
    selected = dict(design, layers=[g for g in groups if g['images']], inspection_regions=[])
    shapes = charts.footprints(selected, set(names), design_path.parent)
    shapes_by_id = {shape[0]: shape for shape in shapes}
    if len(shapes_by_id) != len(shapes) or requested != set(shapes_by_id):
        raise ValueError(f'Checks must identify unique text placements; missing: {sorted(requested - set(shapes_by_id))}')
    nodes = geometry['names'][geometry['node_ids']].astype(str)
    views, view_meta, reports, cached = {}, {}, [], {}
    inputs = [design_path, geo_path, plan_path] + [p for p in (paint_receipt, protect_path) if p]
    for check in checks:
        label, name = check['item'], check['view']
        if not set(check) <= {'item', 'view', 'baseline_deg', 'tolerance_deg', 'nodes'}:
            raise ValueError(f'{label}: unknown check fields')
        expected = float(check['baseline_deg'])
        tolerance = float(check.get('tolerance_deg', 55))
        if not math.isfinite(expected) or not 0 < tolerance < 90:
            raise ValueError(f'{label}: expected a finite screen angle and tolerance in (0,90)')
        if name not in views:
            path = (plan_path.parent / plan['views'][name]).resolve(strict=True)
            views[name] = load_view(path, geometry)
            view_meta[name] = views[name][3]
            inputs.extend([path, Path(view_meta[name]['image']), Path(view_meta[name]['depth'])])
        shape = shapes_by_id[label]
        index = names.index(shape[1])
        selected_nodes = check.get('nodes')
        if selected_nodes is not None and (not isinstance(selected_nodes, list) or not selected_nodes or
                any(not isinstance(n, str) or n not in geometry['names'] for n in selected_nodes)):
            raise ValueError(f'{label}: nodes must be known, exact receiver node names')
        key = (index, tuple(selected_nodes or []))
        if key not in cached:
            mask = assignment == index
            if selected_nodes:
                mask &= np.isin(nodes, selected_nodes)
            ids = np.flatnonzero(mask)
            cached[key] = (ids, *coordinates(geometry, ids, axes[index], frames[index], size))
        stats = placement_stats.get(label, {})
        needs_owner = not paint_receipt or bool(stats.get('nonowner_samples'))
        if needs_owner and atlas_owner is None:
            atlas_owner = surface_owners(geometry['uvs'].astype(np.float64), assignment, facing, *raster_size)
            if proof and proof['owner_atlas_sha256'] != hashlib.sha256(atlas_owner.astype('<i4', copy=False)).hexdigest():
                raise ValueError('Reduced proof UV ownership does not match its bake receipt')
        result = classify(shape, *cached[key], views[name], expected, tolerance, geometry['uvs'],
                          atlas_owner if needs_owner else None, protect)
        if paint_receipt:
            result['bake_samples'] = {k: stats.get(k) for k in ['sample_hits', 'nonowner_samples', 'protected_samples']}
            if not stats or (stats.get('protected_samples') and protect is None):
                result['geometry_only_status'], result['status'] = result['status'], 'undetermined'
                result['coverage'] = 'missing_bake_record' if not stats else 'partial_needs_protect_mask'
            elif not stats.get('sample_hits'):
                result['geometry_only_status'], result['status'] = result['status'], 'not_painted'
                result['coverage'] = 'zero_bake_hits'
            else:
                result['coverage'] = 'partial' if stats.get('nonowner_samples') or stats.get('protected_samples') else 'no_reported_loss'
        else:
            result['coverage'] = 'no_bake_receipt'
        reports.append(dict(item=label, chart=shape[1], view=name, target_baseline_deg=expected,
                            tolerance_deg=tolerance, **result))
    report = dict(schema_version=1, tool='check_lettering.py', design_sha256=design_sha, geometry_sha256=geo_sha,
                  paint_receipt_sha256=surface.sha256_file(paint_receipt) if paint_receipt else None,
                  native_atlas=list(size), inspected_raster=list(raster_size),
                  views=view_meta, checks=reports, counts=dict(Counter(r['status'] for r in reports)),
                  scope='Predicted glyph axes on camera-visible assigned triangles. Inspect the bound image for actual final pixels, spelling, size and readability.')
    with ArtifactTransaction([out], inputs=inputs, label='lettering-review') as tx:
        tx.stage(out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        tx.commit()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('design', 'geometry', 'plan', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--paint-receipt', type=Path)
    parser.add_argument('--protect', type=Path, help='Exact native bake protection mask when the bake reports protected samples')
    parser.add_argument('--require-pass', action='store_true')
    args = parser.parse_args()
    result = run(args.design.resolve(), args.geometry.resolve(), args.plan.resolve(), args.out.resolve(), args.paint_receipt, args.protect)
    print(json.dumps(result['counts']))
    return int(args.require_pass and any(r['status'] != 'pass' for r in result['checks']))


if __name__ == '__main__':
    raise SystemExit(main())
