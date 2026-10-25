"""Run INSIDE Blender: preserve NPZ native UVs, save an inspectable .blend.

blender --background --factory-startup --python-exit-code 1 --python blender_uv_review.py -- ...
This tool creates a fresh scene; it never loads or overwrites a user's .blend.
"""
from pathlib import Path
import argparse
import fnmatch
import hashlib
import json
import sys
import numpy as np
import bpy
from mathutils import Matrix, Vector


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(a):
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('Output must be a new/empty directory')
    source, texture = a.geometry.resolve(), a.texture.resolve()
    if out in source.parents or out in texture.parents:
        raise ValueError('Output must not contain its inputs')
    original_hashes = {str(p): sha(p) for p in [source, texture]}
    with np.load(source, allow_pickle=False) as z:
        t, uv = z['triangles'].copy(), z['uvs'].copy()
        ids, names = z['node_ids'].copy(), z['names'].astype(str)
        mids, mnames = z['material_ids'].copy(), z['material_names'].astype(str)
    if t.ndim != 3 or t.shape[1:] != (3, 3) or uv.shape != (len(t), 3, 2) or not np.isfinite(t).all() or not np.isfinite(uv).all():
        raise ValueError('Invalid native geometry arrays')
    if ids.shape != (len(t),) or mids.shape != (len(t),) or np.any(ids < 0) or np.any(ids >= len(names)) or np.any(mids < 0) or np.any(mids >= len(mnames)):
        raise ValueError('Invalid node/material domains')
    chosen = [i for i, n in enumerate(mnames) if any(fnmatch.fnmatchcase(n, p) for p in a.material)]
    mask = np.isin(mids, chosen)
    if a.node:
        mask &= np.asarray([any(fnmatch.fnmatchcase(n, p) for p in a.node) for n in names[ids]])
    if not mask.any():
        raise ValueError('No triangles match the explicit material/node selection')
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    image = bpy.data.images.load(str(texture), check_existing=False)
    image.colorspace_settings.name = 'sRGB'
    image.pack()
    mat = bpy.data.materials.new('Review_colour_only'); mat.use_nodes = True
    tree = mat.node_tree; tree.nodes.clear()
    tx = tree.nodes.new('ShaderNodeTexImage'); tx.image = image; tx.interpolation = 'Linear'
    emission = tree.nodes.new('ShaderNodeEmission'); output = tree.nodes.new('ShaderNodeOutputMaterial')
    tree.links.new(tx.outputs['Color'], emission.inputs['Color']); tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])
    tree.nodes.active = tx
    objects, records = [], []
    for node_id in sorted(set(ids[mask].tolist())):
        take = mask & (ids == node_id)
        points = t[take].reshape(-1, 3)
        triangles = np.arange(len(points), dtype=np.int32).reshape(-1, 3)
        mesh = bpy.data.meshes.new(str(names[node_id]) + '_NativeMesh')
        mesh.from_pydata(points.tolist(), [], triangles.tolist()); mesh.update()
        layer = mesh.uv_layers.new(name='NativeUV')
        flat_uv = uv[take].reshape(-1, 2).astype(np.float32)
        layer.data.foreach_set('uv', flat_uv.reshape(-1))
        actual = np.empty(len(flat_uv) * 2, dtype=np.float32)
        layer.data.foreach_get('uv', actual)
        error = float(np.max(np.abs(actual.reshape(-1, 2).astype(np.float64) - uv[take].reshape(-1, 2))))
        if error > 1e-6:
            raise ValueError('Native UV roundtrip exceeded float32 precision')
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(str(names[node_id]), mesh); scene.collection.objects.link(obj)
        obj['source_node'] = str(names[node_id]); obj['source_geometry_sha256'] = original_hashes[str(source)]
        objects.append(obj)
        records.append({'node': str(names[node_id]), 'triangles': int(take.sum()), 'max_uv_error': error})
    bounds = t[mask].reshape(-1, 3)
    low, high = bounds.min(axis=0), bounds.max(axis=0)
    center = (low + high) / 2
    distance = float(max(high - low) * 2 + 10)
    def direction(spec):
        value = np.zeros(3)
        value['xyz'.index(spec[-1])] = -1 if spec.startswith('-') else 1
        return value
    up, forward = direction(a.up_axis), direction(a.forward_axis)
    if abs(float(up @ forward)) > .01:
        raise ValueError('Profile up and forward axes must be distinct')
    right = np.cross(forward, up)
    camera_data = bpy.data.cameras.new('ReviewCamera'); camera_data.type = 'ORTHO'
    camera_data.ortho_scale = float(max(np.ptp(bounds @ right), np.ptp(bounds @ forward)) * 1.16)
    camera = bpy.data.objects.new('ReviewCamera', camera_data); scene.collection.objects.link(camera)
    if a.view == 'top':
        matrix = np.eye(4); matrix[:3, 0] = right; matrix[:3, 1] = forward; matrix[:3, 2] = up
        matrix[:3, 3] = center + up * distance
        camera.matrix_world = Matrix(matrix.tolist())
    else:
        position = center + (forward + up - right) * distance
        back = (position - center) / np.linalg.norm(position - center)
        cam_right = np.cross(up, back); cam_right /= np.linalg.norm(cam_right)
        cam_up = np.cross(back, cam_right)
        matrix = np.eye(4); matrix[:3, 0] = cam_right; matrix[:3, 1] = cam_up; matrix[:3, 2] = back; matrix[:3, 3] = position
        camera.matrix_world = Matrix(matrix.tolist())
    scene.camera = camera
    scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 1
    scene.render.resolution_x = scene.render.resolution_y = a.pixels; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'; scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0; scene.view_settings.gamma = 1
    scene.render.dither_intensity = 0
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    # Preserve a real UV/Image Editor alongside 3D when this file is opened.
    uv_areas = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
                area.spaces.active.shading.type = 'MATERIAL'
            if area.type == 'IMAGE_EDITOR':
                area.ui_type = 'UV'; area.spaces.active.image = image
                uv_areas += 1
    workspace = bpy.data.workspaces.get('UV Editing')
    if workspace is not None and bpy.context.window is not None:
        bpy.context.window.workspace = workspace
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'native-uv-review.blend'), check_existing=True)
    if a.render:
        bpy.ops.object.mode_set(mode='OBJECT')
        scene.render.filepath = str(out / (a.view + '.png')); bpy.ops.render.render(write_still=True)
    if not all(sha(Path(p)) == v for p, v in original_hashes.items()):
        raise ValueError('Source file changed')
    record = {'blender_version': bpy.app.version_string, 'inputs': original_hashes, 'tool_sha256': sha(Path(__file__)),
              'profile_axes': {'up': a.up_axis, 'forward': a.forward_axis},
              'material_names': mnames[chosen].tolist(), 'selected_triangles': int(mask.sum()), 'nodes': records,
              'uv_editor_areas_configured': uv_areas, 'uv_workspace_selected': workspace is not None and bpy.context.window is not None,
              'coordinates': 'Source XYZ and UV loop order preserved; no unwrap, repack, welding or modifier applied. Blender mesh storage uses float32; source NPZ is untouched.',
              'texture': 'sRGB colour only; colour alpha not interpreted as aircraft transparency; no packed material/normal map treated as colour',
              'source_files_unchanged': True, 'blend': {'path': str(out / 'native-uv-review.blend'), 'sha256': sha(out / 'native-uv-review.blend')},
              'limits': 'Single selected offline colour/layout view. Not game shader, animation, shared-UV independence, seven-view artwork or full material validation.'}
    (out / 'receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('NATIVE_UV_REVIEW_OK', json.dumps({'triangles': int(mask.sum()), 'nodes': len(objects), 'max_uv_error': max(r['max_uv_error'] for r in records)}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--geometry', type=Path, required=True)
    p.add_argument('--texture', type=Path, required=True)
    p.add_argument('--material', action='append', required=True)
    p.add_argument('--up-axis', choices=['x', 'y', 'z', '-x', '-y', '-z'], required=True, help='Confirmed profile axis, not inferred from model name')
    p.add_argument('--forward-axis', choices=['x', 'y', 'z', '-x', '-y', '-z'], required=True)
    p.add_argument('--node', action='append')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--view', choices=['top', 'iso'], default='top')
    p.add_argument('--pixels', type=int, default=1200)
    p.add_argument('--render', action='store_true', help='One local inspection view only')
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    a = p.parse_args(argv)
    if not 128 <= a.pixels <= 4096:
        p.error('--pixels must be within 128..4096')
    run(a)
