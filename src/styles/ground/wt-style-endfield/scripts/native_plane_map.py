"""Map an intact transparent design through an explicit real surface to native UV SVG.

This maps supplied artwork; it does not choose a surface, design a livery, infer
material data, or establish that a non-planar carrier is appropriate for a logo.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image,ImageDraw

NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
XLINK='http://www.w3.org/1999/xlink'
ET.register_namespace('xlink',XLINK)


def tag(name):
    return '{'+NS+'}'+name


def unit(vector):
    array=np.asarray(vector,dtype=np.float64)
    if array.shape!=(3,) or not np.isfinite(array).all():
        raise ValueError('Surface vectors must contain three finite values')
    length=np.linalg.norm(array)
    if not np.isfinite(length) or length<1e-10:
        raise ValueError('Degenerate surface frame')
    return array/length


def cross2(a,b):
    return float(a[0]*b[1]-a[1]*b[0])


def clip_polygon(subject,triangle):
    result=[np.asarray(v,dtype=np.float64) for v in subject]
    orientation=1 if cross2(triangle[1]-triangle[0],triangle[2]-triangle[0])>=0 else -1
    for a,b in zip(triangle,np.roll(triangle,-1,axis=0)):
        old,result=result,[]
        if not old:
            break
        for previous,current in zip(old[-1:]+old[:-1],old):
            d0=orientation*cross2(b-a,previous-a);d1=orientation*cross2(b-a,current-a)
            if (d0>=-1e-10)!=(d1>=-1e-10):
                result.append(previous+(current-previous)*(d0/(d0-d1)))
            if d1>=-1e-10:
                result.append(current)
    return np.asarray(result)


def map_design(model:dict,profile:dict,design:Path,out_svg:Path)->dict:
    if out_svg.exists() or out_svg.with_suffix('.json').exists():
        raise FileExistsError('Mapping output exists')
    positions=np.asarray(model['positions'],dtype=np.float64)
    uvs=np.asarray(model['uvs'],dtype=np.float64)
    if positions.ndim!=3 or positions.shape[1:]!=(3,3) or uvs.shape!=(len(positions),3,2):
        raise ValueError('Expected triangle positions [N,3,3] and native UV [N,3,2]')
    if not np.isfinite(positions).all() or not np.isfinite(uvs).all():
        raise ValueError('Non-finite native geometry or UV')
    if not isinstance(profile['triangles'],list) or any(type(v) is not int for v in profile['triangles']):
        raise ValueError('Surface triangle IDs must be integers')
    ids=np.asarray(profile['triangles'],dtype=np.int64)
    if not len(ids) or len(set(ids.tolist()))!=len(ids) or ids.min()<0 or ids.max()>=len(positions):
        raise ValueError('Invalid or duplicate surface triangle IDs')
    all_materials=np.asarray(model['material_ids'])
    if all_materials.shape!=(len(positions),) or not np.issubdtype(all_materials.dtype,np.integer):
        raise ValueError('Expected one integer material ID per triangle')
    material_ids=all_materials[ids]
    if len(set(material_ids.tolist()))!=1:
        raise ValueError('One mapping must address one actual material slot')
    if profile.get('uv_origin')!='bottom_left':
        raise ValueError('Declare the actual UV origin; this mapper expects bottom_left')
    aw,ah=profile['atlas_size']
    if any(type(v) is not int or not 1<=v<=16384 for v in (aw,ah)):
        raise ValueError('Invalid native atlas dimensions')
    if np.any(uvs[ids]<-1e-7) or np.any(uvs[ids]>1+1e-7):
        raise ValueError('Selected UV uses tiling outside this single native atlas; supply an explicit mapping strategy')
    n=unit(profile['normal']);hint=unit(profile['horizontal_hint'])
    horizontal=unit(hint-n*np.dot(hint,n));vertical=unit(np.cross(n,horizontal))
    if np.dot(vertical,unit(profile.get('up_hint',[0,1,0])))<0:
        vertical=-vertical
    anchor=np.asarray(profile['anchor_world'],dtype=np.float64)
    if anchor.shape!=(3,) or not np.isfinite(anchor).all():
        raise ValueError('Anchor must contain three finite world coordinates')
    width=float(profile['design_width_m'])
    if not np.isfinite(width) or width<=0:
        raise ValueError('Design width must be positive in model metres')
    with Image.open(design) as source:
        if source.format!='PNG' or source.mode!='RGBA':
            raise ValueError('Artwork must be a real RGBA PNG')
        if max(source.size)>16384:
            raise ValueError('Artwork exceeds the supported native image dimensions')
        source.load();source_alpha=source.getchannel('A');sw,sh=source.size
    if source_alpha.getbbox() is None:
        raise ValueError('Artwork has no visible ink')
    scale=width/sw
    aq=np.array([np.dot(anchor,horizontal),np.dot(anchor,vertical)])
    source_to_plane=np.array([[scale,0,aq[0]-scale*sw/2],[0,-scale,aq[1]+scale*sh/2]])
    source_corners=np.array([[0,0,1],[sw,0,1],[sw,sh,1],[0,sh,1]])@source_to_plane.T
    source_coverage=Image.new('L',(sw,sh),0);coverage_draw=ImageDraw.Draw(source_coverage)
    pieces=[]
    atlas_pixels=uvs[ids]*[aw,-ah]+[0,ah]
    normals=[]
    for offset,index in enumerate(ids):
        tri=positions[index]
        plane=np.stack((tri@horizontal,tri@vertical),axis=1)
        determinant=cross2(plane[1]-plane[0],plane[2]-plane[0])
        if abs(determinant)<1e-12:
            raise ValueError(f'Triangle {index} is degenerate in the supplied projection')
        inverse_points=np.column_stack(((plane[:,0]-source_to_plane[0,2])/scale,
                                        (plane[:,1]-source_to_plane[1,2])/(-scale)))
        coverage_draw.polygon([tuple(v) for v in inverse_points],fill=255)
        overlap=clip_polygon(source_corners,plane)
        if len(overlap)<3:
            continue
        plane_to_uv=np.linalg.solve(np.column_stack((plane,np.ones(3))),atlas_pixels[offset]).T
        affine=plane_to_uv[:,:2]@source_to_plane
        affine[:,2]+=plane_to_uv[:,2]
        mapped=np.column_stack((overlap,np.ones(len(overlap))))@plane_to_uv.T
        pieces.append({'triangle':int(index),'polygon':mapped,'affine':affine})
        normals.append(unit(np.cross(tri[1]-tri[0],tri[2]-tri[0])))
    coverage=np.asarray(source_coverage)>0;alpha=np.asarray(source_alpha)
    clipped=int(((alpha>0)&~coverage).sum())
    if clipped and not profile.get('allow_artwork_clipping',False):
        raise ValueError(f'{clipped} visible source pixels fall outside the declared carrier')
    if not pieces:
        raise ValueError('Artwork does not intersect the declared carrier')
    all_points=np.concatenate([p['polygon'] for p in pieces])
    lo=np.maximum(np.floor(all_points.min(0)).astype(int)-3,[0,0])
    hi=np.minimum(np.ceil(all_points.max(0)).astype(int)+3,[aw,ah])
    if profile.get('crop_box') is not None:
        crop=profile['crop_box']
        if not isinstance(crop,list) or len(crop)!=4 or any(type(v) is not int for v in crop):
            raise ValueError('Crop box must contain four integer atlas coordinates')
        x0,y0,x1,y1=crop
        if not (0<=x0<x1<=aw and 0<=y0<y1<=ah):
            raise ValueError('Crop box lies outside the native atlas')
        if x0>lo[0] or y0>lo[1] or x1<hi[0] or y1<hi[1]:
            raise ValueError('Declared crop cuts the projected artwork footprint')
        lo=np.array([x0,y0]);hi=np.array([x1,y1])
    width_px,height_px=(hi-lo).tolist()
    root=ET.Element(tag('svg'),{'width':str(width_px),'height':str(height_px),
                              'viewBox':f'{lo[0]} {lo[1]} {width_px} {height_px}'})
    defs=ET.SubElement(root,tag('defs'))
    ET.SubElement(defs,tag('image'),{'id':'intact-source','x':'0','y':'0','width':str(sw),'height':str(sh),
                  '{'+XLINK+'}href':'data:image/png;base64,'+base64.b64encode(design.read_bytes()).decode('ascii')})
    for i,piece in enumerate(pieces):
        clip=ET.SubElement(defs,tag('clipPath'),{'id':f'face-{i}','clipPathUnits':'userSpaceOnUse'})
        ET.SubElement(clip,tag('polygon'),{'points':' '.join(f'{x:.6f},{y:.6f}' for x,y in piece['polygon'])})
        group=ET.SubElement(root,tag('g'),{'clip-path':f'url(#face-{i})'})
        a=piece['affine'];values=[a[0,0],a[1,0],a[0,1],a[1,1],a[0,2],a[1,2]]
        ET.SubElement(group,tag('use'),{'{'+XLINK+'}href':'#intact-source','transform':'matrix('+','.join(f'{v:.12f}' for v in values)+')'})
    out_svg.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(out_svg,encoding='utf-8',xml_declaration=True)
    report={'source_sha256':hashlib.sha256(design.read_bytes()).hexdigest(),'source_size':[sw,sh],
            'source_alpha_bbox':list(source_alpha.getbbox()),'source_visible_pixels':int((alpha>0).sum()),
            'source_ink_outside_declared_carrier_pixels':clipped,'native_box':[*lo.tolist(),*hi.tolist()],
            'atlas_size':[aw,ah],'physical_canvas_width_m':width,'physical_canvas_height_m':width*sh/sw,
            'horizontal':horizontal.tolist(),'vertical':vertical.tolist(),'normal':n.tolist(),'anchor_world':anchor.tolist(),
            'triangles':[p['triangle'] for p in pieces],'material_id':int(material_ids[0]),
            'physical_normal_max_deviation_degrees':float(max(np.degrees(np.arccos(np.clip(abs(np.dot(n,x)),0,1))) for x in normals)),
            'rgba_recolored':False,'uniform_source_scale_in_declared_plane':True,
            'limits':'Uniform scale is defined in the declared projection plane, not along a bent surface. No visibility or shared-UV resolution is inferred. Check all UV users, actual occlusion, seams and final material. No automatic aesthetic acceptance.'}
    out_svg.with_suffix('.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    return report


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True);parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--design',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    profile=json.loads(args.profile.read_text(encoding='utf-8-sig'))
    if profile.get('model_file_sha256') and hashlib.sha256(args.model.read_bytes()).hexdigest()!=profile['model_file_sha256']:
        raise ValueError('Model file does not match the surface profile')
    with np.load(args.model,allow_pickle=False) as archive:
        model={key:archive[key] for key in archive.files}
    result=map_design(model,profile,args.design,args.out)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
