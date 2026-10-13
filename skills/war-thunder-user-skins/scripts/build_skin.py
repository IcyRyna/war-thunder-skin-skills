#!/usr/bin/env python3
"""Build a game-ready TGA/BLK skin from editor exports and verified references.

Only selected color maps change. Original color alpha and unedited packed
material channels are preserved. Source UserSkins files remain read-only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
import numpy as np
from PIL import Image
from inspect_skins import inventory,open_rgba,write_json


def assignments(values):
    result={}
    for value in values or []:
        key,path=value.split('=',1)
        if not key or key in result: raise ValueError('Texture assignments must use unique nonempty resource names')
        result[key]=Path(path).resolve()
    return result


def quoted(text):
    return '"'+text.replace('\\','\\\\').replace('"','\\"')+'"'


def build(template,paint,references,output,channel_edits=None):
    channel_edits=channel_edits or {}
    template=template.resolve();output=output.resolve()
    if output==template or template in output.parents: raise ValueError('Output must be outside the source template')
    if output.exists() and any(output.iterdir()): raise ValueError('Choose a new empty skin output directory')
    data=inventory(template)
    if len(data['configs'])!=1: raise ValueError('Expected one template vehicle BLK')
    config=data['configs'][0];sources=[m.get('from') for m in config['mappings']]
    if len(sources)!=len(set(sources)): raise ValueError('Template has duplicate source mappings; resolve ambiguity first')
    if any(key not in sources for key in (*paint,*references,*channel_edits)): raise ValueError('An assignment does not match a template resource')
    if not paint and not channel_edits: raise ValueError('At least one editor color or channel export is required')
    output.mkdir(parents=True,exist_ok=True)
    blocks=['name:t="user"'];records=[]
    for index,mapping in enumerate(config['mappings']):
        source=mapping['from']
        reference=references.get(source,template/mapping.get('target_file',''))
        original,meta=open_rgba(reference)
        edited=source in paint
        if edited:
            if mapping.get('role')!='albedo':
                original.close();raise ValueError('This builder edits color maps; packed material edits require explicit channel assembly')
            with Image.open(paint[source]) as image:
                if image.width*image.height>8192*8192: raise ValueError('Editor export exceeds the validated pixel limit')
                image.load();color=image.convert('RGB')
            if color.width*original.height!=color.height*original.width:
                color.close();original.close();raise ValueError('Editor export changed the UV aspect ratio')
            alpha=original.getchannel('A')
            if alpha.size!=color.size:
                resized=alpha.resize(color.size,Image.Resampling.NEAREST);alpha.close();alpha=resized
            rgba=Image.merge('RGBA',(*color.split(),alpha))
            alpha.close();color.close()
        else:
            rgba=original.copy()
        edited_channels=channel_edits.get(source,{})
        if edited_channels:
            planes={}
            target_size=None
            for channel,path in edited_channels.items():
                if channel not in 'RGBA': raise ValueError('Channel must be R, G, B or A')
                with Image.open(path) as bitmap:
                    if bitmap.width*bitmap.height>8192*8192: raise ValueError('Channel export exceeds the validated pixel limit')
                    bitmap.load()
                    if bitmap.mode not in {'L','RGB','RGBA'}: raise ValueError('Use an 8-bit grayscale channel export')
                    rgb=np.asarray(bitmap.convert('RGB'))
                    if not np.array_equal(rgb[:,:,0],rgb[:,:,1]) or not np.array_equal(rgb[:,:,0],rgb[:,:,2]):
                        raise ValueError('Channel exports must be grayscale, not a colored preview')
                    plane=bitmap.convert('L')
                if target_size is not None and plane.size!=target_size: raise ValueError('Channel exports have different dimensions')
                target_size=plane.size;planes[channel]=plane
            if target_size[0]*rgba.height!=target_size[1]*rgba.width: raise ValueError('Channel export changed the UV aspect ratio')
            merged=[]
            for channel in 'RGBA':
                plane=planes.get(channel)
                if plane is None:
                    plane=rgba.getchannel(channel)
                    if plane.size!=target_size:
                        resized=plane.resize(target_size,Image.Resampling.NEAREST);plane.close();plane=resized
                merged.append(plane)
            assembled=Image.merge('RGBA',merged)
            for plane in merged: plane.close()
            rgba.close();rgba=assembled
        basename=re.sub(r'[^A-Za-z0-9_]+','_',source.rstrip('*')).strip('_') or f'texture_{index}'
        filename=basename+'.tga';target=output/filename
        if target.exists():
            rgba.close();original.close();raise ValueError('Generated texture filenames collide')
        rgba.save(target,format='TGA')
        with Image.open(target) as check:
            decoded=np.asarray(check.convert('RGBA'))
            expected=np.asarray(rgba)
            if not np.array_equal(decoded,expected): raise ValueError('TGA round-trip changed RGBA pixels')
        record={'from':source,'to':filename,'edited_color':edited,'reference':str(reference),
                'width':rgba.width,'height':rgba.height,'bytes':target.stat().st_size,
                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                'reference_alpha_preserved':'A' not in edited_channels,
                'edited_channels':list(edited_channels),
                'packed_material_preserved':not edited and not edited_channels}
        records.append(record)
        body=[mapping['kind']+'{','  from:t='+quoted(source),'  to:t='+quoted(filename)]
        if 'param' in mapping: body.append('  param:t='+quoted(mapping['param']))
        body.append('}');blocks.append('\n'.join(body))
        rgba.close();original.close()
    vehicle=config['vehicle_id'];blk=output/(vehicle+'.blk')
    blk.write_text('\n\n'.join(blocks)+'\n',encoding='utf-8')
    inspection=inventory(output)
    errors=[i for i in inspection['issues'] if i['level']=='error']
    if errors: raise ValueError('Built skin failed static validation: '+json.dumps(errors,ensure_ascii=False))
    archive=output.with_suffix('.zip')
    if archive.exists(): raise ValueError('Skin ZIP already exists')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.iterdir()): zipped.write(path,arcname=(Path(output.name)/path.name).as_posix())
    report={'vehicle':vehicle,'skin_directory':str(output),'zip':str(archive),'textures':records,
            'static_validation_errors':0,'in_game_validation':False,
            'format':'32-bit TGA; runtime mip behavior is checked in game, no DDS compression assumed.'}
    write_json(output.with_suffix('.build.json'),report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template',type=Path,required=True)
    p.add_argument('--paint',action='append',help='Exact from resource=editor PNG')
    p.add_argument('--channel',action='append',help='Exact from resource:RGBA letter=grayscale editor PNG')
    p.add_argument('--reference',action='append',help='Exact from resource=verified original DDS/TGA')
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    try:
        channels={}
        for spec,path in assignments(args.channel).items():
            source,letter=spec.rsplit(':',1)
            if len(letter)!=1 or letter not in 'RGBA': raise ValueError('Use resource:R/G/B/A=grayscale PNG')
            channels.setdefault(source,{})[letter]=path
        report=build(args.template,assignments(args.paint),assignments(args.reference),args.out,channels)
        print(json.dumps(report,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError) as exc:
        print(f'Skin build failed: {exc}',file=__import__('sys').stderr);return 1


if __name__=='__main__': raise SystemExit(main())
