"""Surface maps for a vector_paint design: where each chart can safely carry lines.

For every chart of a design JSON, the selected triangles are drawn in the chart's
own metre coordinates and classed as flat (projection keeps >= 80% of the area),
curving (50-80%), steep (< 50%: widths and patterns streak there), protected
(mechanical texels from --protect), lost (the original UV shares the texel
with an earlier chart, and the earlier chart wins it, as in vector_paint) or
hidden (inner faces covered by the skin, canopy or another chart's surface).  Seams
(a narrow sliver between two parts of this chart that this chart does not paint, such
as the side wall of a raised dorsal strip: another chart or nothing paints it, so it
breaks the item as a thin line in game) are drawn in magenta, and every item that
crosses one is listed under seam_items.  The
design's polygons, strokes and image/text placements are drawn on top and
scored by item type: colour fields are at risk on steep or lost ground (they
may bleed past the real edge on purpose); lines, type and portraits also when
they cross mechanical texels or run off the surface.  Use it before placing lines and type, and after moving
them; it does not replace looking at the model.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion

from artifact_io import ArtifactError, ArtifactTransaction
from inspect_skins import load_font
from surface_preview import load_geometry, rasterize
from vector_paint import parse_axis, select_charts, chart_frames
from uv_ownership import surface_owners
from chart_diagnostics import footprints as item_shapes, footprint_mask, barycentric_field, triangle_risks, chart_aliases

Image.MAX_IMAGE_PIXELS = 8192 * 8192
OFF, FLAT, CURVING, STEEP, SHARED, PROTECTED, HIDDEN = range(7)
SEAM, SHARED_WITHIN = 7, 8
NAMES = ['off-surface', 'flat', 'curving', 'steep', 'lost-to-earlier-chart', 'protected', 'hidden-under-other-surface', 'seam', 'shared-within-chart']
COLORS = [(250, 250, 250), (200, 205, 210), (236, 190, 110), (220, 80, 70), (165, 110, 210), (80, 140, 230), (70, 72, 80), (230, 0, 200), (107, 83, 147)]
SEAM_REACH = .05   # a visible sliver this chart does not paint, with its own surface this close (m) on both sides
RISKY = {'polygon': (STEEP, SHARED, SHARED_WITHIN), 'stroke': (OFF, STEEP, SHARED, SHARED_WITHIN, PROTECTED, HIDDEN),
         'focus': (OFF, STEEP, SHARED, SHARED_WITHIN, PROTECTED, HIDDEN, SEAM),
         'text': (OFF, STEEP, SHARED, SHARED_WITHIN, PROTECTED, HIDDEN), 'image': (STEEP, SHARED, SHARED_WITHIN, PROTECTED)}
# Large colour fields may tuck under wing roots or fairings; they count as at risk only when less
# than this share of them can be seen.  Images are cropped by the surface by design and are not.
MIN_VISIBLE = .35


def chart_coords(points, axes, index):
    """World points (..., 3) -> chart (u, v) using the chart's axis specs."""
    out = []
    for slot in (0, 2):
        axis, mode = axes[index, slot], axes[index, slot + 1]
        value = points[..., axis]
        out.append(np.abs(value) if mode == 2 else -value if mode == 1 else value)
    return np.stack(out, axis=-1)


def slope_classes(geometry, assignment, axes):
    world=geometry['triangles'].astype(np.float64)
    area=np.linalg.norm(np.cross(world[:,1]-world[:,0],world[:,2]-world[:,0]),axis=1)
    classes=np.full(len(world),OFF,np.uint8)
    for chart in np.unique(assignment[assignment>=0]):
        mask=assignment==chart
        uv=chart_coords(world[mask],axes,chart)
        a=uv[:,1]-uv[:,0];b=uv[:,2]-uv[:,0]
        ratio=abs(a[:,0]*b[:,1]-a[:,1]*b[:,0])/np.maximum(area[mask],1e-30)
        classes[mask]=np.where(ratio>=.8,FLAT,np.where(ratio>=.5,CURVING,STEEP))
    return classes


