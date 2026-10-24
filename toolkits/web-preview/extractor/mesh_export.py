"""Export decoded model nodes to independent OBJ parts without changing UVs."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re

from archives import FormatError


@dataclass
class Mesh:
    name: str
    vertices: list[tuple[float, float, float]]
    uvs: list[tuple[float, float]]
    faces: list[tuple[int, int, int]]
    materials: list[str]
    normals: list[tuple[float, float, float]]
    source_ids: list[int]

    @property
    def bounds(self):
        return {"min": [min(v[axis] for v in self.vertices) for axis in range(3)],
                "max": [max(v[axis] for v in self.vertices) for axis in range(3)]}


def filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "part"


def decode_parts(model):
    for obj in model:
        if not obj.faces:
            continue
        node = model.skeleton.getNodeByName(obj.name) if model.skeleton is not None and not obj.skinned else None
        remap, vertices, uvs, source_ids, faces, materials = {}, [], [], [], [], []
        current_material = f"none_{obj.name}"
        for number, face in enumerate(obj.faces):
            if number in obj.materials:
                current_material = str(obj.materials[number])
            if len(face) != 3:
                raise FormatError("Decoded mesh is not triangular")
            mapped = []
            for source_id in face:
                if not 0 <= source_id < model.vertCnt:
                    raise FormatError("Decoded face references an invalid vertex")
                if source_id not in remap:
                    value = model.getVertex(source_id, parentBone=node)
                    # Match DAE's OBJ convention (X/Y unchanged, Z reflected).
                    vertex = (float(value[0]), float(value[1]), -float(value[2]))
                    uv = tuple(float(v) for v in model.getUV(source_id)[:2])
                    if not all(math.isfinite(v) for v in (*vertex, *uv)):
                        raise FormatError("Decoded vertex/UV contains nonfinite values")
                    remap[source_id] = len(vertices)
                    vertices.append(vertex)
                    uvs.append(uv)
                    source_ids.append(source_id)
                mapped.append(remap[source_id])
            faces.append(tuple(mapped))
            materials.append(current_material)
        normals = [[0.0, 0.0, 0.0] for _ in vertices]
        for face in faces:
            a, b, c = (vertices[index] for index in face)
            ab = tuple(b[i] - a[i] for i in range(3))
            ac = tuple(c[i] - a[i] for i in range(3))
            normal = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2],
                      ab[0] * ac[1] - ab[1] * ac[0])
            for index in face:
                for axis in range(3):
                    normals[index][axis] += normal[axis]
        normalized = []
        for normal in normals:
            length = math.sqrt(sum(value * value for value in normal))
            normalized.append(tuple(value / length for value in normal) if length > 1e-20 else (0.0, 1.0, 0.0))
        yield Mesh(obj.name, vertices, uvs, faces, materials, normalized, source_ids), node, obj.skinned


def obj_text(mesh: Mesh, offset: int = 0):
    def numbers(values):
        return " ".join(f"{value:.10g}" for value in values)
    for vertex in mesh.vertices:
        yield "v " + numbers(vertex) + "\n"
    for uv in mesh.uvs:
        yield "vt " + numbers(uv) + "\n"
    for normal in mesh.normals:
        yield "vn " + numbers(normal) + "\n"
    yield f"o {filename(mesh.name)}\ng {filename(mesh.name)}\n"
    previous = None
    for face, material in zip(mesh.faces, mesh.materials):
        if material != previous:
            yield f"usemtl {filename(material)}\n"
            previous = material
        indices = [index + offset + 1 for index in face]
        yield "f " + " ".join(f"{index}/{index}/{index}" for index in indices) + "\n"


def write_part(path: Path, mesh: Mesh, mtl_path: str):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"# Original UVs; node transformed to assembly coordinates\nmtllib {mtl_path}\n")
        stream.writelines(obj_text(mesh))


class AssemblyWriter:
    def __init__(self, path: Path):
        self.stream = path.open("w", encoding="utf-8", newline="\n")
        self.stream.write("# DAE-compatible X/Y/-Z assembly coordinates; original UVs\nmtllib materials.mtl\n")
        self.offset = 0

    def append(self, mesh: Mesh):
        self.stream.writelines(obj_text(mesh, self.offset))
        self.offset += len(mesh.vertices)

    def close(self):
        self.stream.close()
