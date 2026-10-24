#!/usr/bin/env python3
"""Local, Blender-free model preparation and browser preview. Python 3.10+."""
from __future__ import annotations

import argparse
from array import array
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import urllib.parse

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def discover_clients(explicit=None, extra=()):
    """Bounded discovery: environment, Steam registry/libraries and common roots."""
    candidates = [Path(explicit)] if explicit else []
    if os.environ.get("WT_CLIENT"):
        candidates.append(Path(os.environ["WT_CLIENT"]))
    steam_roots = []
    if os.name == "nt":
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as reg:
                    steam_roots.append(Path(winreg.QueryValueEx(reg, value)[0]))
            except OSError:
                continue
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\War Thunder") as reg:
                candidates.append(Path(winreg.QueryValueEx(reg, "InstallLocation")[0]))
        except OSError:
            pass
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(var):
            base = Path(os.environ[var])
            steam_roots.append(base / "Steam")
            candidates.append(base / "War Thunder")
    for base in [*steam_roots, *(Path(p) for p in extra)]:
        candidates.append(base / "steamapps/common/War Thunder")
        library = base / "steamapps/libraryfolders.vdf"
        if library.is_file():
            for match in re.finditer(r'"path"\s*"([^"\r\n]+)"', library.read_text(encoding="utf-8-sig")):
                candidates.append(Path(match[1].replace("\\\\", "\\")) / "steamapps/common/War Thunder")
    for drive in ("C:/", "D:/", "E:/", "F:/"):
        for suffix in ("Games/War Thunder", "Games/WarThunder", "WarThunder", "SteamLibrary/steamapps/common/War Thunder"):
            candidates.append(Path(drive) / suffix)
    valid = {}
    for path in candidates:
        path = path.expanduser().resolve()
        if (path / "content").is_dir() and any((path / p).is_file() for p in ("aces.exe", "win64/aces.exe", "launcher.exe")):
            valid[os.path.normcase(str(path))] = str(path)
    if explicit and os.path.normcase(str(Path(explicit).resolve())) not in valid:
        raise ValueError("指定目录不是可识别的战雷客户端（需要 content 和 aces/launcher）")
    return list(valid.values())


def extractor_path(explicit=None):
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():
            raise FileNotFoundError("资源提取入口不存在: " + str(path))
        return path
    local = ROOT / "extractor/wt_assets.py"
    if local.is_file() and (local.parent / "vendor/dagor-asset-explorer/src/dae/parse/realres.py").is_file():
        return local
    for parent in ROOT.parents:
        path = parent / "war-thunder-skins/tools/war-thunder-assets/wt_assets.py"
        if path.is_file():
            return path
    return local if local.is_file() else None


def decoder_python(extractor, explicit=None):
    if explicit:
        return str(Path(explicit).resolve())
    for path in (extractor.parent / ".venv/Scripts/python.exe", extractor.parent / ".venv/bin/python"):
        if path.is_file():
            return str(path)
    return sys.executable


def obj_groups(path):
    """Stream OBJ into indexed mesh/material groups; retain source topology and UVs."""
    positions, uvs, normals = [], [], []
    groups = {}
    node, material = "model", "unbound"

    def index(text, sequence):
        n = int(text)
        if n == 0:
            raise ValueError("OBJ index zero")
        n = n - 1 if n > 0 else len(sequence) + n
        if not 0 <= n < len(sequence):
            raise ValueError("OBJ index outside declared array")
        return n

    with Path(path).open(encoding="utf-8-sig") as source:
        for number, line in enumerate(source, 1):
            fields = line.split("#", 1)[0].split()
            if not fields:
                continue
            kind, values = fields[0], fields[1:]
            try:
                if kind in ("v", "vt", "vn"):
                    count = 2 if kind == "vt" else 3
                    row = tuple(float(v) for v in values[:count])
                    if len(row) != count or not all(math.isfinite(v) and abs(v) < 1e15 for v in row):
                        raise ValueError("Invalid/nonfinite OBJ attribute")
                    {"v": positions, "vt": uvs, "vn": normals}[kind].append(row)
                elif kind == "o":
                    node = " ".join(values) or "model"
                elif kind == "g" and node == "model":
                    node = " ".join(values) or "model"
                elif kind == "usemtl":
                    material = " ".join(values) or "unbound"
                elif kind == "f":
                    if len(values) != 3:
                        raise ValueError("仅接受三角形 OBJ；不能静默改变多边形拓扑")
                    group = groups.setdefault((node, material), {"remap": {}, "p": array("f"), "uv": array("f"), "n": array("f"), "i": array("I"), "has_normals": True})
                    for value in values:
                        raw = value.split("/")
                        if len(raw) < 2 or not raw[1]:
                            raise ValueError("面缺少原生 UV，不能作为涂装验收模型")
                        pi, ti = index(raw[0], positions), index(raw[1], uvs)
                        ni = index(raw[2], normals) if len(raw) > 2 and raw[2] else None
                        key = (pi, ti, ni)
                        if key not in group["remap"]:
                            group["remap"][key] = len(group["remap"])
                            group["p"].extend(positions[pi])
                            u, v = uvs[ti]
                            # glTF has top-left texture origin. Inspector restores the original OBJ UV.
                            group["uv"].extend((u, 1 - v))
                            group["n"].extend(normals[ni] if ni is not None else (0, 0, 0))
                            group["has_normals"] &= ni is not None
                        group["i"].append(group["remap"][key])
            except (ValueError, IndexError, OverflowError) as exc:
                raise ValueError(f"OBJ 第 {number} 行: {exc}") from exc
    if not groups:
        raise ValueError("OBJ 没有带 UV 的三角面")
    return groups


