#!/usr/bin/env python3
"""Prepare paint geometry, render orthographic guides, and project editor overlays.

Python 3.10+, NumPy, Pillow, Numba. Geometry preparation additionally uses a
configured resource decoder. Render is a layout preview, not a
simulation of War Thunder's material shader. Original UVs are never re-unwrapped.
"""
from __future__ import annotations
import argparse
import contextlib
import fnmatch
import json
import math
import os
from pathlib import Path
import sys
import numpy as np
from numba import njit
from PIL import Image,ImageDraw
from inspect_skins import open_rgba,write_json,load_font

ASSET_TOOLS=Path(os.environ.get('WT_ASSET_TOOLS', str(Path.cwd()/'tools'/'war-thunder-assets')))


def paint_image(path):
    if path.suffix.lower() in {'.dds','.tga'}:
        return open_rgba(path)[0]
    if path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.bmp'}:
        raise ValueError('Unsupported paint image format')
    with Image.open(path) as image:
        if image.width*image.height>8192*8192:
            raise ValueError('Paint image exceeds the validated pixel limit')
        image.load()
        return image.convert('RGBA')


def prepare(game,vehicle,resource,output,tools,excluded):
    tools=tools.expanduser().resolve()
    if not (tools/'wt_assets.py').is_file() or not (tools/'dae_backend.py').is_file():
        raise ValueError('Resource decoder is unavailable; configure --tools or WT_ASSET_TOOLS')
    output.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(tools.resolve()))
    from wt_assets import locate
    from dae_backend import load_model
    matches=locate(game.resolve(),vehicle)
    packs=[Path(e['pack']) for e in matches['matches'] if e['name']==vehicle and e['class_id']==0xB4B7D9C4]
    if not packs: raise ValueError(f'No dynamic model {vehicle!r}')
    descriptors=[game/'patch/content/base/res/dynModelDesc.bin',game/'content/base/res/dynModelDesc.bin']
    with (output/'geometry-decode.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        model,_=load_model(packs[0],vehicle,0,descriptors)
    mats={m.getName() for m in model.materials or []
          if m.getTextureSlots()[0] and fnmatch.fnmatchcase(m.getTextureSlots()[0],resource)}
    vertices=[];uvs=[];nodes=[];names=[]
    for obj in model:
        if any(fnmatch.fnmatchcase(obj.name,pattern) for pattern in excluded): continue
        if not set(obj.materials.values()) & mats: continue
        bone=model.skeleton.getNodeByName(obj.name) if model.skeleton is not None and not obj.skinned else None
        name_id=len(names);count=0;current=None
        cache={}
        for index,face in enumerate(obj.faces):
            if index in obj.materials: current=obj.materials[index]
            if current not in mats: continue
            points=[];coords=[]
            for vertex_id in face:
                if vertex_id not in cache:
                    p=model.getVertex(vertex_id,parentBone=bone)
                    uv=model.getUV(vertex_id)
                    cache[vertex_id]=((float(p[0]),float(p[1]),-float(p[2])),(float(uv[0]),float(uv[1])))
                point,uv=cache[vertex_id];points.append(point);coords.append(uv)
            vertices.append(points);uvs.append(coords);nodes.append(name_id);count+=1
        if count: names.append(obj.name)
    if not vertices: raise ValueError('No triangles use the selected color resource')
    points=np.asarray(vertices,dtype=np.float32);coords=np.asarray(uvs,dtype=np.float32)
    if not np.isfinite(points).all() or not np.isfinite(coords).all(): raise ValueError('Nonfinite geometry')
    target=output/'geometry.npz'
    np.savez_compressed(target,triangles=points,uvs=coords,node_ids=np.asarray(nodes,dtype=np.int32),names=np.asarray(names))
    meta={'vehicle':vehicle,'resource':resource,'source_pack':str(packs[0]),'triangles':len(points),'nodes':len(names),
          'coordinates':'Native X/Y, reflected Z; original UV; static assembly transforms applied.',
          'selected_materials':sorted(mats),'excluded_node_patterns':excluded,'layout_only':True}
    write_json(output/'geometry.json',meta)
    return {'geometry':str(target),**meta}


def camera_basis(view):
    axes={
        'left':([-1,0,0],[0,1,0],[0,0,-1]),
        'right':([1,0,0],[0,1,0],[0,0,1]),
        'top':([0,0,1],[1,0,0],[0,1,0]),
        'bottom':([0,0,-1],[1,0,0],[0,-1,0]),
        'front':([0,0,-1],[0,1,0],[1,0,0]),
        'rear':([0,0,1],[0,1,0],[-1,0,0])}
    if view=='iso':
        eye=np.array([1.0,.65,1.0]);eye/=np.linalg.norm(eye)
        right=np.cross(np.array([0.,1.,0.]),eye);right/=np.linalg.norm(right)
        up=np.cross(eye,right)
        return np.stack((right,up,eye)).astype(np.float32)
    return np.asarray(axes[view],dtype=np.float32)


def screen_vertices(triangles,basis,width,height):
    projected=triangles@basis.T
    low=projected[:,:,:2].min(axis=(0,1));high=projected[:,:,:2].max(axis=(0,1))
    center=(low+high)*.5
    scale=min(width*.88/max(float(high[0]-low[0]),1e-6),height*.82/max(float(high[1]-low[1]),1e-6))
    screen=projected.copy()
    screen[:,:,0]=(projected[:,:,0]-center[0])*scale+width*.5
    screen[:,:,1]=(center[1]-projected[:,:,1])*scale+height*.5
    return screen.astype(np.float32),{'basis':basis.tolist(),'center':center.tolist(),'scale':scale,'width':width,'height':height}


@njit(cache=True)
def sample_rgba(texture,u,v):
    if u<0 or u>1: u=u-math.floor(u)
    if v<0 or v>1: v=v-math.floor(v)
    x=min(texture.shape[1]-1,max(0.,u*(texture.shape[1]-1)))
    y=min(texture.shape[0]-1,max(0.,(1-v)*(texture.shape[0]-1)))
    x0=int(x);y0=int(y);x1=min(x0+1,texture.shape[1]-1);y1=min(y0+1,texture.shape[0]-1)
    dx=x-x0;dy=y-y0
    result=np.empty(4,dtype=np.float32)
    for c in range(4):
        result[c]=(texture[y0,x0,c]*(1-dx)+texture[y0,x1,c]*dx)*(1-dy)+(texture[y1,x0,c]*(1-dx)+texture[y1,x1,c]*dx)*dy
    return result


@njit(cache=True)
def rasterize(screen,world,uvs,texture,width,height,handedness=1.):
    frame=np.empty((height,width,3),dtype=np.uint8);frame[:]=238
    depth=np.full((height,width),-np.inf,dtype=np.float32)
    owners=np.full((height,width),-1,dtype=np.int32)
    light=np.array([.3,.85,.4],dtype=np.float32);light/=np.sqrt((light*light).sum())
    for i in range(len(screen)):
        p=screen[i]
        denom=(p[1,1]-p[2,1])*(p[0,0]-p[2,0])+(p[2,0]-p[1,0])*(p[0,1]-p[2,1])
        # Screen Y points down. Outward front faces therefore have negative
        # signed area; do not display the reverse side of closed aircraft skins.
        if denom*handedness>=-1e-8: continue
        xmin=max(0,int(math.floor(p[:,0].min())));xmax=min(width-1,int(math.ceil(p[:,0].max())))
        ymin=max(0,int(math.floor(p[:,1].min())));ymax=min(height-1,int(math.ceil(p[:,1].max())))
        e1=world[i,1]-world[i,0];e2=world[i,2]-world[i,0]
        n=np.cross(e1,e2);length=np.sqrt((n*n).sum())
        shade=.7+.3*abs((n*light).sum()/length) if length>1e-10 else 1.
        for y in range(ymin,ymax+1):
            for x in range(xmin,xmax+1):
                a=((p[1,1]-p[2,1])*(x+.5-p[2,0])+(p[2,0]-p[1,0])*(y+.5-p[2,1]))/denom
                b=((p[2,1]-p[0,1])*(x+.5-p[2,0])+(p[0,0]-p[2,0])*(y+.5-p[2,1]))/denom
                c=1-a-b
                if a<-.0001 or b<-.0001 or c<-.0001: continue
                z=a*p[0,2]+b*p[1,2]+c*p[2,2]
                if z<=depth[y,x]: continue
                u=a*uvs[i,0,0]+b*uvs[i,1,0]+c*uvs[i,2,0]
                v=a*uvs[i,0,1]+b*uvs[i,1,1]+c*uvs[i,2,1]
                color=sample_rgba(texture,u,v)
                for channel in range(3): frame[y,x,channel]=min(255,max(0,int(color[channel]*shade)))
                depth[y,x]=z;owners[y,x]=i
    return frame,depth,owners


def render(geometry,texture_path,views,output,width,height):
    output.mkdir(parents=True,exist_ok=True)
    with np.load(geometry,allow_pickle=False) as data:
        world=data['triangles'];uvs=data['uvs']
    image=paint_image(texture_path);texture=np.asarray(image).copy();image.close()
    records=[]
    for view in views:
        basis=camera_basis(view)
        screen,meta=screen_vertices(world,basis,width,height)
        frame,depth,owners=rasterize(screen,world,uvs,texture,width,height,float(np.linalg.det(basis)))
        Image.fromarray(frame).save(output/(view+'.png'))
        Image.fromarray(((owners>=0)*255).astype(np.uint8)).save(output/(view+'-mask.png'))
        np.savez_compressed(output/(view+'-depth.npz'),depth=depth,owners=owners)
        write_json(output/(view+'.json'),{'view':view,'geometry':str(geometry.resolve()),**meta,
                                           'layout_only':True,'shader':'Approximate diffuse lighting; original game material shader not simulated.'})
        records.append({'view':view,'image':str(output/(view+'.png')),'covered_pixels':int((owners>=0).sum())})
    return {'views':records,'layout_only':True}


@njit(cache=True)
def project_overlay(world,uvs,basis,center,scale,overlay,depth,base,atlas,score,owner,tolerance,min_facing=.45):
    height,width=atlas.shape[:2];view_h,view_w=overlay.shape[:2]
    count=0
    for i in range(len(world)):
        p=np.empty((3,2),dtype=np.float32)
        for k in range(3):
            p[k,0]=uvs[i,k,0]*(width-1);p[k,1]=(1-uvs[i,k,1])*(height-1)
        denom=(p[1,1]-p[2,1])*(p[0,0]-p[2,0])+(p[2,0]-p[1,0])*(p[0,1]-p[2,1])
        if abs(denom)<1e-8: continue
        normal=np.cross(world[i,1]-world[i,0],world[i,2]-world[i,0]);length=np.sqrt((normal*normal).sum())
        if length<1e-10: continue
        # Prepared geometry has outward winding. Taking abs here paints the
        # reverse side of thin wings when it lies inside the depth tolerance.
        facing=(normal*basis[2]).sum()/length
        if facing<min_facing: continue
        xmin=max(0,int(math.floor(p[:,0].min())));xmax=min(width-1,int(math.ceil(p[:,0].max())))
        ymin=max(0,int(math.floor(p[:,1].min())));ymax=min(height-1,int(math.ceil(p[:,1].max())))
        for y in range(ymin,ymax+1):
            for x in range(xmin,xmax+1):
                a=((p[1,1]-p[2,1])*(x+.5-p[2,0])+(p[2,0]-p[1,0])*(y+.5-p[2,1]))/denom
                b=((p[2,1]-p[0,1])*(x+.5-p[2,0])+(p[0,0]-p[2,0])*(y+.5-p[2,1]))/denom
                c=1-a-b
                if a<-.0001 or b<-.0001 or c<-.0001: continue
                point=a*world[i,0]+b*world[i,1]+c*world[i,2]
                sx=(point*basis[0]).sum();sy=(point*basis[1]).sum();z=(point*basis[2]).sum()
                px=int(round((sx-center[0])*scale+view_w*.5));py=int(round((center[1]-sy)*scale+view_h*.5))
                if px<0 or px>=view_w or py<0 or py>=view_h: continue
                if not np.isfinite(depth[py,px]) or z<depth[py,px]-tolerance: continue
                alpha=overlay[py,px,3]/255.
                if alpha<.005: continue
                strength=facing*alpha
                if strength<=score[y,x]: continue
                score[y,x]=strength;owner[y,x]=i
                for channel in range(3): atlas[y,x,channel]=int(overlay[py,px,channel]*alpha+base[y,x,channel]*(1-alpha))
                count+=1
    return count


def bake(geometry,base_path,overlays,output,min_facing):
    with np.load(geometry,allow_pickle=False) as data: world=data['triangles'];uvs=data['uvs']
    image=paint_image(base_path);base=np.asarray(image).copy();image.close()
    canvas=base.copy();score=np.zeros(base.shape[:2],dtype=np.float32);owner=np.full(base.shape[:2],-1,dtype=np.int32)
    records=[]
    # Shared UV/view conflicts choose highest facing*alpha candidate. Each
    # candidate composites against the original base, not a prior candidate.
    for spec in overlays:
        view_file,overlay_file=spec.split('=',1)
        meta=json.loads(Path(view_file).read_text(encoding='utf-8'))
        with Image.open(overlay_file) as bitmap: overlay=np.asarray(bitmap.convert('RGBA')).copy()
        if overlay.shape[:2]!=(meta['height'],meta['width']): raise ValueError('Overlay must keep the exact orthographic canvas dimensions')
        if Path(meta['geometry']).resolve()!=geometry.resolve(): raise ValueError('Camera guide belongs to different geometry')
        depth_file=Path(view_file).with_name(Path(view_file).stem+'-depth.npz')
        with np.load(depth_file,allow_pickle=False) as data: depth=data['depth']
        # Keep original RGB available for every winning replacement.
        candidate=base.copy();local_score=np.zeros(base.shape[:2],dtype=np.float32);local_owner=np.full(base.shape[:2],-1,dtype=np.int32)
        hits=project_overlay(world,uvs,np.asarray(meta['basis'],dtype=np.float32),np.asarray(meta['center'],dtype=np.float32),
                             meta['scale'],overlay,depth,base,candidate,local_score,local_owner,3.0/meta['scale'],min_facing)
        wins=local_score>score
        canvas[wins]=candidate[wins];score[wins]=local_score[wins];owner[wins]=local_owner[wins]
        records.append({'view':meta['view'],'overlay':str(Path(overlay_file).resolve()),'candidate_writes':hits,'winning_pixels':int(wins.sum())})
    output.parent.mkdir(parents=True,exist_ok=True)
    Image.fromarray(canvas).save(output)
    Image.fromarray(((score>0)*255).astype(np.uint8)).save(output.with_name(output.stem+'-paint-mask.png'))
    meta={'output':str(output.resolve()),'painted_pixels':int((score>0).sum()),'alpha_preserved':bool(np.array_equal(canvas[:,:,3],base[:,:,3])),
          'overlays':records,'shared_uv_policy':'Highest facing*alpha; overlapping independent designs need review.'}
    write_json(output.with_suffix('.projection.json'),meta)
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True)
    a=subs.add_parser('prepare');a.add_argument('--game',type=Path,required=True);a.add_argument('--vehicle',required=True)
    a.add_argument('--resource',required=True);a.add_argument('--tools',type=Path,default=ASSET_TOOLS);a.add_argument('--out',type=Path,required=True)
    a.add_argument('--exclude-node',action='append',default=[],help='Exclude a node glob for the chosen display/paint state')
    a=subs.add_parser('render');a.add_argument('--geometry',type=Path,required=True);a.add_argument('--texture',type=Path,required=True)
    a.add_argument('--view',choices=['left','right','top','bottom','front','rear','iso'],action='append',required=True)
    a.add_argument('--width',type=int,default=1536);a.add_argument('--height',type=int,default=640);a.add_argument('--out',type=Path,required=True)
    a=subs.add_parser('bake');a.add_argument('--geometry',type=Path,required=True);a.add_argument('--base',type=Path,required=True)
    a.add_argument('--overlay',action='append',required=True,help='camera.json=editor-overlay.png');a.add_argument('--out',type=Path,required=True)
    a.add_argument('--min-facing',type=float,default=.45,help='Reject surfaces near edge-on to the projection (0..1)')
    args=p.parse_args()
    try:
        if args.command=='prepare': result=prepare(args.game,args.vehicle,args.resource,args.out,args.tools,args.exclude_node)
        elif args.command=='render':
            if not 128<=args.width<=4096 or not 128<=args.height<=4096: raise ValueError('View dimensions must be 128..4096')
            result=render(args.geometry,args.texture,args.view,args.out,args.width,args.height)
        else:
            if not 0<=args.min_facing<=1: raise ValueError('--min-facing must be 0..1')
            result=bake(args.geometry,args.base,args.overlay,args.out,args.min_facing)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,ImportError) as exc:
        print(f'Surface workflow failed: {exc}',file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