def classify(geometry, assignment, axes, protect, atlas=2048):
    uv=np.asarray(geometry['uvs'],np.float64)
    size=(atlas,atlas) if isinstance(atlas,int) else atlas
    if protect is not None:size=(protect.shape[1],protect.shape[0])
    owners=surface_owners(uv,assignment,np.zeros(len(uv),np.float32),*size)
    mask=np.zeros(owners.shape,np.bool_) if protect is None else protect.astype(bool)
    flags=triangle_risks(uv,assignment,owners,mask)
    classes=slope_classes(geometry,assignment,axes)
    classes[flags[:,2]]=SHARED_WITHIN;classes[flags[:,0]]=SHARED;classes[flags[:,1]]=PROTECTED
    return classes


def find_seams(wall, own, reach):
    """Visible faces outside the chart with its own surface on both sides within reach: unpainted seams."""
    seams = np.zeros(wall.shape, bool)
    for axis in (0, 1):
        before = np.zeros(wall.shape, bool)
        after = np.zeros(wall.shape, bool)
        for k in range(1, reach + 1):
            before.swapaxes(axis,0)[k:] |= own.swapaxes(axis,0)[:-k]
            after.swapaxes(axis,0)[:-k] |= own.swapaxes(axis,0)[k:]
        seams |= wall & before & after
    return seams


