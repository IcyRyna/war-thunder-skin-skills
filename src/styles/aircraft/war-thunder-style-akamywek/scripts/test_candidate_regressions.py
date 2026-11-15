import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
from PIL import Image

import airframe_setup
import area_shares
import chart_diagnostics as diagnostic
import design_lint
import legacy_dds
import surface_map
import vector_paint
from test_vector_paint import islands


class Regressions(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.geo = self.root / "model.npz"
        self.src = self.root / "square.png"
        Image.new("RGBA", (64, 64), (20, 40, 230, 255)).save(self.src)
        self.base = self.root / "base.png"
        Image.new("RGBA", (64, 64), (44, 45, 46, 117)).save(self.base)

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), "utf8")
        return path

    def design(self, charts, layers, **options):
        return dict(
            schema_version=1,
            atlas=dict(width=64, height=64),
            supersample=1,
            charts=charts,
            layers=layers,
            **options,
        )

    def bake(self, d, name, mask=None):
        out = self.root / name
        result = vector_paint.run(
            SimpleNamespace(
                geometry=self.geo,
                design=self.write(name + ".json", d),
                base=self.base,
                protect=mask,
                out=out,
            )
        )
        return np.array(Image.open(out / "composite.png")), result

    def test_shared_uv_applies_to_vector_image_and_text(self):
        islands(self.geo, [(-3, -1, -1, 1, 0, 1, 0, 1), (1, 3, -1, 1, 0, 1, 0, 1)])
        charts = [
            dict(id=n, u="x", v="z", where={"x": bounds})
            for n, bounds in (("first", [-4, 0]), ("second", [0, 4]))
        ]
        field = dict(
            name="paint",
            items=[
                dict(
                    id="red",
                    type="polygon",
                    chart="first",
                    points=[[-4, -2], [0, -2], [0, 2], [-4, 2]],
                    fill="#ff0000",
                )
            ],
        )
        detail = dict(
            name="portraits",
            images=[
                dict(id="lower-priority", source=self.src.name, chart="second", width=3, center=[2, 0])
            ],
        )
        image, record = self.bake(self.design(charts, [field, detail]), "blocked")
        self.assertEqual(image[32, 32].tolist(), [255, 0, 0, 117])
        self.assertIn("lower-priority", record["zero_hit_items"])
        item = record["images"][0]
        self.assertGreater(item["nonowner_samples"], 0)
        self.assertEqual(item["sample_hits"], 0)
        self.assertEqual(item["candidate_samples"], item["nonowner_samples"])
        # Same successful placement when the chart order deliberately changes.
        image, _ = self.bake(self.design(charts[::-1], [field, detail]), "reversed")
        self.assertEqual(image[32, 32].tolist(), [20, 40, 230, 117])
        # Text is rasterized and follows the same ownership.
        text = dict(
            name="text", images=[dict(id="type", text="ABC", chart="second", center=[2, 0], height=0.4)]
        )
        _, record = self.bake(self.design(charts, [field, text]), "text")
        self.assertIn("type", record["zero_hit_items"])

    def test_protected_gutter_and_ordinary_bleed(self):
        islands(self.geo, [(-1, 1, -1, 1, 0.25, 0.75, 0.25, 0.75)])
        mask = np.zeros((64, 64), np.uint8)
        mask[:, 12:16] = 255
        mask[24:30, 30:34] = 255
        m = self.root / "mechanical.png"
        Image.fromarray(mask).save(m)
        item = dict(
            id="field",
            chart="wing",
            type="polygon",
            points=[[-2, -2], [2, -2], [2, 2], [-2, 2]],
            fill="#ff2244",
        )
        charts = [dict(id="wing", u="x", v="z")]
        layers = [dict(name="field", items=[item])]
        plain, _ = self.bake(self.design(charts, layers, bleed_px=0), "plain", m)
        extended, rec = self.bake(self.design(charts, layers, bleed_px=4), "extended", m)
        self.assertTrue(np.all(extended[mask > 0] == [44, 45, 46, 117]))
        self.assertTrue(np.all(plain[:, :, 3] == extended[:, :, 3]))
        self.assertTrue(np.any(extended[mask == 0] != plain[mask == 0]))
        self.assertGreater(rec["items"][0]["protected_samples"], 0)
        layer = np.asarray(Image.open(self.root / "extended/layers/01-field.png"))
        self.assertFalse(layer[:, :, 3][mask > 0].any())

    def test_partial_triangle_and_physical_location(self):
        geom = dict(
            triangles=np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]] * 2),
            uvs=np.array([[[0.1, 0.1], [0.3, 0.1], [0.1, 0.3]], [[0.1, 0.1], [0.9, 0.1], [0.1, 0.9]]]),
        )
        classes = surface_map.classify(
            geom, np.array([0, 1]), np.array([[0, 0, 2, 0]] * 2), None, atlas=128
        )
        self.assertEqual(classes[1], surface_map.SHARED)
        islands(self.geo, [(-1, 1, -1, 1, 0, 1, 0, 1)])
        frame = dict(origin=[31.5, 31.5], x=[-31.5, 0], y=[0, -31.5])
        charts = [dict(id="top", u="x", v="z", frame=frame)]
        mark = dict(
            chart="top",
            id="mark",
            type="polygon",
            fill="#ffffff",
            points=[[-0.8, -0.2], [-0.3, -0.2], [-0.3, 0.2], [-0.8, 0.2]],
        )
        mask = np.zeros((64, 64), np.uint8)
        mask[:, 34:] = 255
        m = self.root / "guard.png"
        Image.fromarray(mask).save(m)
        d = self.design(charts, [dict(name="marks", items=[mark])])
        report = surface_map.run(
            SimpleNamespace(
                geometry=self.geo,
                design=self.write("fr.json", d),
                out=self.root / "fr",
                protect=m,
                chart=[],
                scale=96.0,
                threshold=0.15,
            )
        )
        self.assertGreater(report["charts"]["top"]["items"][0]["ground"]["protected"], 0.98)

    def test_square_alpha_crop_flip_clip_focus(self):
        rgba = np.zeros((64, 64, 4), np.uint8)
        rgba[8:52, 5:25, 3] = 255
        Image.fromarray(rgba).save(self.src)
        spec = dict(
            id="face", source=self.src.name, chart="wing", center=[0, 0], width=7.1, flip=True, rotation=0
        )

        def shapes(**extra):
            design = self.design(
                [dict(id="wing", u="x", v="z")],
                [dict(name="art", images=[dict(spec, **extra)])],
                inspection_regions=[dict(chart="wing", item="face", name="eyes", box=[0, 0, 0.4, 0.5])],
            )
            return diagnostic.footprints(design, {"wing"}, self.root)

        y, x = np.mgrid[-4:4:0.05, -4:4:0.05]
        plain, eyes = shapes()
        cropped, _ = shapes(crop=[0, 0, 64, 64])
        self.assertAlmostEqual(np.ptp(plain[3][:, 1]), 7.1)
        mask = diagnostic.footprint_mask(plain, x, y)
        np.testing.assert_array_equal(mask, diagnostic.footprint_mask(cropped, x, y))
        self.assertGreater(x[mask].mean(), 0)
        focus = diagnostic.footprint_mask(eyes, x, y)
        self.assertTrue(focus.any())
        self.assertFalse((focus & ~mask).any())
        clipped, _ = shapes(clip=[[0, 0], [4, 0], [4, 4], [0, 4]])
        mask = diagnostic.footprint_mask(clipped, x, y)
        self.assertGreaterEqual(y[mask].min(), -0.001)
        self.assertLess(mask.sum(), focus.size // 3)

    def test_palette_gradient_roles_and_no_seven_view_side_effect(self):
        palette = {
            "swatches": {"dark": ["#333334"], "signature": ["#219eaf", ["#a5c69b", "#dfd44f"]]},
            "max_rgb_distance": 3,
        }
        idx = area_shares.palette_index(palette)
        colors = np.array(
            [
                [
                    [33, 158, 175],
                    [165, 198, 155],
                    [223, 212, 79],
                    [194, 205, 117],
                    [165, 198, 155],
                    [165, 198, 155],
                    [0, 0, 255],
                ]
            ],
            np.uint8,
        )
        roles = np.array([[0, 0, 0, 0, 5, 6, 0]], np.uint8)
        mask = np.ones((1, 7), bool)
        rep = area_shares.measure(colors, mask, roles, idx)
        self.assertEqual(
            (
                rep["pixels"]["signature"],
                rep["pixels"]["portrait"],
                rep["pixels"]["mechanical"],
                rep["pixels"]["other"],
            ),
            (4, 1, 1, 1),
        )
        for view in ("top", "bottom", "left", "right", "front", "rear", "iso"):
            Image.fromarray(colors).save(self.root / (view + ".png"))
            Image.fromarray(mask).save(self.root / (view + "-mask.png"))
        spec = self.write("palette.json", palette)
        with contextlib.redirect_stdout(io.StringIO()):
            airframe_setup.main(["shares", "--views", str(self.root), "--palette", str(spec)])
        self.assertTrue((self.root / "area-shares.json").is_file())
        self.assertFalse((self.root / "seven.png").exists())

    def test_strict_header_and_transactional_retry(self):
        with self.assertRaises(ValueError):
            with patch.object(legacy_dds, "check", side_effect=ValueError("injected")):
                legacy_dds.export(self.src, self.root / "body.dds")
        file = self.root / "body.dds"
        self.assertFalse(file.exists())
        ok = legacy_dds.export(self.src, file)
        self.assertTrue(ok["source_rgba_exact"])
        original = file.read_bytes()
        for offset, val in ((8, 0), (24, 7)):
            data = bytearray(original)
            struct.pack_into("<I", data, offset, val)
            file.write_bytes(data)
            with self.assertRaises(ValueError):
                legacy_dds.check(file)

    def test_native_layer_roles_require_matching_camera_and_depth(self):
        from surface_preview import camera_fingerprint

        xyz = np.array([[[-1, -1, 0], [1, -1, 0], [-1, 1, 0]]], np.float32)
        uv = np.array([[[0, 0], [1, 0], [0, 1]]], np.float32)
        np.savez(
            self.geo,
            triangles=xyz,
            uvs=uv,
            node_ids=np.array([0]),
            names=np.array(["mesh"]),
            material_names=np.array(["body"]),
            material_resources=np.array(["[]"]),
            material_ids=np.array([0]),
        )
        role = np.full((8, 8), 255, np.uint8)
        Image.fromarray(role).save(self.root / "wing.png")
        role[:] = 0
        role[:, 0:4] = 255
        Image.fromarray(role).save(self.root / "face.png")
        spec = self.write(
            "layers.json",
            {
                "geometry": self.geo.name,
                "atlas_materials": ["body"],
                "layers": [
                    {"role": "portrait", "mask": "face.png"},
                    {"role": "signature", "mask": "wing.png"},
                ],
            },
        )
        bundle = area_shares.layer_atlas(spec)
        meta = dict(basis=np.eye(3).tolist(), center=[0, 0], scale=4, width=8, height=8)
        image = self.root / "top.png"
        Image.new("RGB", (8, 8)).save(image)
        yy, xx = np.indices((8, 8))
        mask = yy >= xx
        camera = camera_fingerprint(meta)
        geo = bundle[0]["_sha256"]
        depth = self.root / "top-depth.npz"
        np.savez(
            depth,
            owners=np.where(mask, 0, -1).astype(np.int32),
            camera_sha256=np.array(camera),
            geometry_sha256=np.array(geo),
        )
        meta.update(
            camera_sha256=camera,
            geometry_sha256=geo,
            image_sha256=area_shares.sha(image),
            depth_sha256=area_shares.sha(depth),
        )
        self.write("top.json", meta)
        actual, _ = area_shares.project_roles(bundle, self.root, "top", image, mask)
        self.assertEqual(actual[6, 1], 5)
        self.assertEqual(actual[6, 5], 2)
        self.assertEqual(actual[0, 7], 0)
        meta["center"] = [1, 0]
        self.write("top.json", meta)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            area_shares.project_roles(bundle, self.root, "top", image, mask)

    def test_face_box_and_clothing_are_reported_separately_on_a_seam(self):
        # A slightly raised strip physically occludes the same chart at the centre.
        from test_surface_map import quad

        top, u = quad(-1, 1, -1, 1, 0, True, (0, 0, 0.8, 0.8))
        lid, v = quad(-0.025, 0.025, -1, 1, 0.2, True, (0.8, 0.8, 1, 1))
        np.savez(
            self.geo,
            triangles=np.array(top + lid, np.float32),
            uvs=np.array(u + v, np.float32),
            names=np.array(["wing", "lid"]),
            node_ids=np.array([0, 0, 1, 1], np.int32),
        )
        chart = dict(id="wing", u="x", v="z", nodes=["wing"], facing="y")
        art = dict(id="art", chart="wing", source=self.src.name, width=2, center=[0, 0])
        regions = [
            dict(item="art", chart="wing", name=n, box=b)
            for n, b in (("eyes", [0.45, 0.4, 0.55, 0.6]), ("sleeve", [0.75, 0.4, 0.85, 0.6]))
        ]
        d = self.design([chart], [dict(name="art", images=[art])], inspection_regions=regions)
        rep = surface_map.run(
            SimpleNamespace(
                geometry=self.geo,
                design=self.write("focus.json", d),
                out=self.root / "focus",
                protect=None,
                chart=[],
                scale=100.0,
                threshold=0.15,
            )
        )
        rows = {r["id"] for r in rep["seam_items"]}
        self.assertIn("art/eyes", rows)
        self.assertNotIn("art/sleeve", rows)
        self.assertNotIn("art", rows)

    def test_intent_explains_only_matching_gradient_and_echo(self):
        chart = dict(id="a", u="x", v="z")
        echo = dict(
            id="white-echo",
            chart="a",
            type="polygon",
            fill="#ececec",
            points=[[0, 0], [1, 0], [1, 1], [0, 1]],
            holes=[[[0.005, 0.005], [0.995, 0.005], [0.995, 0.995], [0.005, 0.995]]],
        )
        item = dict(
            id="field",
            chart="a",
            type="polygon",
            points=[[1, 0], [2, 0], [2, 1]],
            fill={"gradient": {"from": [0, 0], "to": [1, 1], "colors": ["jade", "gold"]}},
        )
        d = self.design([chart], [dict(name="field", items=[echo, item])])
        d["palette"] = {"jade": "#4b8891", "gold": "#dfd44f"}
        f = self.write("d.json", d)
        intent = {
            "signature_gradients": [["jade", "gold"]],
            "approved_echoes": {"white-echo": design_lint.echo_fingerprint(echo, chart)},
        }

        def levels(intent):
            return {h["code"]: h["level"] for h in design_lint.lint(f, intent)["hits"]}

        self.assertEqual(levels(None)["thin-outline"], "warn")
        self.assertEqual(levels(intent)["thin-outline"], "info")
        self.assertEqual(levels(intent)["hue-shift-gradient"], "info")
        echo["points"][0] = [-0.005, 0]
        self.write("d.json", d)
        self.assertEqual(levels(intent)["thin-outline"], "warn")
