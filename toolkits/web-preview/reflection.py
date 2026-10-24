"""Convert War Thunder packed N channels to linear glTF material maps.

Official contract: wiki.warthunder.com/cdk/creation_camo (2024-04-17).
R = inverted roughness, G = normal X, B = metallicity, A = normal Y.
This previews those channels with PBR lighting; it does not emulate Dagor.
"""
from pathlib import Path
from io import BytesIO
import hashlib
import json
import math
import struct
import sys


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def convert(image, limit=4096):
    from PIL import Image, ImageChops, ImageMath
    image=image.convert('RGBA');image.thumbnail((limit,limit),Image.Resampling.LANCZOS)
    red,green,blue,alpha=image.split()
    orm=Image.merge('RGB',(Image.new('L',image.size,255),ImageChops.invert(red),blue))
    # Reconstruct Z after unpacking signed XY; normalize invalid compressed samples.
    x=ImageMath.lambda_eval(lambda a:a['v']/127.5-1,v=green.convert('F'))
    y=ImageMath.lambda_eval(lambda a:a['v']/127.5-1,v=alpha.convert('F'))
    norm=ImageMath.lambda_eval(lambda a:a['max'](a['x']*a['x']+a['y']*a['y'],1)**.5,x=x,y=y)
    nx=ImageMath.lambda_eval(lambda a:a['convert']((a['x']/a['norm']+1)*127.5+.5,'L'),x=x,norm=norm)
    ny=ImageMath.lambda_eval(lambda a:a['convert']((a['y']/a['norm']+1)*127.5+.5,'L'),y=y,norm=norm)
    nz=ImageMath.lambda_eval(lambda a:a['convert']((a['max'](1-a['x']*a['x']-a['y']*a['y'],0)**.5+1)*127.5+.5,'L'),x=x,y=y)
    return orm,Image.merge('RGB',(nx,ny,nz))


def attach(folder, bindings, base=None):
    """Attach maps to a new prepared scene without altering mesh data or colors."""
    from PIL import Image
    folder=Path(folder);base=Path(base or folder);mapping=bindings.get('surface_materials',{})
    scene=json.loads((folder/'scene.json').read_text(encoding='utf-8'))
    if not mapping:return scene
    raw=(folder/'model.glb').read_bytes();size,kind=struct.unpack_from('<II',raw,12)
    if kind!=0x4e4f534a:raise ValueError('Invalid GLB JSON chunk')
    gltf=json.loads(raw[20:20+size]);bin_start=28+size
    binary=bytearray(raw[bin_start:]);cache={};records={r['name']:r for r in scene['materials']}
    def texture(image):
        image=image.copy();image.thumbnail((1024,1024),Image.Resampling.LANCZOS)
        output=BytesIO();image.save(output,format='PNG');data=output.getvalue()
        binary.extend(b'\0'*(-len(binary)%4));offset=len(binary);binary.extend(data)
        view=len(gltf['bufferViews']);gltf['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(data)})
        index=len(gltf.setdefault('images',[]));gltf['images'].append({'bufferView':view,'mimeType':'image/png'})
        result=len(gltf.setdefault('textures',[]));gltf['textures'].append({'source':index,'sampler':0});return result
    for material in gltf['materials']:
        name=material['name']
        if name not in mapping or name not in records:continue
        path=(base/mapping[name]).resolve()
        if not path.is_file():raise FileNotFoundError('反射贴图不存在：'+str(path))
        key=sha(path)
        if key not in cache:
            sys.path.insert(0,str(Path(__file__).parent/'tools'))
            from dds_mip import open_display
            with open_display(path,4096) as original:
                source_size=original.info.get('original_dds_size',list(original.size));orm,normal=convert(original)
            number=len(cache);surface={}
            for channel,image in [('orm',orm),('normal',normal)]:
                filename=f'native-{channel}-{number:03d}.png';image.save(folder/filename)
                surface[channel]={'file':filename,'sha256':sha(folder/filename),'size':list(image.size),'texture':texture(image)}
            surface.update(source_sha256=key,source_size=source_size,source_name=path.name,encoding='wt-inverted-roughness-metal-GA-normal')
            cache[key]=surface
        surface=cache[key];material['pbrMetallicRoughness'].update(metallicRoughnessTexture={'index':surface['orm']['texture']},metallicFactor=1,roughnessFactor=1)
        material['normalTexture']={'index':surface['normal']['texture']}
        records[name]['reflection']={k:v for k,v in surface.items() if k not in ('orm','normal')}
        records[name]['reflection'].update({k:{a:b for a,b in v.items() if a!='texture'} for k,v in surface.items() if k in ('orm','normal')})
        records[name]['material_simulation']='WT packed N channels → glTF PBR approximation'
        material.setdefault('extras',{})['source']=records[name]
    gltf['buffers'][0]['byteLength']=len(binary);binary.extend(b'\0'*(-len(binary)%4))
    payload=json.dumps(gltf,ensure_ascii=False,separators=(',',':')).encode();payload+=b' '*(-len(payload)%4)
    result=struct.pack('<III',0x46546c67,2,28+len(payload)+len(binary))+struct.pack('<II',len(payload),0x4e4f534a)+payload+struct.pack('<II',len(binary),0x004e4942)+binary
    (folder/'model.glb').write_bytes(result);scene.update(glb_bytes=len(result),glb_sha256=sha(folder/'model.glb'),reflection_materials=sum('reflection' in r for r in scene['materials']))
    scene['material_note']='已读取反射、金属度与凹凸贴图；PBR 近似预览，完整 Dagor 着色器以游戏内为准'
    (folder/'scene.json').write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8');return scene
