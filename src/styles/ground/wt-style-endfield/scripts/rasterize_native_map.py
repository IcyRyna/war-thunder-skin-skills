"""Rasterize only this task's canonical mapped SVGs without shared editor state.

The SVG remains the editable source. This is not a general SVG interpreter.
"""
from pathlib import Path
import base64
import re
import xml.etree.ElementTree as ET
import io
import hashlib
import json

import skia
import numpy as np
from PIL import Image

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def rasterize(path:Path,out:Path):
    if out.exists():
        raise FileExistsError(out)
    root=ET.fromstring(path.read_bytes())
    ns={'s':'http://www.w3.org/2000/svg'}
    width,height=int(root.attrib['width']),int(root.attrib['height'])
    x0,y0,vw,vh=map(float,root.attrib['viewBox'].split())
    if (vw,vh)!=(width,height) or max(width,height)>16384:
        raise ValueError('Unexpected mapped canvas')
    image=root.find('s:defs/s:image',ns)
    href=image.attrib['{http://www.w3.org/1999/xlink}href']
    if not href.startswith('data:image/png;base64,'):
        raise ValueError('Only embedded original PNG is supported')
    original=base64.b64decode(href.partition(',')[2],validate=True)
    with Image.open(io.BytesIO(original)) as source:
        pixels=np.array(source.convert('RGBA'))
    bitmap=skia.Image.fromarray(pixels,colorType=skia.ColorType.kRGBA_8888_ColorType,copy=True)
    if bitmap is None:
        raise ValueError('Cannot decode the embedded PNG')
    surface=skia.Surface(width,height);canvas=surface.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT);canvas.translate(-x0,-y0)
    count=0
    for group in root.findall('s:g',ns):
        match=re.fullmatch(r'url\(#(face-\d+)\)',group.attrib['clip-path'])
        if not match:raise ValueError('Unexpected clip reference')
        polygon=root.find(f"s:defs/s:clipPath[@id='{match[1]}']/s:polygon",ns)
        points=[tuple(map(float,pair.split(','))) for pair in polygon.attrib['points'].split()]
        clip=skia.Path();clip.moveTo(*points[0])
        for point in points[1:]:clip.lineTo(*point)
        clip.close()
        use=group.find('s:use',ns)
        if use.attrib['{http://www.w3.org/1999/xlink}href']!='#intact-source':
            raise ValueError('Unexpected source')
        transform=use.attrib['transform']
        a,b,c,d,e,f=map(float,transform.removeprefix('matrix(').removesuffix(')').split(','))
        canvas.save();canvas.clipPath(clip,doAntiAlias=True)
        canvas.concat(skia.Matrix.MakeAll(a,c,e,b,d,f,0,0,1))
        canvas.drawImage(bitmap,0,0,skia.SamplingOptions(skia.FilterMode.kLinear))
        canvas.restore();count+=1
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(bytes(surface.makeImageSnapshot().encodeToData()))
    result={'source_svg':str(path),'source_sha256':sha(path),'output':str(out),'sha256':sha(out),
            'rasterizer':'skia-python '+skia.__version__,'pieces':count,'size':[width,height],
            'shared_editor_used':False,'source_rgba_recolored':False}
    write_json(out.with_suffix('.json'),result)
    return result


if __name__=='__main__':
    import argparse
    import sys
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('svg',type=Path);parser.add_argument('out',type=Path)
    args=parser.parse_args();result=rasterize(args.svg,args.out)
    sys.stdout.buffer.write((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
