import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("preview", Path(__file__).resolve().parents[1] / "preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreparationTests(unittest.TestCase):
    def test_explicit_game_directory_wins_over_other_installs(self):
        from unittest.mock import patch
        from preview import discover_clients
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('first', 'second'):
                (root / name / 'content').mkdir(parents=True)
                (root / name / 'aces.exe').write_bytes(b'')
            with patch.dict('os.environ', {'WT_CLIENT': str(root / 'second')}):
                self.assertEqual(discover_clients(root / 'first'), [str((root / 'first').resolve())])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = self.root / "input"
        self.model.mkdir()
        self.obj = self.model / "assembly.obj"
        self.obj.write_text("v 0 0 0\nv 2 0 0\nv 0 3 0\nvt -0.25 1.5\nvt 1 0\nvt 0 1\no turret\nusemtl paint\nf -3/-3 -2/-2 -1/-1\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_real_glb_topology_and_out_of_tile_uv_roundtrip(self):
        result = preview.prepare(self.model, self.root / "output")
        data = (self.root / "output/model.glb").read_bytes()
        magic, version, length = struct.unpack_from("<III", data)
        self.assertEqual((magic, version, length), (0x46546C67, 2, len(data)))
        json_size, json_type = struct.unpack_from("<II", data, 12)
        self.assertEqual(json_type, 0x4E4F534A)
        gltf = json.loads(data[20:20 + json_size])
        binary_start = 28 + json_size
        primitive = gltf["meshes"][0]["primitives"][0]
        uv_accessor = gltf["accessors"][primitive["attributes"]["TEXCOORD_0"]]
        uv_view = gltf["bufferViews"][uv_accessor["bufferView"]]
        uv = struct.unpack_from("<6f", data, binary_start + uv_view["byteOffset"])
        self.assertEqual(uv, (-.25, -.5, 1., 1., 0., 0.))
        self.assertEqual(result["triangles"], 1)
        self.assertEqual(gltf["nodes"][0]["name"], "turret")
        self.assertEqual(result["unbound_materials"], ["paint"])

    def test_rejects_invalid_indices_without_publishing_scene(self):
        self.obj.write_text(self.obj.read_text().replace("-1/-1", "900/900"))
        with self.assertRaisesRegex(ValueError, "index outside"):
            preview.prepare(self.model, self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_missing_uv_fails(self):
        self.obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        with self.assertRaisesRegex(ValueError, "UV"):
            preview.prepare(self.model, self.root / "output")

    def test_never_overwrites_input_or_existing_output(self):
        with self.assertRaises(ValueError):
            preview.prepare(self.model, self.model / "preview")
        output = self.root / "output"
        output.mkdir()
        (output / "keep.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            preview.prepare(self.model, output)
        self.assertEqual((output / "keep.txt").read_text(), "keep")

    def test_unknown_material_binding_is_not_silently_ignored(self):
        bindings = self.root / "bindings.json"
        preview.write_json(bindings, {"materials": {"wrong_model": "paint.png"}})
        with self.assertRaisesRegex(ValueError, "不存在的材质"):
            preview.prepare(self.model, self.root / "output", bindings)

    def test_steam_library_discovery_with_spaces(self):
        steam = self.root / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        library = self.root / "Other Library"
        game = library / "steamapps/common/War Thunder"
        (game / "content").mkdir(parents=True)
        (game / "launcher.exe").touch()
        (steam / "steamapps/libraryfolders.vdf").write_text('"path" "' + str(library).replace('\\', '\\\\') + '"')
        self.assertIn(str(game.resolve()), preview.discover_clients(extra=[steam]))

    def test_preview_rgb_preserves_hidden_c_color(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        texture = self.root / "paint.png"
        Image.new("RGBA", (8, 8), (220, 10, 30, 0)).save(texture)
        bindings = self.root / "bindings.json"
        preview.write_json(bindings, {"materials": {"paint": "paint.png"}})
        result = preview.prepare(self.model, self.root / "output", bindings)
        self.assertEqual(result["materials"][0]["color_state"], "bound-rgb-preview")
        data = (self.root / "output/model.glb").read_bytes()
        jlen = struct.unpack_from("<I", data, 12)[0]
        gltf = json.loads(data[20:20+jlen])
        view = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
        from io import BytesIO
        start = 28+jlen+view["byteOffset"]
        image = Image.open(BytesIO(data[start:start+view["byteLength"]]))
        self.assertEqual(image.getpixel((0, 0)), (220, 10, 30))

    def test_stock_camo_uses_raw_c_mask_without_mutating_source(self):
        from PIL import Image
        source=self.root/'raw.png'
        image=Image.new('RGBA',(3,1));image.putdata([(170,40,30,0),(170,40,30,128),(170,40,30,255)]);image.save(source)
        Image.new('RGB',(2,2),(10,90,20)).save(self.root/'camo.png')
        before=preview.digest(source)
        preview.write_json(self.model/'materials.json',{'materials':[{'obj_name':'paint','shader':'dynamic_masked_tank'}]})
        bindings=self.root/'bindings.json'
        preview.write_json(bindings,{'materials':{'paint':'raw.png'},'camo_materials':{'paint':'camo.png'}})
        result=preview.prepare(self.model,self.root/'output',bindings)
        native=Image.open(self.root/'output'/result['materials'][0]['native_file'])
        self.assertEqual(native.getpixel((0,0)),(170,40,30))
        self.assertEqual(native.getpixel((2,0)),(10,90,20))
        self.assertEqual(preview.digest(source),before)
        self.assertEqual(result['materials'][0]['view_mode'],'stock-camo-approx')


if __name__ == "__main__":
    unittest.main()