def prepare(model_dir, output, bindings=None, max_texture=1024):
    """Generate an uncompressed GLB cache with embedded RGB preview images."""
    model_dir, output = Path(model_dir).resolve(), Path(output).resolve()
    obj = model_dir / "assembly.obj"
    if not obj.is_file():
        raise FileNotFoundError("需要现有导出模型目录中的 assembly.obj")
    if output == model_dir or model_dir in output.parents:
        raise ValueError("输出必须在模型输入目录之外")
    if output.exists():
        raise FileExistsError("输出已存在，请使用新的版本目录: " + str(output))
    source_materials = read_json(model_dir / "materials.json").get("materials", []) if (model_dir / "materials.json").is_file() else []
    binding_data = read_json(bindings) if bindings else {}
    mapping = binding_data.get("materials", {})
    if not isinstance(mapping, dict):
        raise ValueError("bindings.materials 必须为 材质名:颜色图路径 的对象")
    groups = obj_groups(obj)
    names = list(dict.fromkeys(material for _, material in groups))
    unknown = set(mapping) - set(names)
    if unknown:
        raise ValueError("绑定文件包含模型不存在的材质: " + ", ".join(sorted(unknown)))
    gltf = {"asset": {"version": "2.0", "generator": "wt-web-preview candidate"},
            "scene": 0, "scenes": [{"nodes": [], "extras": {"source_obj_sha256": digest(obj)}}], "nodes": [], "meshes": [], "materials": [],
            "buffers": [{"byteLength": 0}], "bufferViews": [], "accessors": [],
            "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]}
    binary = bytearray()

    def view(data, target=None):
        while len(binary) % 4:
            binary.append(0)
        row = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
        if target:
            row["target"] = target
        binary.extend(data)
        gltf["bufferViews"].append(row)
        return len(gltf["bufferViews"]) - 1

    def accessor(values, width, kind, component=5126, bounds=False):
        if sys.byteorder != "little":
            values.byteswap()
        row = {"bufferView": view(values.tobytes(), 34963 if component == 5125 else 34962),
               "componentType": component, "count": len(values) // width, "type": kind}
        if bounds:
            row["min"] = [min(values[axis::width]) for axis in range(width)]
            row["max"] = [max(values[axis::width]) for axis in range(width)]
        gltf["accessors"].append(row)
        return len(gltf["accessors"]) - 1

    records, image_cache, native_images = [], {}, {}
    for name in names:
        source = next((r for r in source_materials if r.get("obj_name") == name or r.get("name") == name), {})
        texture_path = None
        if name in mapping:
            texture_path = (Path(bindings).resolve().parent / mapping[name]).resolve()
        elif source.get("albedo_proxy"):
            texture_path = (model_dir / source["albedo_proxy"]).resolve()
            if not texture_path.is_relative_to(model_dir):
                raise ValueError("模型的 albedo_proxy 路径越界")
        pbr = {"baseColorFactor": [1, 1, 1, 1] if texture_path else [.32, .35, .31, 1], "metallicFactor": 0, "roughnessFactor": .85}
        record = {"name": name, "shader": source.get("shader"), "texture_slots": source.get("texture_slots", []),
                  "color_state": "unbound", "material_simulation": "generic-pbr; not Dagor shader",
                  "source_quality": binding_data.get("source_quality", {}).get(name, "user-supplied" if name in mapping else "unclassified")}
        if texture_path:
            if not texture_path.is_file():
                raise FileNotFoundError("材质颜色图不存在: " + str(texture_path))
            from io import BytesIO
            from PIL import Image, ImageStat
            camo_path = (Path(bindings).resolve().parent / binding_data["camo_materials"][name]).resolve() if bindings and name in binding_data.get("camo_materials", {}) else None
            cache_key=(str(texture_path),str(camo_path))
            camo_record={}
            if cache_key not in image_cache:
                with Image.open(texture_path) as image:
                    original_size = list(image.size)
                    rgba=image.convert("RGBA")
                    image = image.convert("RGB")
                    if camo_path:
                        if source.get("shader") != "dynamic_masked_tank":
                            raise ValueError("Stock camo blending is only declared for dynamic_masked_tank")
                        with Image.open(camo_path) as camo_image:
                            color=tuple(round(value) for value in ImageStat.Stat(camo_image.convert("RGB")).mean)
                        # Baseline geometry/placement preview. UV2 tiling and the full Dagor
                        # lighting/material model are not available in this OBJ export.
                        image=Image.composite(Image.new("RGB", image.size, color), image, rgba.getchannel("A"))
                        camo_record={"view_mode":"stock-camo-approx", "camo_sha256":digest(camo_path),
                                     "camo_mean_rgb":list(color),"blend":"mix(raw C RGB, mean slot1 RGB, raw C A)"}
                    native_stream = BytesIO()
                    image.save(native_stream, format="PNG")
                    native_name = f"native-color-{len(native_images):03d}.png"
                    native_images[native_name] = native_stream.getvalue()
                    image.thumbnail((max_texture, max_texture), Image.Resampling.LANCZOS)
                    stream = BytesIO()
                    image.save(stream, format="PNG")
                    pixel_size = list(image.size)
                image_id = len(gltf.setdefault("images", []))
                gltf["images"].append({"bufferView": view(stream.getvalue()), "mimeType": "image/png"})
                texture_id = len(gltf.setdefault("textures", []))
                gltf["textures"].append({"sampler": 0, "source": image_id})
                image_cache[cache_key] = (texture_id, original_size, pixel_size, native_name, camo_record)
            texture_id, original_size, pixel_size, native_name, camo_record = image_cache[cache_key]
            pbr["baseColorTexture"] = {"index": texture_id}
            record.update(color_state="bound-rgb-preview", source_sha256=digest(texture_path),
                          source_size=original_size, preview_size=pixel_size, source_name=texture_path.name,
                          native_file=native_name, native_sha256=hashlib.sha256(native_images[native_name]).hexdigest())
            record.update(camo_record or {"view_mode":"fixed-color-rgb"})
        gltf["materials"].append({"name": name, "pbrMetallicRoughness": pbr, "doubleSided": True,
                                  "extras": {"source": record}})
        records.append(record)
    node_meshes = {}
    triangles, vertices = 0, 0
    for (node, material), group in groups.items():
        attributes = {"POSITION": accessor(group["p"], 3, "VEC3", bounds=True), "TEXCOORD_0": accessor(group["uv"], 2, "VEC2")}
        if group["has_normals"]:
            attributes["NORMAL"] = accessor(group["n"], 3, "VEC3")
        primitive = {"attributes": attributes, "indices": accessor(group["i"], 1, "SCALAR", 5125), "material": names.index(material), "mode": 4}
        if node not in node_meshes:
            node_meshes[node] = len(gltf["meshes"])
            gltf["meshes"].append({"name": node, "primitives": []})
            gltf["nodes"].append({"name": node, "mesh": node_meshes[node]})
            gltf["scenes"][0]["nodes"].append(len(gltf["nodes"]) - 1)
        gltf["meshes"][node_meshes[node]]["primitives"].append(primitive)
        triangles += len(group["i"]) // 3
        vertices += len(group["p"]) // 3
    gltf["buffers"][0]["byteLength"] = len(binary)
    json_chunk = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode()
    json_chunk += b" " * (-len(json_chunk) % 4)
    binary += b"\0" * (-len(binary) % 4)
    glb = struct.pack("<III", 0x46546C67, 2, 28 + len(json_chunk) + len(binary))
    glb += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    glb += struct.pack("<II", len(binary), 0x004E4942) + binary
    output.mkdir(parents=True)
    (output / "model.glb").write_bytes(glb)
    for name, payload in native_images.items():
        (output / name).write_bytes(payload)
    result = {"schema_version": 1, "model": "model.glb", "label": read_json(model_dir / "summary.json").get("model", model_dir.name) if (model_dir / "summary.json").is_file() else model_dir.name,
              "source_obj_sha256": digest(obj), "source_obj_bytes": obj.stat().st_size, "glb_bytes": len(glb), "glb_sha256": digest(output / "model.glb"),
              "triangles": triangles, "vertices": vertices, "nodes": len(node_meshes), "materials": records,
              "uv_convention": "OBJ original u,v => glTF u,1-v; inspector restores OBJ UV",
              "geometry": "Full selected LOD; no decimation; float32 attributes; static assembled bind pose",
              "unbound_materials": [r["name"] for r in records if r["color_state"] == "unbound"],
              "thumbnail_materials": [r["name"] for r in records if r["source_quality"] == "thumbnail-only"],
              "verification": {"geometry": "converted", "visual": "unreviewed", "game": "not_run"}}
    write_json(output / "scene.json", result)
    return result


class PreviewHandler(SimpleHTTPRequestHandler):
    """Serve only viewer assets and the two prepared scene files over loopback."""
    def __init__(self, *args, scene=None, api=None, **kwargs):
        self.scene_dir = Path(scene).resolve() if scene else None
        self.api=api
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def do_GET(self):
        route = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        host = self.headers.get("Host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]"):
            self.send_error(403, "Loopback host required")
            return
        if self.api and self.api.get(self,route):return
        if route.startswith("/scene/"):
            leaf = route.removeprefix("/scene/")
            allowed = {"scene.json", "model.glb"}
            if self.scene_dir and (self.scene_dir / "scene.json").is_file():
                allowed.update(row["native_file"] for row in read_json(self.scene_dir / "scene.json").get("materials", [])
                               if re.fullmatch(r"native-color-[0-9]+\.png", row.get("native_file", "")))
            if not self.scene_dir or leaf not in allowed:
                self.send_error(404)
                return
            path = self.scene_dir / leaf
        else:
            path = (ROOT / "web" / route.lstrip("/")).resolve()
            if not path.is_relative_to((ROOT / "web").resolve()):
                self.send_error(403)
                return
            if route == "/":
                path /= "index.html"
        if path.is_symlink() or not path.is_file():
            self.send_error(404)
            return
        # The candidate viewer's root must not contain symlinked parent directories.
        base = self.scene_dir if route.startswith("/scene/") else ROOT / "web"
        if not path.resolve().is_relative_to(base.resolve()):
            self.send_error(403)
            return
        self.send_response(200)
        self.send_header("Content-Type", {".js": "text/javascript", ".glb": "model/gltf-binary"}.get(path.suffix, self.guess_type(str(path))))
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with path.open("rb") as stream:
            import shutil
            shutil.copyfileobj(stream, self.wfile)

    def do_HEAD(self):
        self.send_error(405)

    def do_POST(self):
        if self.api:self.api.post(self,urllib.parse.urlsplit(self.path).path)
        else:self.send_error(405)


def serve(scene=None, port=0, work_dir=None, game_dir=None, extractor=None):
    if scene and not (Path(scene) / "scene.json").is_file():
        raise FileNotFoundError("场景目录缺少 scene.json")
    if not (ROOT / "web/vendor/three.module.js").is_file():
        raise FileNotFoundError("缺少固定版 Web 依赖，请运行 tools/vendor_web.py")
    from local_api import LocalAPI
    clients=discover_clients(game_dir) if work_dir else []
    game=Path(clients[0]) if len(clients)==1 else None
    if work_dir and any(Path(work_dir).resolve().is_relative_to(Path(client)) for client in clients):raise ValueError('导入工作目录不能放在战雷目录内')
    decoder=extractor_path(extractor) if work_dir else None
    api=LocalAPI(ROOT,work_dir,game,decoder,decoder_python(decoder) if decoder else None)
    with ThreadingHTTPServer(("127.0.0.1", port), partial(PreviewHandler, scene=scene,api=api)) as server:
        url = f"http://127.0.0.1:{server.server_port}/" + ("?scene=/scene/scene.json" if scene else "")
        print(json.dumps({"ok": True, "url": url, "stop": "Ctrl+C"}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:api.close()


def initialize(args):
    clients = discover_clients(args.client)
    if len(clients) != 1:
        raise ValueError("需要唯一客户端；用 --client 选择。发现: " + json.dumps(clients, ensure_ascii=False))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.vehicle):
        raise ValueError("--vehicle 使用精确内部资源 ID，例如 ztz_99a")
    extractor = extractor_path(args.extractor)
    if extractor is None:
        raise FileNotFoundError("资源解码组件缺失；运行 extractor/setup.ps1 或指定 --extractor wt_assets.py")
    out = args.out.resolve()
    client = Path(clients[0])
    if out == client or out.is_relative_to(client):
        raise ValueError("初始化输出必须在游戏目录以外")
    if out.exists():
        raise FileExistsError("初始化使用新的输出目录，不覆盖已有模型或设计")
    command = [decoder_python(extractor, args.python), "-B", str(extractor), "model", str(client),
               "--name", args.vehicle, "--lod", str(args.lod), "--out", str(out / "source-model")]
    if args.template:
        command += ["--template", str(args.template.resolve())]
    else:
        # Do not guess from a similar template name: resource identity is exact.
        expected = client / "UserSkins" / ("template_" + args.vehicle)
        if expected.is_dir():
            command += ["--template", str(expected)]
    out.mkdir(parents=True)
    with (out / "initialization.log").open("w", encoding="utf-8") as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=900, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if process.returncode:
        raise RuntimeError("模型解码失败，保留诊断: " + str(out / "initialization.log"))
    binding_path = args.bindings
    if not binding_path and not args.no_native_textures:
        command = [decoder_python(extractor, args.python), "-B", str(ROOT / "tools/auto_textures.py"),
                   "--extractor", str(extractor), "--client", str(client), "--model-dir", str(out / "source-model"),
                   "--out", str(out / "color-cache")]
        with (out / "texture-initialization.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=900,
                                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if process.returncode:
            raise RuntimeError("纹理自动提取失败，模型已保留；查看 texture-initialization.log，或用 --no-native-textures 明确检查灰模")
        binding_path = out / "color-cache/bindings.json"
    result = prepare(out / "source-model", out / "scene", binding_path, args.max_texture)
    write_json(out / "initialization.json", {"vehicle": args.vehicle, "lod": args.lod, "client": str(client),
               "extractor_sha256": digest(extractor), "scene": "scene/scene.json", "state": "ready",
               "missing_color_materials": result["unbound_materials"]})
    if args.serve:
        serve(out/'scene',args.port,out/'imports',client,extractor)
    else:
        print(json.dumps({"ok": True, "scene": str(out / "scene"), "unbound_materials": result["unbound_materials"]}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Discover client and decoder without writes")
    doctor.add_argument("--game-dir", "--client", dest="client", help="War Thunder installation folder; never launches game")
    doctor.add_argument("--extractor")
    init = sub.add_parser("init", help="Find client, decode exact vehicle, prepare Web scene")
    init.add_argument("--vehicle", required=True)
    init.add_argument("--game-dir", "--client", dest="client", help="Read models from installation folder; never launches game")
    init.add_argument("--extractor")
    init.add_argument("--python")
    init.add_argument("--template", type=Path)
    init.add_argument("--no-native-textures", action="store_true", help="Explicit geometry-only inspection")
    init.add_argument("--lod", type=int, choices=range(4), default=1)
    init.add_argument("--out", type=Path, required=True)
    init.add_argument("--serve", action="store_true")
    init.add_argument("--port", type=int, default=0)
    convert = sub.add_parser("prepare", help="Convert existing native OBJ export to compact Web scene")
    convert.add_argument("--model-dir", type=Path, required=True)
    convert.add_argument("--out", type=Path, required=True)
    for command in (init, convert):
        command.add_argument("--bindings", type=Path, help="JSON materials mapping; paths relative to JSON")
        command.add_argument("--max-texture", type=int, choices=(512, 1024, 2048, 4096), default=1024)
    server = sub.add_parser("serve", help="Loopback-only viewer; prints URL as JSON")
    server.add_argument("--scene", type=Path)
    server.add_argument("--port", type=int, default=0)
    server.add_argument('--work-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'WT-Paint-Workbench/imports',help='本地 ZIP/文件夹导入工作目录，默认位于用户应用数据目录')
    server.add_argument('--game-dir',type=Path)
    server.add_argument('--extractor',type=Path)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            extractor = extractor_path(args.extractor)
            print(json.dumps({"game_directories": discover_clients(args.client), "extractor": str(extractor) if extractor else None,
                  "decoder_python": decoder_python(extractor) if extractor else None, "blender_required": False,
                  "viewer": "static WebGL2; no Python needed on hosted page", "extraction": "Windows x64 current decoder"}, ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            print(json.dumps(prepare(args.model_dir, args.out, args.bindings, args.max_texture), ensure_ascii=False, indent=2))
        elif args.command == "init":
            initialize(args)
        else:
            serve(args.scene,args.port,args.work_dir,args.game_dir,args.extractor)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