def render_chart(chart, index, geometry, assignment, axes, classes, shapes, scale, font, owners_atlas, protected, frame):
    world = geometry['triangles'].astype(np.float64)
    tris = np.flatnonzero(assignment == index)
    pts = chart_coords(world[tris], axes, index)
    item_pts = [np.asarray(s[3]) for s in shapes]
    bounds=list(item_pts)
    if frame[0] and bounds:
        # The map axes stay in world metres; bound frame-space artwork in the same
        # physical plane by inverting the local UV/world map of its nearest carrier.
        atlas=geometry['uvs'][tris].astype(np.float64)
        atlas[:,:,0]*=owners_atlas.shape[1]-1;atlas[:,:,1]=(1-atlas[:,:,1])*(owners_atlas.shape[0]-1)
        native=(atlas-frame[1:3])@frame[3:].reshape(2,2).T
        affine=native[:,1:]-native[:,:1]; good=np.abs(np.linalg.det(affine))>1e-12
        bounds=[]
        if good.any():
            anchors=native[good].mean(axis=1);triangles=native[good];physical=pts[good]
            for point in np.concatenate(item_pts):
                i=int(np.argmin(np.sum((anchors-point)**2,axis=1)))
                weights=np.linalg.solve((triangles[i,1:]-triangles[i,0]).T,point-triangles[i,0])
                bounds.append([physical[i,0]+weights@(physical[i,1:]-physical[i,0])])
    every=np.concatenate([pts.reshape(-1,2),*bounds]) if bounds else pts.reshape(-1,2)
    lo, hi = every.min(axis=0) - .3, every.max(axis=0) + .3
    header = 44  # legend strip above the chart
    width, height = int((hi[0] - lo[0]) * scale) + 1, int((hi[1] - lo[1]) * scale) + 1 + header
    if not 0<width<=4096 or not header<height<=4096:
        raise ValueError(f"Chart grid {width}x{height} exceeds 4096; reduce --scale")
    to_px = lambda u, v: ((u - lo[0]) * scale, header + (hi[1] - v) * scale)
    # Real visibility: rasterise the whole airframe orthographically along the chart's viewing axis
    # with the preview renderer's z-buffer, and keep the nearest front-facing triangle per pixel.
    # Inner faces that face the viewer (cockpit floors, duct walls) are then covered by the skin,
    # canopy or another chart's surface, as on the model.  A both-sides chart (abs axis) is done per
    # side so the far side never covers the near one; the pictures merge keeping the worse class.
    normal = np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0])
    used = {parse_axis(chart['u'])[0], parse_axis(chart['v'])[0]}
    depth_axis = ({0, 1, 2} - used).pop()
    centroid = world.mean(axis=1)[:, depth_axis]
    uv_all = chart_coords(world, axes, index)
    in_box = ((uv_all[:, :, 0].max(axis=1) >= lo[0]) & (uv_all[:, :, 0].min(axis=1) <= hi[0]) &
              (uv_all[:, :, 1].max(axis=1) >= lo[1]) & (uv_all[:, :, 1].min(axis=1) <= hi[1]))
    explicit_view = chart.get('_inspection_view')
    fixed = explicit_view is not None or (chart.get('facing') and parse_axis(chart['facing'])[0] == depth_axis and parse_axis(chart['facing'])[1] != 2)
    groups = [None] if fixed else sorted(set(np.sign(centroid[tris]).astype(int)) - {0}) or [None]
    rank = np.array([0, 1, 2, 4, 4, 3, 5, 6, 4])
    grid = None
    mapping = None
    for group in groups:
        mine = tris if group is None else tris[np.sign(centroid[tris]) == group]
        if not len(mine):
            continue
        view = 1. if normal[mine, depth_axis].mean() >= 0 else -1.  # viewer sits on this side
        if explicit_view is not None:
            view = -1. if explicit_view.startswith('-') else 1.
        pool = in_box if group is None else in_box & (np.sign(centroid) == group)
        pool[mine] = True
        picked = np.flatnonzero(pool)
        screen = np.empty((len(picked), 3, 3), np.float32)
        screen[:, :, 0] = (uv_all[picked, :, 0] - lo[0]) * scale
        screen[:, :, 1] = (hi[1] - uv_all[picked, :, 1]) * scale
        screen[:, :, 2] = world[picked, :, depth_axis] * view
        dummy_uv, texture = np.zeros((len(picked), 3, 2), np.float32), np.zeros((1, 1, 4), np.uint8)
        best_owners, kept, best_depth = None, -1, None
        for handedness in (1., -1.):  # keep the winding under which this chart's own faces survive culling
            _, depth, owners = rasterize(screen, world[picked].astype(np.float32), dummy_uv, texture, width, height - header, handedness)
            if explicit_view is not None:
                if best_depth is None:
                    best_depth, best_owners = depth, owners
                else:
                    nearer = depth > best_depth
                    best_owners[nearer] = owners[nearer]
                continue
            count = int(np.isin(owners, np.flatnonzero(np.isin(picked, mine))).sum())
            if count > kept:
                best_owners, kept, winding = owners, count, handedness
        owner_tri = np.where(best_owners >= 0, picked[np.maximum(best_owners, 0)], -1)
        layer = np.full(best_owners.shape, OFF, np.uint8)
        visible = owner_tri >= 0
        own = visible & (assignment[np.maximum(owner_tri, 0)] == index)
        layer[own] = classes[owner_tri[own]]
        # Get actual sample UVs, including the original chart behind an occluder.
        local_mine=np.flatnonzero(np.isin(picked,mine))
        carrier=best_owners.copy()
        carrier[~own]=-1
        if frame[0] and np.any(visible & ~own):
            def local_pass(sign):
                return rasterize(screen[local_mine],world[picked[local_mine]].astype(np.float32),
                                 dummy_uv[local_mine],texture,width,height-header,sign)[1:]
            if explicit_view is None:
                _, local = local_pass(winding)
            else:
                z_front, front = local_pass(1.)
                z_back, back = local_pass(-1.)
                local = np.where(z_back > z_front, back, front)
            valid=local>=0
            carrier[valid]=local_mine[local[valid]]
        sample=barycentric_field(screen,geometry['uvs'][picked],carrier,
                                 (owners_atlas.shape[1],owners_atlas.shape[0]))
        coords=None
        if sample is not None:
            px,py=sample
            ix=np.clip(np.rint(px[own]).astype(int),0,owners_atlas.shape[1]-1)
            iy=np.clip(np.rint(py[own]).astype(int),0,owners_atlas.shape[0]-1)
            surface=owners_atlas[iy,ix]
            sampled=layer[own].copy()
            sampled[(surface>=0)&(assignment[np.maximum(surface,0)]!=index)]=SHARED
            shared = chart_aliases(geometry['uvs'], assignment, owner_tri[own], surface, px[own], py[own],
                                   owners_atlas.shape[1], owners_atlas.shape[0])
            sampled[shared] = SHARED_WITHIN
            sampled[protected[iy,ix]]=PROTECTED
            layer[own]=sampled
            if frame[0]:
                dx=px-frame[1];dy=py-frame[2]
                coords=(dx*frame[3]+dy*frame[4], dx*frame[5]+dy*frame[6])
        layer[visible & ~own] = HIDDEN
        layer[find_seams(visible & ~own, own, max(1, int(round(SEAM_REACH * scale))))] = SEAM
        if coords is not None:
            if mapping is None:mapping=coords
            else:
                replace=rank[layer]>rank[grid]
                for a,b in zip(mapping,coords):a[replace]=b[replace]
        grid = layer if grid is None else np.where(rank[layer] > rank[grid], layer, grid)
    if grid is None:raise ValueError(f"No surface samples for {chart['id']}")
    if frame[0] and mapping is None:raise ValueError(f"No native frame carrier for {chart['id']}")
    if mapping is None:
        gy,gx=np.indices(grid.shape,dtype=np.float64)
        mapping=(lo[0]+(gx+.5)/scale,hi[1]-(gy+.5)/scale)
    grid=np.pad(grid,((header,0),(0,0)),constant_values=OFF)
    rgb = Image.fromarray(np.asarray(COLORS, np.uint8)[grid], 'RGB')
    pen = ImageDraw.Draw(rgb)
    for u in range(math.ceil(lo[0]), math.floor(hi[0]) + 1):
        pen.line([to_px(u, lo[1]), to_px(u, hi[1])], fill=(150, 170, 190) if u % 5 else (60, 110, 200))
        pen.text((to_px(u, lo[1])[0] + 2, height - 16), str(u), fill=(0, 0, 0), font=font)
    for v in np.arange(math.ceil(lo[1] * 2) / 2, hi[1], .5):
        pen.line([to_px(lo[0], v), to_px(hi[0], v)], fill=(190, 200, 215))
        pen.text((2, to_px(lo[0], v)[1] - 8), f'{v:g}', fill=(0, 0, 0), font=font)
    scores = []
    for shape in shapes:
        label, _, kind, poly = shape
        mask=footprint_mask(shape,*mapping)
        # The outline is sampled from effective alpha, clip and any cut-outs.
        rim=mask & ~binary_erosion(mask)
        outline=Image.fromarray((rim*255).astype(np.uint8))
        rgb.paste((20,20,20),(0,header,width,height),outline)
        inside = grid[header:][mask]
        if not inside.size:
            if kind == 'focus':
                scores.append(dict(id=label,kind=kind,footprint_pixels=0,seam_pixels=0,
                                   risky_share=1.,ground={},seam_length_m=0.,
                                   review='No effective samples in focus box. Check alpha, clip and map scale.'))
            continue
        counts = {NAMES[c]: round(float((inside == c).mean()), 3) for c in range(len(NAMES)) if (inside == c).any()}
        risk = float(np.isin(inside, RISKY[kind]).mean())
        seam_px = int((inside == SEAM).sum())
        visible = float(np.isin(inside, (FLAT, CURVING, PROTECTED)).mean())
        if kind == 'polygon' and visible < MIN_VISIBLE:
            risk = max(risk, 1 - visible)
        # Preserve the historical pixel-count indicator for old reports. Its units
        # depend on strip width; physical area is the invariant measurement.
        scores.append(dict(id=label, kind=kind, footprint_pixels=int(inside.size), seam_pixels=seam_px,
                           seam_area_m2=seam_px/scale**2, risky_share=round(risk,3),ground=counts,
                           seam_length_m=round(seam_px/scale,2)))
    pen.text((6, 4), f'chart {chart["id"]}  u={chart["u"]} v={chart["v"]}  (metres)', fill=(0, 0, 0), font=font)
    x = 6
    for name, color in zip(NAMES, COLORS):
        pen.rectangle([x, 22, x + 14, 36], fill=color, outline=(0, 0, 0))
        pen.text((x + 18, 22), name, fill=(0, 0, 0), font=font)
        x += 34 + int(pen.textlength(name, font=font))
    totals = {NAMES[c]: round(float((grid == c).sum() / max(1, (grid != OFF).sum())), 3) for c in range(1, len(NAMES))}
    return rgb, scores, totals


