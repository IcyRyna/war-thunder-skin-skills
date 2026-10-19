"""Real JIT regression tests for bound original-UV projection and file safety."""
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import surface_preview as surface


class ProjectionContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Top camera sees outward +Y, while the atlas remains rectangular.
        self.world = np.array([[[0, 0, 0], [0, 0, 1], [1, 0, 0]]], dtype=np.float32)
        self.uvs = np.array([[[.05, .05], [.95, .05], [.05, .95]]], dtype=np.float32)
        self.geometry = self.root / 'geometry.npz'
        self.save_geometry()
        self.base = self.root / 'base.png'
        Image.new('RGBA', (96, 48), (80, 90, 100, 77)).save(self.base)

    def save_geometry(self, **extras):
        values = dict(triangles=self.world, uvs=self.uvs,
                      node_ids=np.zeros(len(self.world), dtype=np.int32), names=np.array(['body']))
        values.update(extras)
        np.savez_compressed(self.geometry, **values)

    def guides(self):
        output = self.root / 'guides'
        surface.render(self.geometry, self.base, ['top', 'bottom'], output, 128, 192)
        return output

    def overlay(self, color=(200, 30, 50, 255), name='overlay.png'):
        path = self.root / name
        Image.new('RGBA', (128, 192), color).save(path)
        return path

    def attempt_bake(self, guide, overlay, output=None):
        return surface.bake(self.geometry, self.base, [f'{guide}={overlay}'], output or self.root / 'result.png', .45)

    def assert_no_success_output(self):
        self.assertFalse((self.root / 'result.png').exists())
        self.assertFalse((self.root / 'result-paint-mask.png').exists())
        self.assertFalse((self.root / 'result.projection.json').exists())

    def test_bound_rectangular_roundtrip_preserves_alpha(self):
        folder = self.guides()
        guide = json.loads((folder / 'top.json').read_text())
        self.assertEqual(guide['schema_version'], 2)
        self.assertEqual(guide['geometry_sha256'], surface.sha256_file(self.geometry))
        self.assertEqual(guide['depth_sha256'], surface.sha256_file(folder / 'top-depth.npz'))
        with np.load(folder / 'top-depth.npz', allow_pickle=False) as data:
            self.assertEqual(data['owners'].shape, (192, 128))
            self.assertEqual(str(data['camera_sha256']), guide['camera_sha256'])
        result = self.attempt_bake(folder / 'top.json', self.overlay())
        self.assertGreater(result['painted_pixels'], 100)
        self.assertEqual(result['state'], 'complete')
        with Image.open(self.root / 'result.png') as image:
            self.assertEqual(image.size, (96, 48))
            self.assertTrue(np.all(np.asarray(image)[:, :, 3] == 77))

    def test_geometry_replaced_at_same_path_is_rejected(self):
        folder = self.guides()
        self.world[:, :, 1] += .01
        self.save_geometry()
        with self.assertRaisesRegex(ValueError, 'geometry content'):
            self.attempt_bake(folder / 'top.json', self.overlay())
        self.assert_no_success_output()
        receipts = list((self.root / '.artifact-failures').glob('*.failure.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())['state'], 'failed')

    def test_swapped_depth_is_rejected_even_if_shape_matches(self):
        folder = self.guides()
        (folder / 'top-depth.npz').write_bytes((folder / 'bottom-depth.npz').read_bytes())
        with self.assertRaisesRegex(ValueError, 'depth/owner content'):
            self.attempt_bake(folder / 'top.json', self.overlay())
        self.assert_no_success_output()

    def test_depth_internal_binding_catches_relabelled_archive(self):
        folder = self.guides()
        guide_path = folder / 'top.json'; meta = json.loads(guide_path.read_text())
        (folder / 'top-depth.npz').write_bytes((folder / 'bottom-depth.npz').read_bytes())
        meta['depth_sha256'] = surface.sha256_file(folder / 'top-depth.npz')
        guide_path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, 'different geometry/camera'):
            self.attempt_bake(guide_path, self.overlay())
        self.assert_no_success_output()

    def test_legacy_guide_rejected_without_rewriting_it(self):
        folder = self.guides(); guide_path = folder / 'top.json'
        meta = json.loads(guide_path.read_text()); meta.pop('schema_version')
        guide_path.write_text(json.dumps(meta)); before = guide_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'legacy camera guide'):
            self.attempt_bake(guide_path, self.overlay())
        self.assertEqual(guide_path.read_bytes(), before)
        self.assert_no_success_output()

    def test_camera_edit_invalidates_binding(self):
        folder = self.guides(); guide_path = folder / 'top.json'
        meta = json.loads(guide_path.read_text()); meta['scale'] *= 2
        guide_path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, 'camera binding'):
            self.attempt_bake(guide_path, self.overlay())
        self.assert_no_success_output()

    def test_render_rejects_inputs_changed_after_their_data_was_loaded(self):
        original_rasterize = surface.rasterize
        for kind in ('geometry', 'texture'):
            with self.subTest(input=kind):
                self.save_geometry()
                Image.new('RGBA', (96, 48), (80, 90, 100, 77)).save(self.base)
                folder = self.root / f'changed-{kind}'
                source = self.geometry if kind == 'geometry' else self.base
                def render_then_change(*args, **kwargs):
                    result = original_rasterize(*args, **kwargs)
                    source.write_bytes(source.read_bytes() + b'changed-after-decode')
                    return result
                with patch.object(surface, 'rasterize', side_effect=render_then_change):
                    with self.assertRaisesRegex(ValueError, 'Input changed before output commit'):
                        surface.render(self.geometry, self.base, ['top'], folder, 128, 128)
                self.assertFalse((folder / 'top.json').exists())
                self.assertFalse((folder / 'top.png').exists())

    def test_bake_rejects_camera_depth_overlay_and_base_changed_after_read(self):
        original_project = surface.project_overlay
        for kind in ('camera', 'depth', 'overlay', 'base'):
            with self.subTest(input=kind):
                Image.new('RGBA', (96, 48), (80, 90, 100, 77)).save(self.base)
                folder = self.root / f'loaded-{kind}'
                surface.render(self.geometry, self.base, ['top'], folder, 128, 192)
                overlay = self.overlay(name=f'{kind}.png')
                source = {'camera': folder / 'top.json', 'depth': folder / 'top-depth.npz',
                          'overlay': overlay, 'base': self.base}[kind]
                def project_then_change(*args, **kwargs):
                    result = original_project(*args, **kwargs)
                    source.write_bytes(source.read_bytes() + b'\n')
                    return result
                output = self.root / f'result-{kind}.png'
                with patch.object(surface, 'project_overlay', side_effect=project_then_change):
                    with self.assertRaisesRegex(ValueError, 'Input changed before output commit'):
                        self.attempt_bake(folder / 'top.json', overlay, output)
                self.assertFalse(output.exists())
                self.assertFalse(output.with_suffix('.projection.json').exists())

    def test_transparent_overlay_is_explicit_noop(self):
        folder = self.guides()
        result = self.attempt_bake(folder / 'top.json', self.overlay((255, 30, 40, 0)))
        self.assertEqual(result['state'], 'no_op')
        self.assertEqual(result['painted_pixels'], 0)
        with Image.open(self.base) as a, Image.open(self.root / 'result.png') as b:
            self.assertTrue(np.array_equal(np.asarray(a), np.asarray(b)))

    def test_nontransparent_overlay_zero_hits_is_failure(self):
        folder = self.guides()
        with self.assertRaisesRegex(ValueError, 'zero UV hits'):
            self.attempt_bake(folder / 'bottom.json', self.overlay())
        self.assert_no_success_output()

    def test_one_successful_overlay_cannot_hide_another_zero_hit_overlay(self):
        folder = self.guides(); overlay = self.overlay()
        with self.assertRaisesRegex(ValueError, 'zero UV hits'):
            surface.bake(self.geometry, self.base, [f'{folder / "top.json"}={overlay}', f'{folder / "bottom.json"}={overlay}'],
                         self.root / 'result.png', .45)
        self.assert_no_success_output()

    def test_receipt_write_failure_rolls_back_all_new_outputs(self):
        folder = self.guides(); before = self.base.read_bytes()
        with patch.object(surface, 'write_json', side_effect=OSError('receipt disk failure')):
            with self.assertRaisesRegex(OSError, 'receipt disk failure'):
                self.attempt_bake(folder / 'top.json', self.overlay())
        self.assert_no_success_output()
        self.assertEqual(self.base.read_bytes(), before)
        failures = list((self.root / '.artifact-failures').glob('*.failure.json'))
        self.assertEqual(len(failures), 1)
        self.assertEqual(json.loads(failures[0].read_text())['state'], 'failed')

    def test_repeating_uv_rejected_before_jit_and_no_overwrite(self):
        self.uvs += 1; self.save_geometry(); before = self.geometry.read_bytes()
        with self.assertRaisesRegex(ValueError, 'outside 0..1'):
            self.guides()
        self.assertEqual(self.geometry.read_bytes(), before)
        self.assertFalse((self.root / 'guides/top.png').exists())
        # Scene-only loading is explicit and does not change projection policy.
        self.assertTrue((surface.load_geometry(self.geometry, allow_repeat_uv=True)['uvs'] > 1).any())

    def test_render_refuses_input_and_derived_output_collisions(self):
        folder = self.root / 'guard'; folder.mkdir()
        source = folder / 'top-mask.png'; Image.new('RGBA', (8, 8), (1, 2, 3, 4)).save(source)
        before = source.read_bytes()
        with self.assertRaises((FileExistsError, surface.ArtifactError)):
            surface.render(self.geometry, source, ['top'], folder, 128, 128)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse((folder / 'top.png').exists())

    def test_bake_refuses_base_and_overlay_collisions(self):
        folder = self.guides(); overlay = self.overlay()
        before = self.base.read_bytes()
        with self.assertRaises((FileExistsError, surface.ArtifactError)):
            self.attempt_bake(folder / 'top.json', overlay, self.base)
        self.assertEqual(self.base.read_bytes(), before)
        protected = self.root / 'result-paint-mask.png'; protected.write_bytes(overlay.read_bytes())
        before = protected.read_bytes()
        with self.assertRaises((FileExistsError, surface.ArtifactError)):
            self.attempt_bake(folder / 'top.json', protected)
        self.assertEqual(protected.read_bytes(), before)
        self.assertFalse((self.root / 'result.png').exists())

    def test_render_existing_output_set_is_never_replaced(self):
        folder = self.guides(); before = {p.name: p.read_bytes() for p in folder.iterdir()}
        with self.assertRaises(FileExistsError):
            self.guides()
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_invalid_geometry_shapes_finite_and_indices(self):
        fixtures = [dict(triangles=np.zeros((3, 3))), dict(uvs=np.zeros((1, 2, 2))),
                    dict(node_ids=np.array([1])), dict(node_ids=np.array([.5])),
                    dict(triangles=np.full((1, 3, 3), np.nan)), dict(names=np.array(['name'], dtype=object))]
        for fixture in fixtures:
            with self.subTest(fields=list(fixture)):
                self.save_geometry(**fixture)
                with self.assertRaises((ValueError, TypeError)):
                    surface.load_geometry(self.geometry)

    def test_invalid_camera_and_visibility_fail_before_jit(self):
        valid = dict(basis=np.eye(3), center=[0, 0], scale=1, width=128, height=128)
        for change in (dict(scale=0), dict(scale=np.nan), dict(basis=np.ones((3, 3))),
                       dict(center=[np.nan, 0]), dict(width=128.0), dict(height=-1)):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    surface.validate_camera({**valid, **change})
        depth = np.full((8, 8), -np.inf, dtype=np.float32); owners = np.full((8, 8), -1, dtype=np.int32)
        with self.assertRaises(ValueError): surface.validate_visibility(depth, owners, 1, (9, 8))
        owners[0, 0] = 9
        with self.assertRaises(ValueError): surface.validate_visibility(depth, owners, 1, (8, 8))
        owners[0, 0] = 0; depth[0, 0] = np.nan
        with self.assertRaises(ValueError): surface.validate_visibility(depth, owners, 1, (8, 8))
        owners[0, 0] = -1; depth[0, 0] = 0
        with self.assertRaises(ValueError): surface.validate_visibility(depth, owners, 1, (8, 8))

    def test_finite_float64_overflow_rejected_after_float32_conversion(self):
        huge_world = self.world.astype(np.float64); huge_world[0, 0, 0] = 1e100
        with np.errstate(over='ignore', invalid='ignore'):
            with self.assertRaises(ValueError): surface.validate_geometry_arrays(huge_world, self.uvs)
            depth = np.array([[1e100]], dtype=np.float64); owners = np.array([[0]], dtype=np.int32)
            with self.assertRaisesRegex(ValueError, 'float32'):
                surface.validate_visibility(depth, owners, 1, (1, 1))

    def test_malformed_npz_rejected_without_success_artifacts(self):
        self.geometry.write_bytes(b'PK\x03\x04truncated')
        with self.assertRaises(Exception):
            self.guides()
        self.assertFalse((self.root / 'guides/top.png').exists())

    def test_decoder_priority_explicit_environment_project(self):
        def decoder(name):
            path = self.root / name; path.mkdir()
            for file in ('wt_assets.py', 'dae_backend.py'): (path / file).write_text('')
            return path
        explicit, environment, configured = decoder('explicit'), decoder('environment'), decoder('configured')
        (self.root / '.skin-workshop.json').write_text(json.dumps({'tools': {'asset_decoder': 'configured'}}))
        with patch.dict(os.environ, {'WT_ASSET_TOOLS': str(environment)}):
            self.assertEqual(surface.resolve_asset_tools(explicit, self.root), explicit)
            self.assertEqual(surface.resolve_asset_tools(None, self.root), environment)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(surface.resolve_asset_tools(None, self.root), configured)
        with patch.dict(os.environ, {'WT_ASSET_TOOLS': str(environment)}):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                surface.resolve_asset_tools(self.root / 'missing', self.root)

    def test_prepare_preserves_triangle_material_ids_and_resources(self):
        tools = self.root / 'decoder'; tools.mkdir()
        for name in ('wt_assets.py', 'dae_backend.py'): (tools / name).write_text('')
        pack = self.root / 'source.grp'; pack.write_bytes(b'original')
        material = types.SimpleNamespace(getName=lambda: 'paint', getTextureSlots=lambda: ['plane_c', 'plane_n'])
        obj = types.SimpleNamespace(name='wing', skinned=False, materials={0: 'paint'}, faces=[(0, 1, 2)])
        class Model:
            materials = [material]
            skeleton = None
            def __iter__(self): return iter([obj])
            def getVertex(self, i, parentBone=None): return [(0, 0, 0), (0, 0, 1), (1, 0, 0)][i]
            def getUV(self, i): return [(0, 0), (1, 0), (0, 1)][i]
        locate = types.SimpleNamespace(locate=lambda *a: {'matches': [dict(pack=str(pack), name='plane', class_id=0xB4B7D9C4)]})
        backend = types.SimpleNamespace(load_model=lambda *a: (Model(), None))
        with patch.dict('sys.modules', {'wt_assets': locate, 'dae_backend': backend}):
            result = surface.prepare(self.root, 'plane', 'plane_c', self.root / 'prepared', tools, [])
        data = surface.load_geometry(result['geometry'])
        self.assertEqual(data['material_ids'].tolist(), [0])
        self.assertEqual(data['material_names'].tolist(), ['paint'])
        self.assertEqual(json.loads(str(data['material_resources'][0])), ['plane_c', 'plane_n'])
        self.assertEqual(pack.read_bytes(), b'original')

    def test_same_direction_hidden_sheet_receives_zero_pixels(self):
        front = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], dtype=np.float32)
        rear = front.copy(); rear[:, 2] = -.002
        world = np.stack([front, rear])
        uvs = np.array([[[.02, .02], [.45, .02], [.02, .98]], [[.55, .02], [.98, .02], [.55, .98]]], dtype=np.float32)
        basis = np.eye(3, dtype=np.float32); screen, camera = surface.screen_vertices(world, basis, 128, 128)
        base = np.full((96, 128, 4), 80, dtype=np.uint8)
        _, depth, visible = surface.rasterize(screen, world, uvs, base, 128, 128)
        overlay = np.full((128, 128, 4), 255, dtype=np.uint8); output = base.copy()
        score = np.zeros(base.shape[:2], dtype=np.float32); owner = np.full(base.shape[:2], -1, dtype=np.int32)
        writes = surface.project_overlay(world, uvs, basis, np.asarray(camera['center'], dtype=np.float32), camera['scale'],
                                         overlay, depth, base, output, score, owner, 3 / camera['scale'], .45, visible)
        self.assertGreater(writes, 100)
        self.assertTrue(np.all(owner[score > 0] == 0))
        self.assertTrue(np.array_equal(output[:, 70:], base[:, 70:]))
        self.assertTrue(surface._project_overlay.signatures)

    def test_shared_edge_recovery_is_continuous_and_order_independent(self):
        world = np.array([[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]], dtype=np.float32)
        uvs = world[:, :, :2].copy(); basis = np.eye(3, dtype=np.float32)
        def project(order):
            w, uv = world[order].copy(), uvs[order].copy()
            screen, meta = surface.screen_vertices(w, basis, 128, 128)
            base = np.zeros((64, 64, 4), dtype=np.uint8); base[:, :, 3] = 255
            _, depth, visible = surface.rasterize(screen, w, uv, base, 128, 128)
            overlay = np.full((128, 128, 4), 255, dtype=np.uint8); score = np.zeros((64, 64), dtype=np.float32)
            output = base.copy(); owner = np.full((64, 64), -1, dtype=np.int32)
            surface.project_overlay(w, uv, basis, np.asarray(meta['center'], dtype=np.float32), meta['scale'], overlay, depth,
                                    base, output, score, owner, 3 / meta['scale'], .45, visible)
            return output, score
        output, score = project([0, 1]); reverse, reverse_score = project([1, 0])
        self.assertTrue(np.all(score[2:61, 2:61] > 0))
        self.assertTrue(np.array_equal(output, reverse))
        self.assertTrue(np.array_equal(score > 0, reverse_score > 0))
        neighbors = surface.triangle_neighbors(world, np.array([0, 1]))
        self.assertTrue(np.all(neighbors == -1))

    def test_folded_and_nonmanifold_edges_never_become_recovery_neighbors(self):
        world = np.array([[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]], dtype=np.float32)
        folded = world.copy(); folded[1, 2] = [.1, 0, -.01]
        self.assertTrue(np.all(surface.triangle_neighbors(folded) == -1))
        nonmanifold = np.concatenate([world, world[1:]], axis=0)
        self.assertTrue(np.all(surface.triangle_neighbors(nonmanifold) == -1))

    def test_projection_uses_pixel_center_aligned_bilinear_color(self):
        world = np.array([[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]], dtype=np.float32)
        uvs = world[:, :, :2].copy(); basis = np.eye(3, dtype=np.float32)
        screen, meta = surface.screen_vertices(world, basis, 128, 128)
        base = np.zeros((32, 32, 4), dtype=np.uint8); base[:, :, 3] = 255
        _, depth, visible = surface.rasterize(screen, world, uvs, base, 128, 128)
        overlay = np.zeros((128, 128, 4), dtype=np.uint8); overlay[:, :, 3] = 255
        overlay[:, :, 0] = np.arange(128)[None, :]; overlay[:, :, 1] = np.arange(128)[:, None]
        output = base.copy(); score = np.zeros((32, 32), dtype=np.float32); owner = np.full((32, 32), -1, dtype=np.int32)
        surface.project_overlay(world, uvs, basis, np.asarray(meta['center'], dtype=np.float32), meta['scale'], overlay,
                                depth, base, output, score, owner, 3 / meta['scale'], .45, visible)
        x, y = 7, 11
        # Forward bilinear sampling places atlas texel centers at integers.
        u, v = x / 31, 1 - y / 31
        # Pixel-edge camera coordinates become image pixel-center indices
        # before bilinear color filtering; exact geometric visibility is unchanged.
        expected_x = int(np.clip((u - meta['center'][0]) * meta['scale'] + 64 - .5, 0, 127))
        expected_y = int(np.clip((meta['center'][1] - v) * meta['scale'] + 64 - .5, 0, 127))
        self.assertEqual(output[y, x, :2].tolist(), [expected_x, expected_y])

    def project_fixture(self, world, uvs, atlas_size=(64, 64), overlay=None):
        basis = np.eye(3, dtype=np.float32)
        world, uvs = np.asarray(world, np.float32), np.asarray(uvs, np.float32)
        screen, camera = surface.screen_vertices(world, basis, 128, 128)
        width, height = atlas_size
        base = np.full((height, width, 4), 80, dtype=np.uint8)
        _, depth, visible = surface.rasterize(screen, world, uvs, base, 128, 128)
        if overlay is None:
            overlay = np.full((128, 128, 4), 255, dtype=np.uint8)
        output = base.copy(); score = np.zeros((height, width), dtype=np.float32)
        owners = np.full((height, width), -1, dtype=np.int32); diagnostics = {}
        writes = surface.project_overlay(world, uvs, basis, np.asarray(camera['center'], np.float32), camera['scale'],
                                         overlay, depth, base, output, score, owners, 3/camera['scale'], .45,
                                         visible, diagnostics=diagnostics)
        return output, score, owners, diagnostics, visible, writes

    def test_thin_uv_without_any_texel_center_gets_exact_bilinear_support(self):
        world = [[[-1, -1, 0], [1, -1, 0], [-1, 1, 0]]]
        texels = np.array([[[2.1, 2.1], [2.9, 2.1], [2.1, 2.4]]], np.float32)
        uvs = texels/7; uvs[:, :, 1] = 1-uvs[:, :, 1]
        output, score, owners, diagnostics, visible, writes = self.project_fixture(world, uvs, (8, 8))
        self.assertGreater(int((visible >= 0).sum()), 100)
        self.assertEqual(diagnostics['pull_painted_texels'], 0)
        self.assertEqual(diagnostics['footprint_filled_texels'], 4)
        self.assertEqual(set(map(tuple, np.argwhere(score > 0))), {(2, 2), (2, 3), (3, 2), (3, 3)})
        self.assertTrue(np.all(output[score > 0, :3] == 255))
        self.assertTrue(np.all(owners[score > 0] == 0))
        self.assertEqual(writes, 4)
        self.assertTrue(surface._bilinear_footprint.signatures)

    def test_gradient_at_known_texel_is_not_half_texel_shifted(self):
        world = np.array([[[-1, -1, 0], [1, -1, 0], [-1, 1, 0]]], np.float32)
        texels = np.array([[[1, 1], [6, 1], [1, 6]]], np.float32)
        uvs = texels/7; uvs[:, :, 1] = 1-uvs[:, :, 1]
        basis = np.eye(3, dtype=np.float32); center = np.zeros(2, dtype=np.float32); scale = 19.
        screen = world.copy(); screen[:, :, 0] = world[:, :, 0]*scale+32; screen[:, :, 1] = 32-world[:, :, 1]*scale
        base = np.zeros((8, 8, 4), np.uint8); base[:, :, 3] = 255
        _, depth, visible = surface.rasterize(screen, world, uvs, base, 64, 64)
        overlay = np.zeros((64, 64, 4), np.uint8); overlay[:, :, 3] = 255
        overlay[:, :, 0] = np.arange(64)[None, :]*4
        output = base.copy(); score = np.zeros((8, 8), np.float32); owners = np.full((8, 8), -1, np.int32)
        surface.project_overlay(world, uvs, basis, center, scale, overlay, depth, base, output, score, owners, 3/scale, .45, visible)
        self.assertEqual(output[2, 2, 0], 80)  # old half-offset sampling yielded 96

    def test_footprint_does_not_expand_into_a_nearby_hidden_uv_island(self):
        front = np.array([[-1, -1, 0], [1, -1, 0], [-1, 1, 0]], np.float32)
        rear = front.copy(); rear[:, 2] = -.002
        texels = np.array([[[2.1, 2.1], [2.9, 2.1], [2.1, 2.4]], [[4.1, 2.1], [4.9, 2.1], [4.1, 2.4]]], np.float32)
        uvs = texels/7; uvs[:, :, 1] = 1-uvs[:, :, 1]
        output, score, owners, diagnostics, visible, writes = self.project_fixture(np.stack([front, rear]), uvs, (8, 8))
        self.assertEqual(set(map(tuple, np.argwhere(score > 0))), {(2, 2), (2, 3), (3, 2), (3, 3)})
        self.assertTrue(np.all(output[:, 4:] == 80))
        self.assertTrue(np.all(owners[score > 0] == 0))

    def test_footprint_preserves_local_occlusion_inside_a_uv_island(self):
        world = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 0, .01], [.6, 0, .01], [0, .6, .01]]], np.float32)
        uvs = np.array([[[.02, .02], [.45, .02], [.02, .98]], [[.55, .02], [.98, .02], [.55, .98]]], np.float32)
        output, score, owners, diagnostics, visible, writes = self.project_fixture(world, uvs, (128, 96))
        # Deep inside the rear triangle's occluded region, not an AA boundary.
        self.assertEqual(score[84, 8], 0)
        self.assertTrue(np.all(output[84, 8] == 80))
        self.assertGreater(score[84, 41], 0)

    def test_shared_uv_diagnostic_does_not_promise_independent_hidden_surface(self):
        front = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
        rear = front.copy(); rear[:, 2] = -.002
        uv = np.array([[.1, .1], [.9, .1], [.1, .9]], np.float32)
        output, score, owners, diagnostics, visible, writes = self.project_fixture(np.stack([front, rear]), np.stack([uv, uv]))
        self.assertGreater(diagnostics['overlapping_uv_center_texels'], 100)
        self.assertGreater(diagnostics['painted_overlapping_uv_center_texels'], 100)
        self.assertIn('cannot encode independent artwork', diagnostics['shared_uv_diagnostic'])
        self.assertTrue(np.all(owners[score > 0] == 0))

    def test_visible_shared_footprint_color_competition_is_reported(self):
        first = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
        second = first.copy(); second[:, 0] += 1.5
        texels = np.array([[[2.1, 2.1], [2.9, 2.1], [2.1, 2.4]]], np.float32)
        uv = texels/7; uv[:, :, 1] = 1-uv[:, :, 1]
        overlay = np.zeros((128, 128, 4), np.uint8); overlay[:, :, 3] = 255
        overlay[:, :64, 0] = 255; overlay[:, 64:, 1] = 255
        output, score, owners, diagnostics, visible, writes = self.project_fixture(np.stack([first, second]), np.concatenate([uv, uv]), (8, 8), overlay)
        self.assertGreater(diagnostics['footprint_color_competition_texels'], 0)
        self.assertEqual(diagnostics['footprint_filled_texels'], 4)




