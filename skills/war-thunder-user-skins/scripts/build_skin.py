#!/usr/bin/env python3
"""Build a game-ready TGA/BLK skin from editor exports and verified references.

Only selected color maps change. Original color alpha and unedited packed
material channels are preserved. Source UserSkins files remain read-only.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import zipfile
import numpy as np
from PIL import Image
from inspect_skins import inventory,open_rgba,write_json
from artifact_io import ArtifactError, ArtifactTransaction


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
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new empty skin output directory')
    data=inventory(template)
    if len(data['configs'])!=1: raise ValueError('Expected one template vehicle BLK')
    config=data['configs'][0];sources=[m.get('from') for m in config['mappings']]
    # Reference replacement can repair a missing target file. It cannot make
    # duplicate fields, invalid mapping types or other BLK structure unambiguous.
    problems=[]
    for issue in data['issues']:
        if issue['code']=='missing_texture':
            affected=[m for m in config['mappings'] if m.get('line')==issue.get('line')]
            if affected and all(m.get('from') in references for m in affected):
                continue
        if issue['level']=='error' or issue['code'] in {
                'unhandled_field','unhandled_block','unhandled_mapping_field',
                'param_on_replace','wildcard_target','duplicate_mapping','conflicting_mapping'}:
            problems.append(issue)
    if problems:
        raise ValueError('Template needs resolution before build: '+json.dumps(problems,ensure_ascii=False))
    if len(sources)!=len(set(sources)): raise ValueError('Template has duplicate source mappings; resolve ambiguity first')
    if any(key not in sources for key in (*paint,*references,*channel_edits)): raise ValueError('An assignment does not match a template resource')
    if not paint and not channel_edits: raise ValueError('At least one editor color or channel export is required')
    filenames=[]
    for index,source in enumerate(sources):
        basename=re.sub(r'[^A-Za-z0-9_]+','_',source.rstrip('*')).strip('_') or f'texture_{index}'
        filenames.append(basename+'.tga')
    if len({name.casefold() for name in filenames}) != len(filenames):
        raise ValueError('Generated texture filenames collide')
    vehicle=config['vehicle_id']
    blk=output/(vehicle+'.blk')
    archive=output.with_suffix('.zip')
    report_path=output.with_suffix('.build.json')
    outputs=[*(output/name for name in filenames),blk,archive,report_path]
    inputs=[template,*paint.values(),*references.values(),
            *(p for edits in channel_edits.values() for p in edits.values())]
    with ArtifactTransaction(outputs,inputs=inputs,label='skin-build') as transaction:
        return _build_staged(template,paint,references,output,channel_edits,
                             config,filenames,transaction,blk,archive,report_path)


def _build_staged(template,paint,references,output,channel_edits,config,
                  filenames,transaction,blk,archive,report_path):
    blocks=['name:t="user"'];records=[]
    for index,mapping in enumerate(config['mappings']):
        source=mapping['from']
        reference=references.get(source,template/mapping.get('target_file',''))
        edited=source in paint
        edited_channels=channel_edits.get(source,{})
        filename=filenames[index];target=transaction.stage(output/filename)
        with assemble_texture(reference,paint.get(source),mapping,edited_channels) as rgba:
            rgba.save(target,format='TGA')
            with Image.open(target) as check, check.convert('RGBA') as decoded:
                if not np.array_equal(np.asarray(decoded),np.asarray(rgba)):
                    raise ValueError('TGA round-trip changed RGBA pixels')
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
    staged_blk=transaction.stage(blk)
    staged_blk.write_text('\n\n'.join(blocks)+'\n',encoding='utf-8')
    inspection=inventory(staged_blk.parent)
    errors=[i for i in inspection['issues'] if i['level']=='error']
    if errors: raise ValueError('Built skin failed static validation: '+json.dumps(errors,ensure_ascii=False))
    staged_archive=transaction.stage(archive)
    with zipfile.ZipFile(staged_archive,'w',compression=zipfile.ZIP_DEFLATED) as zipped:
        for final in [*(output/name for name in filenames),blk]:
            zipped.write(transaction.stage(final),arcname=(Path(output.name)/final.name).as_posix())
    with zipfile.ZipFile(staged_archive) as zipped:
        if zipped.testzip() is not None:
            raise ValueError('Built ZIP failed CRC validation')
    report={'vehicle':config['vehicle_id'],'skin_directory':str(output),'zip':str(archive),'textures':records,
            'static_validation_errors':0,'in_game_validation':False,
            'format':'32-bit TGA; runtime mip behavior is checked in game, no DDS compression assumed.'}
    write_json(transaction.stage(report_path),report)
    transaction.commit()
    return report


def assemble_texture(reference,paint,mapping,channel_edits):
    """Return an owned image, releasing all decoder/plane intermediates on failure."""
    with ExitStack() as cleanup:
        original,_=open_rgba(reference)
        cleanup.callback(original.close)
        if paint is not None:
            if mapping.get('role')!='albedo':
                raise ValueError('This builder edits color maps; packed material edits require explicit channel assembly')
            with Image.open(paint) as image:
                if image.width*image.height>8192*8192:
                    raise ValueError('Editor export exceeds the validated pixel limit')
                image.load()
                color=image.convert('RGB')
                cleanup.callback(color.close)
            if color.width*original.height!=color.height*original.width:
                raise ValueError('Editor export changed the UV aspect ratio')
            alpha=original.getchannel('A');cleanup.callback(alpha.close)
            if alpha.size!=color.size:
                alpha=alpha.resize(color.size,Image.Resampling.NEAREST);cleanup.callback(alpha.close)
            color_planes=color.split()
            for plane in color_planes: cleanup.callback(plane.close)
            rgba=Image.merge('RGBA',(*color_planes,alpha))
        else:
            rgba=original.copy()
        cleanup.callback(rgba.close)
        if channel_edits:
            planes={};target_size=None
            for channel,path in channel_edits.items():
                if len(channel)!=1 or channel not in 'RGBA':
                    raise ValueError('Channel must be R, G, B or A')
                with Image.open(path) as bitmap:
                    if bitmap.width*bitmap.height>8192*8192:
                        raise ValueError('Channel export exceeds the validated pixel limit')
                    bitmap.load()
                    if bitmap.mode not in {'L','RGB','RGBA'}:
                        raise ValueError('Use an 8-bit grayscale channel export')
                    with bitmap.convert('RGB') as converted:
                        rgb=np.asarray(converted)
                        if not np.array_equal(rgb[:,:,0],rgb[:,:,1]) or not np.array_equal(rgb[:,:,0],rgb[:,:,2]):
                            raise ValueError('Channel exports must be grayscale, not a colored preview')
                    plane=bitmap.convert('L');cleanup.callback(plane.close)
                if target_size is not None and plane.size!=target_size:
                    raise ValueError('Channel exports have different dimensions')
                target_size=plane.size;planes[channel]=plane
            if target_size[0]*rgba.height!=target_size[1]*rgba.width:
                raise ValueError('Channel export changed the UV aspect ratio')
            merged=[]
            for channel in 'RGBA':
                plane=planes.get(channel)
                if plane is None:
                    plane=rgba.getchannel(channel);cleanup.callback(plane.close)
                    if plane.size!=target_size:
                        plane=plane.resize(target_size,Image.Resampling.NEAREST);cleanup.callback(plane.close)
                merged.append(plane)
            result=Image.merge('RGBA',merged)
        else:
            result=rgba.copy()
    return result


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
    except (OSError,ValueError,KeyError,ArtifactError) as exc:
        print(f'Skin build failed: {exc}',file=__import__('sys').stderr);return 1


if __name__=='__main__': raise SystemExit(main())