def run(args):
    design_path, geometry_path = args.design.resolve(), args.geometry.resolve()
    inputs = [design_path, geometry_path] + ([args.protect.resolve()] if args.protect else [])
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ArtifactError('--out must be a new or empty directory')
    design = json.loads(design_path.read_text(encoding='utf-8'))
    if not isinstance(design.get('charts'), list) or not design['charts']:
        raise ValueError('Design needs a nonempty charts list')
    geometry = load_geometry(geometry_path, allow_repeat_uv=True)
    protect = np.asarray(Image.open(args.protect).convert('L')) > 0 if args.protect else None
    atlas=design.get('atlas',{})
    size=(int(atlas.get('width',2048)),int(atlas.get('height',2048)))
    if protect is not None and not atlas:size=(protect.shape[1],protect.shape[0])
    if not all(16<=v<=8192 for v in size):raise ValueError('Invalid atlas size')
    if protect is None:protect=np.zeros((size[1],size[0]),bool)
    if protect.shape!=(size[1],size[0]):raise ValueError('Protect mask and design atlas differ')
    assignment,axes,facing,quality,warnings=select_charts(design,geometry,size)
    owners=surface_owners(np.asarray(geometry['uvs'],np.float64),assignment,facing,*size)
    classes=slope_classes(geometry,assignment,axes)
    frames=chart_frames(design)
    ids=[c['id'] for c in design['charts']]
    if any(r['chart'] not in ids for r in design.get('inspection_regions',[])):
        raise ValueError('Unknown inspection region chart')
    font = load_font(13)
    charts = [c for c in design['charts'] if not args.chart or c['id'] in args.chart]
    if args.chart and set(args.chart) - set(ids):
        raise ValueError('Unknown chart requested: ' + ', '.join(sorted(set(args.chart) - set(ids))))
    views = {}
    by_id = {chart['id']: chart for chart in charts}
    for entry in getattr(args, 'view_from', []):
        name, sep, direction = entry.partition('=')
        if not sep or name not in by_id or name in views or direction not in ('x','-x','y','-y','z','-z'):
            raise ValueError('--view-from expects one selected CHART=x|-x|y|-y|z|-z per chart')
        chart = by_id[name]
        if parse_axis(direction)[0] in (parse_axis(chart['u'])[0],parse_axis(chart['v'])[0]):
            raise ValueError('--view-from must be perpendicular to the chart projection plane')
        views[name] = direction
    outputs = [out / f'{c["id"]}.png' for c in charts] + [out / 'surface-map.json']
    report = dict(schema_version=2, atlas_size=size, coordinate_system='world projection in metres; native frame evaluated at carrier UV', tool='surface_map.py', design=str(design_path), charts={}, risky_items=[], seam_items=[], warnings=warnings,
                  classes=dict(flat='projection keeps >= 80% of area', curving='50-80%', steep='< 50%, lines and patterns streak',
                               **{'lost-to-earlier-chart': 'texel shared with an earlier chart, which wins it; reorder charts or move the item'},
                               **{'shared-within-chart': 'overlapping triangle interiors in this chart; author on the winning surface or split the chart to choose its priority'},
                               protected='mechanical texels from --protect', **{'off-surface': 'no triangle of this chart',
                  'hidden-under-other-surface': 'covered by skin, canopy or another chart seen from this side: never visible',
                  'seam': 'narrow sliver between two parts of this chart that another chart (or none) paints, e.g. the side wall of a raised dorsal strip; an item crossing it shows a thin break in game: keep motifs off it, end them at it, or make it the dark channel'}),
                  risk_rule=dict({k: [NAMES[c] for c in v] for k, v in RISKY.items()},
                                 fields=f'also at risk when less than {MIN_VISIBLE:.0%} is visible'))
    with ArtifactTransaction(outputs, inputs=inputs, label='surface-map') as transaction:
        staged = {p: transaction.stage(p) for p in outputs}
        for chart in charts:
            index = [c['id'] for c in design['charts']].index(chart['id'])
            shapes = item_shapes(design, {chart['id']}, design_path.parent)
            # Do not feed this inspection direction to select_charts/surface_owners:
            # changing the viewer must never change which side owns a texture sample.
            inspect_chart = dict(chart, _inspection_view=views.get(chart['id']))
            image, scores, totals = render_chart(inspect_chart, index, geometry, assignment, axes, classes, shapes, args.scale, font, owners, protect, frames[index])
            image.save(staged[out / f'{chart["id"]}.png'])
            report['charts'][chart['id']] = dict(area_share=totals, items=scores, view_from=views.get(chart['id']), **quality[chart['id']])
            report['risky_items'] += [dict(chart=chart['id'], **s) for s in scores if s['risky_share'] > args.threshold]
            report['seam_items'] += [dict(chart=chart['id'], id=s['id'], kind=s['kind'],
                                         seam_pixels=s['seam_pixels'], seam_area_m2=s['seam_area_m2'],
                                         seam_length_m=s['seam_length_m'])
                                     for s in scores if (s['kind']=='focus' and s['seam_pixels']>0) or (s['kind']!='image' and s['seam_length_m']>=getattr(args,'seam_report',.1))]
        report['risky_items'].sort(key=lambda s: -s['risky_share'])
        staged[out / 'surface-map.json'].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--design', type=Path, required=True, help='vector_paint design JSON (charts required; layers optional)')
    parser.add_argument('--protect', type=Path, help='Atlas mask of mechanical texels (nonzero = protected)')
    parser.add_argument('--chart', action='append', default=[], help='Only these chart ids (repeatable)')
    parser.add_argument('--view-from', action='append', default=[], metavar='CHART=AXIS',
                        help='Visibility from a signed physical axis, e.g. dorsal=y; never changes paint ownership')
    parser.add_argument('--scale', type=float, default=60, help='Pixels per metre (default 60)')
    parser.add_argument('--threshold', type=float, default=.15, help='Report items with more risky ground than this share (default 0.15)')
    parser.add_argument('--seam-report', type=float, default=.1,
                        help='Legacy threshold (intersecting pixels / scale); focus boxes report any overlap')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output directory')
    report = run(parser.parse_args(argv))
    for item in report['risky_items']:
        print(f"RISK {item['chart']:12} {item['id']:28} {item['risky_share']:.0%} on {item['ground']}")
    for item in report['seam_items']:
        print(f"SEAM {item['chart']:12} {item['id']:28} overlaps {item['seam_pixels']} projected seam pixels")
    if not report['risky_items']:
        print('No item over the risk threshold.')


if __name__ == '__main__':
    main()
