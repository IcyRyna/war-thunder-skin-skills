#!/usr/bin/env python3
"""Compare an aircraft template and active custom textures against a real baseline.

Read-only. Python 3.10+, Pillow and NumPy. Detects flat export placeholders,
resolves BLK targets, compares independently resized channels, and can restrict
measurements to a supplied model-derived UV coverage mask.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from collections import Counter
import math
import numpy as np
from PIL import Image, ImageDraw

from inspect_skins import inventory, open_rgba, load_font, sha256, write_json
from artifact_io import ArtifactError, ArtifactTransaction


def primary_config(folder: Path):
    data = inventory(folder)
    if len(data['configs']) != 1:
        raise ValueError('Comparison expects one aircraft BLK per input folder')
    return data, data['configs'][0]


def texture_mapping(config: dict, source: str, root: Path):
    matches = [m for m in config['mappings'] if m.get('from') == source]
    if len(matches) != 1 or 'target_file' not in matches[0]:
        raise ValueError(f'Expected one resolved mapping for {source}')
    target = root / matches[0]['target_file']
    if not target.is_file():
        raise ValueError(f'Missing active texture: {target}')
    return target, matches[0]


def load_texture(path: Path, size: tuple[int, int], aspect_size: tuple[int, int] | None = None):
    image, meta = open_rgba(path)
    aspect_width,aspect_height=aspect_size or size
    if image.width * aspect_height != image.height * aspect_width:
        image.close()
        raise ValueError('Texture aspect ratio differs from the comparison baseline')
    channels, full_stats = [], {}
    for name in 'RGBA':
        plane = image.getchannel(name)
        hist = np.asarray(plane.histogram(), dtype=np.float64)
        values = np.arange(256)
        total = hist.sum()
        mean = float(np.dot(hist, values) / total)
        variance = float(np.dot(hist, (values - mean) ** 2) / total)
        lo, hi = plane.getextrema()
        full_stats[name] = {'min':lo, 'max':hi, 'mean':round(mean,5),
                            'stddev':round(math.sqrt(variance),5),
                            'mode':int(hist.argmax()), 'mode_percent':round(float(hist.max()/total*100),5)}
        sample = plane.resize(size, Image.Resampling.BOX) if plane.size != size else plane.copy()
        channels.append(np.asarray(sample).copy())
        sample.close(); plane.close()
    image.close()
    pixels = np.stack(channels, axis=-1)
    meta.update(file=str(path.resolve()), sha256=sha256(path), channels=full_stats,
                flat_rgba=all(c['min']==c['max'] for c in full_stats.values()),
                sampled_rgba_sha256=hashlib.sha256(pixels.tobytes()).hexdigest())
    return pixels, meta


def channel_metrics(reference: np.ndarray, candidate: np.ndarray, mask: np.ndarray):
    a=reference[mask].astype(np.float32)
    b=candidate[mask].astype(np.float32)
    difference=np.abs(a-b)
    ac=a-a.mean(); bc=b-b.mean()
    denominator=float(np.sqrt(np.dot(ac,ac)*np.dot(bc,bc)))
    correlation=float(np.dot(ac,bc)/denominator) if denominator>0 else None
    return {'mae_0_255':round(float(difference.mean()),5),
            'p95_abs_diff':round(float(np.percentile(difference,95)),5),
            'pixels_diff_gt_8_percent':round(float((difference>8).mean()*100),5),
            'correlation':round(correlation,6) if correlation is not None else None}


def normals(pixels: np.ndarray, mask: np.ndarray):
    xy=pixels[mask][:,[1,3]].astype(np.float32)*(2.0/255.0)-1.0
    length_sq=np.sum(xy*xy,axis=-1)
    z=np.sqrt(np.maximum(0,1-length_sq))
    vector=np.column_stack((xy,z))
    vector/=np.maximum(np.linalg.norm(vector,axis=1,keepdims=True),1e-12)
    return vector


def normal_metrics(reference, candidate, mask):
    a=normals(reference,mask); b=normals(candidate,mask)
    angle=np.degrees(np.arccos(np.clip(np.sum(a*b,axis=1),-1,1)))
    return {'mean_degrees':round(float(angle.mean()),5),
            'median_degrees':round(float(np.median(angle)),5),
            'p95_degrees':round(float(np.percentile(angle,95)),5),
            'pixels_over_5_degrees_percent':round(float((angle>5).mean()*100),5),
            'assumption':'G/A mapped from 0..255 to signed XY, positive reconstructed Z; diagnostic only.'}


def compare_arrays(reference, candidate, mask):
    return {name:channel_metrics(reference[:,:,i],candidate[:,:,i],mask) for i,name in enumerate('RGBA')}


def image_from_rgb(pixels, side):
    bitmap=Image.fromarray(pixels[:,:,:3])
    bitmap.thumbnail((side,side),Image.Resampling.LANCZOS)
    return bitmap


def overview(output, template_c, original_c, original_n, rows, references, mask):
    side=380; header=65; footer=135
    columns=2+len(rows)
    sheet=Image.new('RGB',(columns*side,side*3+header+footer),(242,240,236))
    draw=ImageDraw.Draw(sheet); font=load_font(16)
    sets=[('Exported template',template_c,None),('Actual game baseline',original_c,original_n)]
    sets += [(row['label'],references[row['label']]['albedo'],references[row['label']]['material']) for row in rows]
    for col,(label,color,material) in enumerate(sets):
        x=col*side
        draw.text((x+10,8),label,fill=(25,25,25),font=font)
        rgb=image_from_rgb(color,side-12)
        sheet.paste(rgb,(x+6,header)); rgb.close()
        if material is not None:
            rgb=image_from_rgb(material,side-12)
            sheet.paste(rgb,(x+6,header+side)); rgb.close()
            delta=np.abs(material[:,:,[1,3]].astype(np.int16)-original_n[:,:,[1,3]].astype(np.int16)).max(axis=-1)
            hot=np.clip(delta*12,0,255).astype(np.uint8)
            hot[~mask]=0
            heat=Image.fromarray(np.stack((hot,(hot//3),np.zeros_like(hot)),axis=-1))
            heat.thumbnail((side-12,side-12),Image.Resampling.LANCZOS)
            sheet.paste(heat,(x+6,header+side*2)); heat.close()
        if col>=2:
            row=rows[col-2]
            g=row['material_difference']['G']; a=row['material_difference']['A']
            text=f"Color / packed material / G-A delta x12\nG MAE {g['mae_0_255']:.2f}; A MAE {a['mae_0_255']:.2f}\nNormal mean {row['normal_difference']['mean_degrees']:.2f} deg\n{row['material']['width']} x {row['material']['height']}; {row['material']['mip_count']} mip(s)"
        else:
            text='Color / packed material / G-A delta x12' if col==1 else 'Uniform export: unavailable original detail'
        draw.multiline_text((x+10,header+side*3+4),text,fill=(25,25,25),font=font,spacing=6)
    sheet.save(output/'comparison.png'); sheet.close()


def run(args):
    inputs=[args.template.resolve(),*[p.resolve() for p in args.skin]]
    output=args.out.resolve()
    for source in inputs:
        if output==source or source in output.parents:
            raise ValueError('Comparison output must be outside all source skin directories')
    labels=[source.name for source in inputs[1:]]
    if len({name.casefold() for name in labels})!=len(labels):
        raise ValueError('Input leaf folder names must be unique')
    for path in (args.reference_albedo,args.reference_material,args.uv_mask):
        if path is not None:
            inputs.append(path.resolve())
    outputs=[output/'comparison.json',output/'comparison.png',
             *(output/(name+'_rgb.png') for name in labels)]
    with ArtifactTransaction(outputs,inputs=inputs,label='skin-comparison') as transaction:
        staged={path:transaction.stage(path) for path in outputs}
        result=_run_staged(args,staged[output/'comparison.json'].parent)
        transaction.commit()
    _print_summary(args,result)
    return result


def _run_staged(args,output):
    inputs=[args.template.resolve(),*[p.resolve() for p in args.skin]]
    template_data,template_config=primary_config(inputs[0])
    color_sources=[m['from'] for m in template_config['mappings'] if m.get('role')=='albedo']
    material_sources=[m['from'] for m in template_config['mappings'] if m.get('role')=='packed_material']
    if len(color_sources)!=1 or len(material_sources)!=1:
        raise ValueError('Expected one main color and one main packed material mapping')
    color_source,material_source=color_sources[0],material_sources[0]
    default_c,_=texture_mapping(template_config,color_source,inputs[0])
    default_n,_=texture_mapping(template_config,material_source,inputs[0])
    original_c_path=args.reference_albedo or default_c
    original_n_path=args.reference_material or default_n
    base_image,base_meta=open_rgba(original_c_path)
    width,height=base_image.size
    scale=min(1.0,args.size/max(width,height))
    size=(max(1,round(width*scale)),max(1,round(height*scale)))
    base_image.close()
    original_c,original_c_meta=load_texture(original_c_path,size,(width,height))
    original_n,original_n_meta=load_texture(original_n_path,size,(width,height))
    template_c,template_c_meta=load_texture(default_c,size,(width,height))
    template_n,template_n_meta=load_texture(default_n,size,(width,height))
    if original_c_meta['flat_rgba'] and original_n_meta['flat_rgba'] and not (args.reference_albedo and args.reference_material):
        raise ValueError('Flat template is not a structural baseline; supply actual reference textures')
    if args.uv_mask:
        with Image.open(args.uv_mask) as bitmap:
            if bitmap.width*height != bitmap.height*width:
                raise ValueError('UV mask aspect ratio differs from the comparison baseline')
            mask=np.asarray(bitmap.convert('L').resize(size,Image.Resampling.NEAREST))>0
    else:
        mask=np.ones((size[1],size[0]),dtype=bool)
    if not mask.any():
        raise ValueError('UV mask has no covered pixels')
    rows,arrays=[],{}
    for source in inputs[1:]:
        data,config=primary_config(source)
        c_path,c_map=texture_mapping(config,color_source,source)
        n_path,n_map=texture_mapping(config,material_source,source)
        c,c_meta=load_texture(c_path,size,(width,height)); n,n_meta=load_texture(n_path,size,(width,height))
        label=source.name
        if label in arrays:
            raise ValueError('Input leaf folder names must be unique')
        arrays[label]={'albedo':c,'material':n}
        row={'label':label,'folder':str(source),'albedo':c_meta,'material':n_meta,
             'albedo_difference':compare_arrays(original_c,c,mask),
             'material_difference':compare_arrays(original_n,n,mask),
             'normal_difference':normal_metrics(original_n,n,mask),
             'extra_mappings':[m for m in config['mappings'] if m.get('from') not in {color_source,material_source}],
             'static_issue_codes':dict(Counter(i['code'] for i in data['issues']))}
        Image.fromarray(c[:,:,:3]).save(output/(label+'_rgb.png'))
        rows.append(row)
    result={'comparison_resolution':list(size),'measured_pixels':int(mask.sum()),
            'measured_percent_of_atlas':round(float(mask.mean()*100),5),
            'template':{'albedo':template_c_meta,'material':template_n_meta},
            'reference':{'albedo':original_c_meta,'material':original_n_meta},'skins':rows,
            'limits':['Differences include source resolution, compression and intentional artistic changes.',
                      'UV compatibility and visual quality still need model/game review.',
                      'Normal-angle estimate assumes conventional signed G/A packing; it is not an in-game shader simulation.']}
    pairs=[]
    for i,left in enumerate(rows):
        for right in rows[i+1:]:
            pairs.append({'left':left['label'],'right':right['label'],
                          'albedo':compare_arrays(arrays[left['label']]['albedo'],arrays[right['label']]['albedo'],mask),
                          'material':compare_arrays(arrays[left['label']]['material'],arrays[right['label']]['material'],mask)})
    result['cross_skin_pairs']=pairs
    write_json(output/'comparison.json',result)
    overview(output,template_c,original_c,original_n,rows,arrays,mask)
    return result


def _print_summary(args,result):
    template=result['template']
    print(json.dumps({'output':str(args.out.resolve()),'template_flat':template['albedo']['flat_rgba'] and template['material']['flat_rgba'],
                      'measured_percent_of_atlas':result['measured_percent_of_atlas'],
                      'skins':[{'name':r['label'],'size':r['albedo']['width'],
                                'G_MAE':r['material_difference']['G']['mae_0_255'],
                                'A_MAE':r['material_difference']['A']['mae_0_255'],
                                'normal_mean_deg':r['normal_difference']['mean_degrees'],
                                'R_mean':r['material']['channels']['R']['mean'],
                                'B_mean':r['material']['channels']['B']['mean']} for r in result['skins']]},ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template',type=Path,required=True)
    parser.add_argument('--skin',type=Path,action='append',required=True)
    parser.add_argument('--reference-albedo',type=Path)
    parser.add_argument('--reference-material',type=Path)
    parser.add_argument('--uv-mask',type=Path)
    parser.add_argument('--size',type=int,default=2048)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:
        if not 128<=args.size<=2048:
            raise ValueError('--size must be 128..2048')
        run(args)
        return 0
    except (OSError,ValueError,KeyError,ArtifactError) as exc:
        print(f'Comparison failed: {exc}',file=__import__('sys').stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