def exact_fixture_geometry(screen_xy, z=0., uv=None):
    points = np.asarray(screen_xy, dtype=np.float32)
    # Camera identity, width/height 16, scale 1, center zero.
    world = np.column_stack((points[:, 0]-8, 8-points[:, 1], np.full(3, z))).astype(np.float32)
    if uv is None:
        uv = np.asarray([[.1, .9], [.9, .9], [.1, .1]], dtype=np.float32)
    return world, np.asarray(uv, dtype=np.float32)


def exact_fixture_project(world, uvs, min_facing=.45):
    basis = np.eye(3, dtype=np.float32)
    screen = world@basis.T
    screen[:, :, 0] += 8
    screen[:, :, 1] = 8-screen[:, :, 1]
    base = np.zeros((64, 64, 4), dtype=np.uint8)
    base[:, :, 3] = np.arange(64, dtype=np.uint8)
    overlay = np.full((16, 16, 4), [220, 140, 30, 255], dtype=np.uint8)
    _, depth, visible = surface.rasterize(screen, world, uvs, base, 16, 16)
    out, score = base.copy(), np.zeros((64, 64), dtype=np.float32)
    owner = np.full((64, 64), -1, dtype=np.int32)
    report = {}
    writes = surface.project_overlay(world, uvs, basis, np.zeros(2, dtype=np.float32), 1., overlay, depth, base, out, score, owner, 3., min_facing, visible_owners=visible, diagnostics=report)
    return writes, out, score, owner, report, visible, base


