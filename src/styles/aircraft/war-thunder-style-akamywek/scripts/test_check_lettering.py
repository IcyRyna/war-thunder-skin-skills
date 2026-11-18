import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image, ImageFont

import check_lettering as lettering
import scene_preview as scene


class LetteringTests(unittest.TestCase):
    def setUp(self):
        container = tempfile.TemporaryDirectory()
        self.addCleanup(container.cleanup)
        self.root = Path(container.name)
        try:
            self.font = str(ImageFont.truetype('DejaVuSans.ttf', 24).path)
        except OSError:
            self.font = str(ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 24).path)

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def fixture(self, blocker=False, crop=False):
        corners = np.array([[-2,-2,0], [2,-2,0], [2,2,0], [-2,2,0]], np.float32)
        tr = np.array([[0,1,2], [0,2,3]])
        shapes = [corners[tr]]
        if blocker:
            shapes.append(corners[tr] + ([2.45,0,1] if blocker == 'partial' else [0,0,1]))
        geometry = self.root / 'geometry.npz'
        uv = (corners[tr, :2] / 8 + .5).astype(np.float32)
        names = ['panel', 'occluder'] if blocker else ['panel']
        np.savez(geometry, triangles=np.concatenate(shapes).astype(np.float32), uvs=np.concatenate([uv]*len(names)),
                 names=np.array(names), node_ids=np.repeat(np.arange(len(names), dtype=np.int32), 2),
                 material_names=np.array(['body']), material_ids=np.zeros(2*len(names), np.int32),
                 material_resources=np.array(['[]']))
        manifest = dict(schema_version=1, geometry=dict(path=geometry.name, sha256=scene.file_hash(geometry)),
                        materials=[dict(id=0, name='body', double_sided=True, base_color=[.3,.3,.3,1])],
                        display_state=dict(description='test panel'), width=200, height=200,
                        cameras=dict(test=dict(basis=np.eye(3).tolist(), center=[1.55 if crop else 0,0],
                                               scale=85 if crop else 42, width=200, height=200)))
        scene.render(self.write('scene.json',manifest), 'test', 'layout', self.root/'test.png')
        return geometry

    def review(self, geometry, *, rotation=0., flipped=False, native=False, expected=0, target='review',
               center=(0,0), clip=None, mirrored_chart=False):
        chart = dict(id='panel', nodes=['panel'], u='x', v='y')
        if native:
            chart['frame'] = dict(origin=[127.5,127.5], x=[-255/8 if mirrored_chart else 255/8,0], y=[0,-255/8])
        text = dict(id='word', chart='panel', text='FS 28', font=self.font, center=list(center),
                    height=.27, rotation=rotation, flip=flipped)
        if clip:
            text['clip'] = clip
        design = dict(schema_version=1, atlas=dict(width=256,height=256), text_pixels_per_metre=600,
                      charts=[chart], layers=[dict(name='type',images=[text])])
        plan = dict(views=dict(view='test.json'), checks=[dict(item='word',view='view',baseline_deg=expected,tolerance_deg=15)])
        return lettering.run(self.write('art.json',design),geometry,self.write('plan.json',plan),
                             self.root/(target+'.json'))['checks'][0]

    def test_deliberate_tilt_in_native_and_world_charts(self):
        geo = self.fixture()
        for native in [False, True]:
            result = self.review(geo, rotation=35, expected=-35, native=native, target='tilt'+str(native))
            self.assertEqual(result['status'], 'pass')
            self.assertAlmostEqual(result['baseline_deg'], -35, places=1)
            self.assertGreater(result['visible_ink_pixels'], 60)
        self.assertEqual(self.review(geo,rotation=35,target='inclined')['status'],'off_axis')

    def test_mirror_is_separate_from_half_turn(self):
        geo = self.fixture()
        self.assertEqual(self.review(geo,flipped=True,target='mirrored')['status'],'mirrored')
        self.assertEqual(self.review(geo,rotation=180,target='flipped-over')['status'],'upside_down')
        self.assertEqual(self.review(geo,native=True,mirrored_chart=True,target='reverse-native')['status'],'mirrored')
        self.assertEqual(self.review(geo,native=True,mirrored_chart=True,flipped=True,target='compensated')['status'],'pass')

    def test_hidden_and_out_of_frame_do_not_pass(self):
        geo = self.fixture(blocker=True)
        hidden = self.review(geo, target='hidden')
        self.assertEqual(hidden['status'],'occluded')
        self.assertGreater(hidden['occluded_ink_samples'], 60)
        self.assertEqual(self.review(geo,center=(8,0),target='no-support')['status'],'undetermined')

    def test_partial_visibility_retains_observable_axes(self):
        geo = self.fixture(blocker='partial')
        partial = self.review(geo)
        self.assertEqual(partial['status'], 'pass')
        self.assertEqual(partial['visibility'], 'partially_occluded')
        self.assertGreater(partial['occluded_ink_samples'], 1)

    def test_real_bake_protected_samples_do_not_discard_the_remaining_orientation(self):
        geo = self.fixture()
        self.review(geo, target='unmasked')
        mask = np.zeros((256,256), np.uint8)
        mask[:, :(123 if 'DejaVuSans' in self.font else 125)] = 255
        protect = self.root/'protect.png'
        Image.fromarray(mask).save(protect)
        art, plan = self.root/'art.json', self.root/'plan.json'
        out = self.root/'bake'
        lettering.paint.run(SimpleNamespace(design=art, geometry=geo, base=None, protect=protect, out=out))
        receipt = out/'receipt.json'
        partial = lettering.run(art, geo, plan, self.root/'painted.json', receipt, protect)['checks'][0]
        self.assertGreater(partial['bake_samples']['protected_samples'], 0)
        self.assertEqual(partial['status'], 'pass')
        self.assertEqual(partial['coverage'], 'partial')
        self.assertGreater(partial['unverified_atlas_ink_samples'], 0)
        unknown = lettering.run(art, geo, plan, self.root/'no-mask.json', receipt)['checks'][0]
        self.assertEqual(unknown['status'], 'undetermined')
        proof = self.root/'reduced-bake'
        lettering.paint.run(SimpleNamespace(design=art, geometry=geo, base=None, protect=protect, out=proof, proof_width=128))
        reviewed = lettering.run(art, geo, plan, self.root/'proof-axes.json', proof/'receipt.json', protect)
        self.assertEqual(reviewed['inspected_raster'], [128,128])
        self.assertEqual(reviewed['native_atlas'], [256,256])
        # At half resolution this mask covers enough extra bilinear footprints
        # that the surviving fragment no longer spans 40% of the word.
        self.assertEqual(reviewed['checks'][0]['status'], 'undetermined')
        self.assertLess(reviewed['checks'][0]['baseline_span_fraction'], .40)

    def test_offscreen_supported_surface_differs_from_no_carrier(self):
        geo = self.fixture(crop=True)
        self.assertEqual(self.review(geo, center=(-1.3,0))['status'], 'out_of_frame')

    def test_stale_render_sidecars_rejected(self):
        geo = self.fixture()
        meta = lettering.read_json(self.root/'test.json')
        meta['scale'] *= 2
        self.write('test.json',meta)
        with self.assertRaisesRegex(ValueError,'camera fingerprint'):
            self.review(geo)


if __name__ == '__main__':
    unittest.main()
