#!/usr/bin/env python3
"""Hash-bound offline finish comparison using two complete analytic environments.

Consumes the standard scene_preview scene; never rewrites it or changes its UVs,
normal convention or tangent handedness. --profile is mandatory. generic uses
R=inverse roughness and B=metallicity. dynamic_masked_chrome_public additionally
uses the pinned public chrome B remap and source-derived BRDF on materials whose
source_shader is exactly dynamic_masked_chrome_bump. This is an approximation,
not the compiled War Thunder shader. Python 3.10+, NumPy, Pillow and Numba.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from numba import njit, prange
from numba.typed import List
from PIL import Image

import artifact_io
from artifact_io import ArtifactError, ArtifactTransaction
import scene_preview as scene_api

PROFILES = ('generic', 'dynamic_masked_chrome_public')
ENVIRONMENTS = ('outdoor', 'studio')
SOURCE_COMMIT = 'd2b87eaf5302e3dc6be8df9a29aa32f303dbd734'
SOURCE_ROOT = f'https://github.com/GaijinEntertainment/DagorEngine/blob/{SOURCE_COMMIT}/'
SOURCE_REFERENCES = {
    'chrome_channels': SOURCE_ROOT + 'prog/daNetGame/shaders/dynamic_masked_chrome_inc.dshl',
    'normal_packing': SOURCE_ROOT + 'prog/daNetGame/shaders/shader_global.dshl',
}
LIMITATIONS = [
    'Offline orthographic approximation, not the compiled War Thunder shader or a game validation.',
    '24 deterministic samples integrate analytic environments, not game cubemaps, EnvBRDFApprox or shadows.',
    'Fixed exposure 1.0 and fitted ACES then sRGB; actual game exposure and reflections are unverified.',
    'No transparency, masking, extra detail normals, anisotropy, mip/LOD, damage or animation validation.',
    'Normal axes/sign/strength are taken from the scene; the profile does not establish their game correctness.',
    'Packed roughness has a 0.04 floor for numerical stability; source behavior below that floor is not reproduced.',
]


@njit(cache=True)
def environment_radiance(direction, environment_id):
    """Linear RGB radiance fields, in world coordinates."""
    y = max(0., min(1., direction[1]))
    if environment_id == 0:
        if direction[1] >= 0:
            return np.array([.72, .80, .91])*(1-y) + np.array([.22, .42, .76])*y
        return np.array([.12, .105, .085])*(.7+.3*abs(direction[1]))
    ceiling = max(0., direction[1])**10
    panel = max(0., .86*direction[0]+.36*direction[1]-.36*direction[2])**40
    rim = max(0., -.65*direction[0]+.4*direction[1]+.65*direction[2])**28
    return (np.array([.075, .075, .08]) + np.array([3.8, 3.5, 2.9])*ceiling
            + np.array([2.5, 3.4, 4.5])*panel + np.array([1.8, 1.7, 1.5])*rim)


def environment_settings(name: str) -> tuple[int, np.ndarray, np.ndarray]:
    if name not in ENVIRONMENTS:
        raise ValueError(f'environment must be one of {ENVIRONMENTS}')
    if name == 'outdoor':
        vectors, powers = [[-.35, .86, .37], [.45, .30, -.72]], [2.6, .20]
    else:
        vectors, powers = [[.86, .36, -.36], [-.7, .3, .65]], [.4, .15]
    vectors = np.asarray(vectors, np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return ENVIRONMENTS.index(name), vectors, np.asarray(powers, np.float32)


def profile_flags(raw: dict, profile: str) -> np.ndarray:
    if profile not in PROFILES:
        raise ValueError(f'profile must be one of {PROFILES}')
    records = sorted(raw['materials'], key=lambda item: item['id'])
    flags = np.asarray([profile == 'dynamic_masked_chrome_public'
                        and record.get('source_shader') == 'dynamic_masked_chrome_bump'
                        and record.get('packed') is not None
                        for record in records], np.bool_)
    if profile == 'dynamic_masked_chrome_public':
        if not flags.any():
            raise ValueError('chrome profile needs an explicit source_shader dynamic_masked_chrome_bump material with a hash-bound packed texture')
    return flags


@njit(cache=True)
def packed_parameters(data, chrome):
    roughness = max(.04, min(1., 1-data[0]))
    metal = max(0., min(1., data[2]))
    if chrome:
        metal = 1-(1-metal)**2
    return roughness, metal


@njit(cache=True)
def radical_inverse(index):
    result, scale = 0., .5
    while index:
        result += (index & 1)*scale
        index >>= 1
        scale *= .5
    return result


@njit(cache=True)
def fresnel(f0, cosine, chrome):
    fc = (1-cosine)**5
    grazing = min(1., 50*f0[1]) if chrome else 1.
    return grazing*fc+(1-fc)*f0


@njit(cache=True)
def diffuse_factor(nv, nl, vh, rough, chrome):
    if not chrome:
        return 1.
    energy = (.45*rough-.475)*rough+1
    fd90 = .5+2*vh*vh*rough
    return (1+(fd90-1)*(1-nv)**5)*(1+(fd90-1)*(1-nl)**5)*energy


@njit(cache=True)
def correlated_visibility(nv, nl, alpha2):
    gv = nl*math.sqrt(nv*(nv-nv*alpha2)+alpha2)
    gl = nv*math.sqrt(nl*(nl-nl*alpha2)+alpha2)
    return .5/max(1e-8, gv+gl)


@njit(cache=True)
def ggx_ibl(base, normal, view, rough, metal, chrome, lights, powers, environment_id):
    n, v = scene_api.unit(normal), scene_api.unit(view)
    nv = max(.001, float((n*v).sum()))
    result = np.zeros(3, np.float64)
    f0 = .04*(1-metal)+base*metal
    alpha2 = max(.0001, rough*rough)**2
    for index in range(len(lights)):
        light = lights[index]
        half = scene_api.unit(light+v)
        nl = max(0., float((n*light).sum()))
        nh = max(0., float((n*half).sum()))
        vh = max(0., float((v*half).sum()))
        # Stable GGX form. A 1e-8 denominator floor would flatten the narrow
        # highlight at rough=.04..0.1 and even reverse its roughness trend.
        den = (1-nh*nh)+alpha2*nh*nh
        distribution = alpha2/max(1e-20, den*den)
        visibility = correlated_visibility(nv, nl, alpha2)
        f = fresnel(f0, vh, chrome)
        spec = f*distribution*visibility
        diffuse = (1-metal)*base*diffuse_factor(nv, nl, vh, rough, chrome)
        # Conventional incident radiance here; source lightColor includes 1/pi.
        result += (diffuse+spec)/math.pi*nl*powers[index]
    up = np.array([0., 1., 0.]) if abs(n[1]) < .95 else np.array([1., 0., 0.])
    t = scene_api.unit(np.cross(up, n))
    b = np.cross(n, t)
    diffuse_sum, spec_sum = np.zeros(3), np.zeros(3)
    count = 24
    for index in range(count):
        x1, x2 = (index+.5)/count, radical_inverse(index)
        phi = 2*math.pi*x2
        ct, st = math.sqrt(1-x1), math.sqrt(x1)
        light = t*(math.cos(phi)*st)+b*(math.sin(phi)*st)+n*ct
        half = scene_api.unit(light+v)
        vh = max(0., float((v*half).sum()))
        nl = max(0., float((n*light).sum()))
        diffuse_sum += environment_radiance(light, environment_id)*diffuse_factor(nv, nl, vh, rough, chrome)
        ct = math.sqrt((1-x1)/(1+(alpha2-1)*x1))
        st = math.sqrt(max(0., 1-ct*ct))
        half = scene_api.unit(t*(math.cos(phi)*st)+b*(math.sin(phi)*st)+n*ct)
        vh = max(0., float((v*half).sum()))
        light = scene_api.unit(half*(2*vh)-v)
        nl = max(0., float((n*light).sum()))
        nh = max(.001, float((n*half).sum()))
        if nl > 0:
            spec_sum += (environment_radiance(light, environment_id)*fresnel(f0, vh, chrome)
                         *4*nl*correlated_visibility(nv, nl, alpha2)*vh/nh)
    return result+diffuse_sum/count*base*(1-metal)+spec_sum/count


@njit(cache=True)
def raster_owners(screen, material_ids, double_sided, basis, width, height):
    depth = np.full((height, width), -np.inf, np.float32)
    owners = np.full((height, width), -1, np.int32)
    handedness = np.linalg.det(basis)
    for index in range(len(screen)):
        p = screen[index]
        den = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
        if abs(den) < 1e-8 or (not double_sided[material_ids[index]] and den*handedness >= -1e-8):
            continue
        xmin, xmax = max(0, int(math.floor(p[:, 0].min()))), min(width-1, int(math.ceil(p[:, 0].max())))
        ymin, ymax = max(0, int(math.floor(p[:, 1].min()))), min(height-1, int(math.ceil(p[:, 1].max())))
        for y in range(ymin, ymax+1):
            for x in range(xmin, xmax+1):
                a = ((p[1, 1]-p[2, 1])*(x+.5-p[2, 0])+(p[2, 0]-p[1, 0])*(y+.5-p[2, 1]))/den
                b = ((p[2, 1]-p[0, 1])*(x+.5-p[2, 0])+(p[0, 0]-p[2, 0])*(y+.5-p[2, 1]))/den
                c = 1-a-b
                if a < -.0001 or b < -.0001 or c < -.0001:
                    continue
                z = a*p[0, 2]+b*p[1, 2]+c*p[2, 2]
                if z > depth[y, x]:
                    depth[y, x], owners[y, x] = z, index
    return owners


@njit(cache=True, parallel=True)
def shade(screen, owners, uvs, normals, tangents, bitangents, material_ids,
          colors, packed, has_packed, normal_textures, normal_codes, normal_strengths,
          normal_y_signs, roughness, metallicity, chrome_flags, double_sided,
          repeats, basis, lights, powers, environment_id):
    height, width = owners.shape
    frame = np.full((height, width, 3), 238, np.uint8)
    for y in prange(height):
        for x in range(width):
            index = owners[y, x]
            if index < 0:
                continue
            p = screen[index]
            mid = material_ids[index]
            den = (p[1, 1]-p[2, 1])*(p[0, 0]-p[2, 0])+(p[2, 0]-p[1, 0])*(p[0, 1]-p[2, 1])
            a = ((p[1, 1]-p[2, 1])*(x+.5-p[2, 0])+(p[2, 0]-p[1, 0])*(y+.5-p[2, 1]))/den
            b = ((p[2, 1]-p[0, 1])*(x+.5-p[2, 0])+(p[0, 0]-p[2, 0])*(y+.5-p[2, 1]))/den
            c = 1-a-b
            u, v = a*uvs[index, 0]+b*uvs[index, 1]+c*uvs[index, 2]
            color = scene_api.sample(colors[mid], u, v, repeats[mid])
            n = scene_api.unit(a*normals[index, 0]+b*normals[index, 1]+c*normals[index, 2])
            back_facing = double_sided[mid] and (n*basis[2]).sum() < 0
            if normal_codes[mid] != 0 and normal_strengths[mid] != 0:
                data = scene_api.sample(normal_textures[mid], u, v, repeats[mid])
                n = scene_api.mapped_normal(n, tangents[index], bitangents[index], data,
                                           normal_codes[mid], normal_strengths[mid], normal_y_signs[mid])
            if back_facing:
                n = -n
            rough, metal = roughness[mid], metallicity[mid]
            if has_packed[mid]:
                data = scene_api.sample(packed[mid], u, v, repeats[mid])
                rough, metal = packed_parameters(data, chrome_flags[mid])
            base = np.empty(3, np.float64)
            for channel in range(3):
                value = color[channel]
                base[channel] = value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4
            radiance = ggx_ibl(base, n, basis[2], rough, metal, chrome_flags[mid], lights, powers, environment_id)
            for channel in range(3):
                value = max(0., radiance[channel])
                value = max(0., min(1., value*(2.51*value+.03)/(value*(2.43*value+.59)+.14)))
                value = value*12.92 if value <= .0031308 else 1.055*value**(1/2.4)-.055
                frame[y, x, channel] = int(max(0., min(255., value*255)))
    return frame


def scaled_camera(scene: dict, view: str, camera_path: Path | None, size: int):
    if isinstance(size, bool) or not isinstance(size, int) or not 16 <= size <= 4096:
        raise ValueError('size must be an integer within 16..4096')
    _, camera, inputs = scene_api.select_camera(scene, view, camera_path)
    factor = size/max(camera['width'], camera['height'])
    width, height = round(camera['width']*factor), round(camera['height']*factor)
    scene_api.dimensions(width, height)
    camera = {**camera, 'width': width, 'height': height, 'scale': camera['scale']*factor}
    world = scene['geometry']['triangles']
    screen = world @ np.asarray(camera['basis'], np.float32).T
    screen[:, :, 0] = (screen[:, :, 0]-camera['center'][0])*camera['scale']+width*.5
    screen[:, :, 1] = (camera['center'][1]-screen[:, :, 1])*camera['scale']+height*.5
    return np.ascontiguousarray(screen, np.float32), camera, inputs


def render(scene_path: Path, output: Path, *, profile: str, environment: str = 'outdoor',
           view: str = 'iso', size: int = 1280, camera_path: Path | None = None,
           normal: bool = True) -> dict:
    if any(scene_api.file_hash(path) != digest for path, digest in LOADED_SOURCE_HASHES.items()):
        raise ValueError('Renderer source changed after module import; restart the Python process')
    if not isinstance(normal, bool):
        raise ValueError('normal must be boolean')
    scene = scene_api.load_scene(Path(scene_path))
    flags = profile_flags(scene['raw'], profile)
    environment_id, lights, powers = environment_settings(environment)
    screen, camera, camera_inputs = scaled_camera(scene, view, camera_path, size)
    output = Path(output).expanduser().resolve()
    if output.suffix.lower() != '.png':
        raise ValueError('--out must name a new PNG file')
    receipt_path = output.with_suffix('.json')
    frozen = {**scene['input_hashes'], **camera_inputs,
              **LOADED_SOURCE_HASHES}
    with ArtifactTransaction([output, receipt_path], inputs=frozen,
                             label='finish-preview', failure_directory=output.parent/'.artifact-failures') as transaction:
        # Start staging before expensive JIT/rendering so failures receive a receipt.
        staged_image = transaction.stage(output)
        geometry = scene['geometry']
        normals = scene_api.smooth_normals(geometry['triangles'], geometry['node_ids'], geometry['material_ids'])
        tangents, bitangents, valid = scene_api.tangent_frames(geometry['triangles'], geometry['uvs'])
        owners = raster_owners(screen, geometry['material_ids'], scene['double_sided'],
                               np.asarray(camera['basis'], np.float32), camera['width'], camera['height'])
        if not np.any(owners >= 0):
            raise ValueError('camera produced no visible triangles')
        colors, packed, maps = List(), List(), List()
        for color, data, normal_data in zip(scene['colors'], scene['packed'], scene['normal_textures']):
            colors.append(color)
            packed.append(data)
            maps.append(normal_data)
        codes = scene['normal_codes'] if normal else np.zeros_like(scene['normal_codes'])
        frame = shade(screen, owners, geometry['uvs'], normals, tangents, bitangents,
                      geometry['material_ids'], colors, packed, scene['has_packed'], maps,
                      codes, scene['normal_strengths'], scene['normal_y_signs'],
                      scene['roughness'], scene['metallicity'], flags, scene['double_sided'],
                      scene['repeats'], np.asarray(camera['basis'], np.float32), lights, powers, environment_id)
        Image.fromarray(frame).save(staged_image)
        coverage = np.bincount(geometry['material_ids'][owners[owners >= 0]], minlength=len(colors))
        records = sorted(scene['raw']['materials'], key=lambda item: item['id'])
        report = dict(
            schema_version=1, kind='offline_finish_preview', profile=profile, environment=environment,
            scene=str(scene['path']), scene_sha256=frozen[scene['path']],
            geometry=str(scene['geometry_path']), geometry_sha256=geometry['_sha256'],
            image=str(output), image_sha256=scene_api.file_hash(staged_image),
            receipt=str(receipt_path),
            camera=camera, camera_sha256=scene_api.surface.camera_fingerprint(camera), view=view,
            covered_pixels=int((owners >= 0).sum()),
            material_coverage={record['name']: int(coverage[i]) for i, record in enumerate(records)},
            material_coverage_by_id={str(record['id']): dict(name=record['name'], pixels=int(coverage[i]))
                                     for i, record in enumerate(records)},
            display_state=scene['raw']['display_state'],
            normal_mapping=dict(explicitly_disabled=not normal,
                                materials=[dict(id=record['id'], name=record['name'],
                                                convention=record.get('normal_convention', 'none'),
                                                active=bool(codes[i] and scene['normal_strengths'][i]),
                                                strength=float(scene['normal_strengths'][i]),
                                                y_sign=float(scene['normal_y_signs'][i]),
                                                degenerate_uv_fallback_triangles=int(((geometry['material_ids']==i)&~valid).sum()))
                                           for i, record in enumerate(records)]),
            material_decoding=[dict(id=record['id'], name=record['name'],
                                    source_shader=record.get('source_shader'), chrome_profile_applied=bool(flags[i]),
                                    roughness='max(0.04, 1-R)' if scene['has_packed'][i] else 'scene constant',
                                    metal=('1-(1-B)^2' if flags[i] else 'B') if scene['has_packed'][i] else 'scene constant')
                               for i, record in enumerate(records)],
            lighting=dict(directions=lights.tolist(), irradiance=powers.tolist(),
                          analytic_environment=environment, environment_version='analytic-fields-v1',
                          integration_samples=24, exposure=1.0,
                          tone_map='fixed fitted ACES then sRGB', coordinate_space='world'),
            numerical_safety=dict(roughness_floor=.04, direct_ggx_denominator_floor=1e-20,
                                  arbitrary_direct_highlight_cap=False,
                                  comparison_to_legacy='corrected legacy 1e-8 denominator floor and 10000 specular cap; high-smoothness direct peaks deliberately differ'),
            source_basis=dict(commit=SOURCE_COMMIT, references=SOURCE_REFERENCES,
                              applied_to='chrome flagged materials only; generic is a separate approximation',
                              brdf='chrome: source-derived BurleyFixed diffuse, GGX, correlated Smith, source Fresnel; generic: Lambert, GGX, correlated Smith, Schlick'),
            source_inputs=[dict(path=str(path), sha256=digest) for path, digest in frozen.items()],
            exact_source_components=(['chrome-flagged packed materials: R inverse roughness above numerical floor, B remap 1-(1-B)^2',
                                      'chrome-flagged materials: source-derived BurleyFixed diffuse, GGX D, correlated Smith visibility and source Fresnel']
                                     if flags.any() else []),
            approximate_components=['analytic 24-sample diffuse/GGX environment integration',
                                    'geometry-derived smoothed TBN; scene-declared normal convention',
                                    'unmatched auxiliary materials use generic Lambert/GGX, not a source-matched shader'],
            unverified=['compiled game shader identity and formats', 'extra detail normals and transparency',
                        'game sky, exposure and reflections', 'mip anisotropy, LOD, damage and animation'],
            limitations=LIMITATIONS, game_verified=False, game_launched=False)
        transaction.stage(receipt_path).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        if any(scene_api.file_hash(path) != digest for path, digest in frozen.items()):
            raise ValueError('Scene or renderer input changed during rendering; no valid output committed')
        transaction.commit()
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True, type=Path)
    parser.add_argument('--profile', required=True, choices=PROFILES)
    parser.add_argument('--environment', choices=ENVIRONMENTS, default='outdoor')
    parser.add_argument('--view', default='iso')
    parser.add_argument('--camera', type=Path)
    parser.add_argument('--size', type=int, default=1280, help='long edge in pixels; preserves the selected camera aspect/framing')
    parser.add_argument('--normal-off', action='store_true', help='explicit diagnostic override; scene normal axes remain recorded')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = render(args.scene, args.out, profile=args.profile, environment=args.environment,
                        view=args.view, size=args.size, camera_path=args.camera, normal=not args.normal_off)
    except (ValueError, OSError, KeyError, TypeError, ArtifactError) as error:
        parser.exit(1, f'finish preview failed: {error}\n')
    print(json.dumps({key: report[key] for key in ('image', 'image_sha256', 'covered_pixels', 'profile', 'environment')}, ensure_ascii=False))
    return 0


LOADED_SOURCE_HASHES = {
    path: scene_api.file_hash(path)
    for path in (Path(__file__).resolve(), Path(scene_api.__file__).resolve(),
                 Path(scene_api.surface.__file__).resolve(), Path(artifact_io.__file__).resolve())
}


if __name__ == '__main__':
    raise SystemExit(main())