class ExactVisibilityTests(unittest.TestCase):
    def test_subpixel_triangle_without_any_framebuffer_owner(self):
        a, uv = exact_fixture_geometry([[8.05, 8.05], [8.05, 8.3], [8.3, 8.05]])
        writes, out, score, owner, report, visible, base = exact_fixture_project(a[None], uv[None])
        self.assertEqual(int((visible >= 0).sum()), 0)
        self.assertGreater(writes, 1000)
        self.assertEqual(report['exact_visibility']['true_occluded_samples'], 0)
        self.assertGreater(report['exact_visibility']['framebuffer_owner_mismatch_accepted_samples'], 1000)
        np.testing.assert_array_equal(out[:, :, 3], base[:, :, 3])

    def test_adjacent_triangle_pixel_center_does_not_own_point(self):
        a, uv_a = exact_fixture_geometry([[6.1, 6.1], [6.1, 6.9], [6.9, 6.1]])
        b, uv_b = exact_fixture_geometry([[6.9, 6.1], [6.1, 6.9], [6.9, 6.9]], uv=[[.55, .9], [.9, .55], [.9, .9]])
        writes, out, score, owner, report, visible, base = exact_fixture_project(np.asarray([a, b]), np.asarray([uv_a*.45, uv_b]))
        self.assertGreater(writes, 100)
        self.assertGreater(report['exact_visibility']['framebuffer_owner_mismatch_accepted_samples'], 100)
        self.assertEqual(report['exact_visibility']['true_occluded_samples'], 0)

    def test_near_same_facing_occluder_blocks_back_layer(self):
        a, uv_a = exact_fixture_geometry([[2, 2], [2, 13], [13, 2]], z=0.)
        b, uv_b = exact_fixture_geometry([[2, 2], [2, 13], [13, 2]], z=.000001, uv=[[.55, .9], [.9, .9], [.55, .55]])
        writes, out, score, owner, report, visible, base = exact_fixture_project(np.asarray([a, b]), np.asarray([uv_a*.45, uv_b]))
        self.assertGreater(writes, 100)
        self.assertGreater(report['exact_visibility']['true_occluded_samples'], 100)
        self.assertFalse(np.any(owner == 0))
        self.assertTrue(np.any(owner == 1))

    def test_reverse_thin_surface_is_not_painted(self):
        a, uv_a = exact_fixture_geometry([[2, 2], [2, 13], [13, 2]], z=0.)
        b = a[::-1].copy(); b[:, 2] = -.000001
        uv_b = np.asarray([[.55, .9], [.9, .9], [.55, .55]], dtype=np.float32)
        _, out, _, owner, _, _, base = exact_fixture_project(np.asarray([a, b]), np.asarray([uv_a*.45, uv_b]))
        self.assertTrue(np.any(owner == 0))
        self.assertFalse(np.any(owner == 1))
        np.testing.assert_array_equal(out[:, :, 3], base[:, :, 3])

    def test_roundoff_does_not_admit_distinct_near_zero_depth_planes(self):
        for gap in (1e-11, 1e-16):
            a, uv_a = exact_fixture_geometry([[2, 2], [2, 13], [13, 2]], z=0.)
            b, uv_b = exact_fixture_geometry([[2, 2], [2, 13], [13, 2]], z=gap, uv=[[.55, .9], [.9, .9], [.55, .55]])
            _, _, _, owner, report, _, _ = exact_fixture_project(np.asarray([a, b]), np.asarray([uv_a*.45, uv_b]))
            self.assertFalse(np.any(owner == 0), gap)
            self.assertTrue(np.any(owner == 1), gap)

    def test_valid_world_microtriangle_has_no_screen_area_cutoff(self):
        a, uv = exact_fixture_geometry([[8.1, 8.1], [8.1, 8.10002], [8.10002, 8.1]])
        writes, _, score, _, report, visible, _ = exact_fixture_project(a[None], uv[None])
        self.assertEqual(int((visible >= 0).sum()), 0)
        self.assertGreater(writes, 1000)

    def test_outside_triangle_across_tile_edge_is_never_authorised(self):
        world = np.array([[[0, 0, 1], [-1000, 0, 1], [0, -10, 1]]], np.float32)
        index = surface.visibility_index(world, np.eye(3, dtype=np.float32), np.array([1.5e-7, 0], np.float32), 1., 32, 32)
        for sx in (15.9999999, 16.):
            z, owner = surface._point_depth(index['screen'], index['offsets'], index['entries'], index['columns'], index['tile'], sx, 20.)
            self.assertEqual(owner, -1)

    def test_single_skinny_face_never_occludes_itself(self):
        for dy in (.001, .01, .000001):
            world = np.array([[[0, 0, 0], [1000, 1, 125], [2000, 2+dy, 250]]], np.float32)
            uv = np.array([[[.05, .95], [.95, .95], [.05, .05]]], np.float32)
            basis, center = np.eye(3, dtype=np.float32), np.array([1000, 1+dy/3], np.float32)
            screen = world@basis.T
            screen[:,:,0] = (screen[:,:,0]-center[0])*.01+16
            screen[:,:,1] = (center[1]-screen[:,:,1])*.01+16
            base = np.zeros((64, 64, 4), np.uint8)
            overlay = np.full((32, 32, 4), 255, np.uint8)
            _, depth, visible = surface.rasterize(screen, world, uv, base, 32, 32)
            out, score, owner = base.copy(), np.zeros((64, 64), np.float32), np.full((64, 64), -1, np.int32)
            diagnostics = {}
            surface.project_overlay(world, uv, basis, center, .01, overlay, depth, base, out, score, owner, 300., .45, visible, diagnostics=diagnostics)
            self.assertEqual(diagnostics['exact_visibility']['true_occluded_samples'], 0)
            self.assertEqual(diagnostics['exact_visibility']['no_continuous_coverage_samples'], 0)
            self.assertEqual(diagnostics['exact_visibility']['accepted_samples'], diagnostics['exact_visibility']['queried_samples'])

    def test_geometry_camera_cache_identity(self):
        a, uv = exact_fixture_geometry([[2, 2], [2, 13], [13, 2]])
        basis, center = np.eye(3, dtype=np.float32), np.zeros(2, dtype=np.float32)
        first = surface.visibility_index(a[None], basis, center, 1., 16, 16)
        self.assertIs(first, surface.visibility_index(a[None], basis, center, 1., 16, 16))
        changed = a.copy(); changed[0, 0] += .01
        self.assertNotEqual(first['key'], surface.visibility_index(changed[None], basis, center, 1., 16, 16)['key'])
        self.assertNotEqual(first['key'], surface.visibility_index(a[None], basis, center, 2., 16, 16)['key'])


class BilinearProposalTests(unittest.TestCase):
    def test_opaque_corners_and_half_center_are_exact(self):
        image = np.array([[[20, 40, 60, 255], [120, 140, 160, 255]],
                          [[40, 60, 80, 255], [140, 160, 180, 255]]], np.uint8)
        np.testing.assert_array_equal(surface._sample_overlay_premultiplied(image, 0., 0.), [20, 40, 60, 1])
        np.testing.assert_array_equal(surface._sample_overlay_premultiplied(image, 1., 1.), [140, 160, 180, 1])
        np.testing.assert_array_equal(surface._sample_overlay_premultiplied(image, .5, .5), [80, 100, 120, 1])

    def test_hidden_rgb_in_transparent_neighbor_cannot_create_halo(self):
        image = np.array([[[200, 20, 40, 255], [0, 255, 255, 0]]], np.uint8)
        np.testing.assert_array_equal(surface._sample_overlay_premultiplied(image, .5, 0.), [100, 10, 20, .5])
        image[0, 1, :3] = [255, 0, 255]
        np.testing.assert_array_equal(surface._sample_overlay_premultiplied(image, .5, 0.), [100, 10, 20, .5])

    def test_transparent_input_remains_zero_premultiplied(self):
        image = np.full((4, 4, 4), [255, 60, 90, 0], np.uint8)
        self.assertEqual(surface._sample_overlay_premultiplied(image, 1.4, 2.1), (0., 0., 0., 0.))

    def test_clamp_boundary_does_not_introduce_black_border(self):
        image = np.full((2, 2, 4), [27, 58, 99, 255], np.uint8)
        for x, y in ((-.5, -.5), (1.49, 1.49), (-.2, .7)):
            self.assertEqual(surface._sample_overlay_premultiplied(image, x, y), (27., 58., 99., 1.))

    def test_arbitrary_points_match_independent_float_oracle(self):
        random = np.random.default_rng(421)
        image = random.integers(0, 256, (7, 9, 4), dtype=np.uint8)
        for x, y in random.uniform([-.5, -.5], [8.5, 6.5], (80, 2)):
            xc, yc = np.clip(x, 0, 8), np.clip(y, 0, 6)
            x0, y0 = int(xc), int(yc)
            x1, y1 = min(x0+1, 8), min(y0+1, 6)
            result = np.zeros(4)
            for xi, yi, weight in ((x0, y0, (1-xc+x0)*(1-yc+y0)),
                                   (x1, y0, (xc-x0)*(1-yc+y0)),
                                   (x0, y1, (1-xc+x0)*(yc-y0)),
                                   (x1, y1, (xc-x0)*(yc-y0))):
                value = image[yi, xi].astype(float)
                result += np.r_[value[:3]*value[3]/255, value[3]/255]*weight
            np.testing.assert_allclose(surface._sample_overlay_premultiplied(image, x, y), result, rtol=0, atol=1e-12)

    def test_projection_gradient_uses_pixel_center_coordinates(self):
        world = np.array([[[0,0,0],[1,0,0],[1,1,0]],[[0,0,0],[1,1,0],[0,1,0]]], np.float32)
        uv = world[:, :, :2].copy()
        basis = np.eye(3, dtype=np.float32)
        screen, camera = surface.screen_vertices(world, basis, 128, 128)
        base = np.full((32, 32, 4), [0, 0, 0, 71], np.uint8)
        _, depth, visible = surface.rasterize(screen, world, uv, base, 128, 128)
        overlay = np.zeros((128, 128, 4), np.uint8)
        overlay[:, :, 0] = np.arange(128)[None, :]
        overlay[:, :, 1] = np.arange(128)[:, None]
        overlay[:, :, 3] = 255
        out, score, owners = base.copy(), np.zeros((32,32),np.float32), np.full((32,32),-1,np.int32)
        surface.project_overlay(world, uv, basis, np.asarray(camera['center'],np.float32), camera['scale'],
                                overlay, depth, base, out, score, owners, 3/camera['scale'], .45, visible)
        changed_from_old_nearest = 0
        for y in range(2, 30):
            for x in range(2, 30):
                sx = (x/31-camera['center'][0])*camera['scale']+64
                sy = (camera['center'][1]-(1-y/31))*camera['scale']+64
                expected = [int(max(0,sx-.5)), int(max(0,sy-.5))]
                self.assertEqual(out[y,x,:2].tolist(), expected)
                changed_from_old_nearest += expected != [int(sx),int(sy)]
        self.assertGreater(changed_from_old_nearest, 100)
        np.testing.assert_array_equal(out[:,:,3], base[:,:,3])


if __name__ == '__main__':
    unittest.main()
