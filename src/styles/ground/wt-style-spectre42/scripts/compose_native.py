"""Compose approved module placements into a target's own native UV colour maps.

Consumes measured profiles, not guessed vehicle names. Never edits N/AO, invokes
retired reprojection tools, deploys a skin, or changes a source file.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import numpy as np
from PIL import Image, ImageChops, ImageDraw
from style_quality import authorize,check_detail
from source_model_uv import validate_plan as validate_source_model_uv

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def safe_id(s):
    if not isinstance(s,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}',s):
        raise ValueError('IDs must be 1..80 ASCII letters, digits, underscore or hyphen')
    if re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])',s,re.IGNORECASE):
        raise ValueError('Reserved Windows filename')
    return s

def read_image(path):
    with Image.open(path) as im:
        if max(im.size)>8192 or min(im.size)<1:raise ValueError('Texture dimension outside 1..8192')
        im.load();return im.convert('RGBA')

def path_at(root,value):
    if not isinstance(value,str) or not value:raise ValueError('Missing file path')
    return (root/value).resolve(strict=True)

def mask_at(root,spec,size):
    p=path_at(root,spec['file'])
    if sha(p)!=spec['sha256']:raise ValueError(f'Mask hash mismatch: {p.name}')
    with Image.open(p) as im:
        if im.size!=size or im.mode!='L':raise ValueError('Mask must be an L image at native dimensions')
        pixels=np.asarray(im)
        if not np.logical_or(pixels==0,pixels==255).all():raise ValueError('Native approval masks must be binary (0/255)')
        return im.copy()

def points(value,size,count=None):
    if not isinstance(value,list) or (count and len(value)!=count) or len(value)<3:raise ValueError('Invalid polygon')
    p=np.asarray(value,dtype=float)
    if p.shape!=(len(value),2) or not np.isfinite(p).all():raise ValueError('Invalid coordinates')
    w,h=size
    if (p<0).any() or (p[:,0]>w-1).any() or (p[:,1]>h-1).any():raise ValueError('Coordinates outside native texture')
    cross=[]
    for i in range(len(p)):
        a=p[(i+1)%len(p)]-p[i];b=p[(i+2)%len(p)]-p[(i+1)%len(p)]
        cross.append(a[0]*b[1]-a[1]*b[0])
    if not (all(c>1e-6 for c in cross) or all(c< -1e-6 for c in cross)):
        raise ValueError('Use a strictly convex polygon; split concave surfaces into subregions')
    return [tuple(map(float,xy)) for xy in p]

def load(profile_path,plan_path):
    root=profile_path.resolve().parent
    profile=json.loads(profile_path.read_text(encoding='utf-8-sig'))
    plan=json.loads(plan_path.read_text(encoding='utf-8-sig'))
    if profile.get('schema_version')!=1 or plan.get('schema_version')!=2:raise ValueError('Use explicit asset contract plan schema 2')
    validate_source_model_uv(plan_path,plan)
    catalog_path=path_at(plan_path.resolve().parent,plan.get('catalog'))
    if sha(catalog_path)!=plan.get('catalog_sha256'):raise ValueError('Asset catalog lock mismatch')
    catalog=json.loads(catalog_path.read_text(encoding='utf-8'))
    if catalog.get('schema_version')!=2:raise ValueError('Use unified asset catalog schema 2')
    catalog_assets={r['id']:r for r in catalog['assets']}
    intent=plan.get('intent','style_transfer')
    if not profile.get('vehicle') or not profile.get('uv_evidence'):raise ValueError('Vehicle identity and UV evidence are required')
    if plan.get('profile_sha256')!=sha(profile_path):raise ValueError('Plan does not match the frozen profile')
    inputs={};surfaces={};texture_ids=set();surface_ids=set()
    for key,t in profile['textures'].items():
        safe_id(key)
        if key.casefold() in texture_ids:raise ValueError('Case-insensitive duplicate texture ID')
        texture_ids.add(key.casefold())
        p=path_at(root,t['file'])
        if sha(p)!=t['sha256']:raise ValueError(f'Texture hash mismatch: {key}')
        if t.get('alpha_semantics')!='fixed_rgb' or t.get('color_space')!='srgb':
            raise ValueError('This composer supports fixed_rgb sRGB colour only; use the toolkit for other semantics')
        im=read_image(p)
        paint=mask_at(root,t['paint_mask'],im.size)
        protected=mask_at(root,t['protected_mask'],im.size)
        inputs[key]={'image':im,'allowed':ImageChops.subtract(paint,protected),'path':p}
    for s in profile['surfaces']:
        key=safe_id(s['id'])
        if key.casefold() in surface_ids:raise ValueError('Case-insensitive duplicate surface ID')
        surface_ids.add(key.casefold())
        if s['texture'] not in inputs:raise ValueError('Unknown texture')
        if s.get('verified') is not True or not s.get('evidence'):raise ValueError(f'Unverified surface: {key}')
        if s.get('sharing') not in ('unique','repeated','mirrored'):raise ValueError('Explicit sharing declaration required')
        if s['sharing']!='unique' and not s.get('peers'):raise ValueError('Shared surfaces need a peer inventory')
        s['polygon_px']=points(s['polygon_px'],inputs[s['texture']]['image'].size)
        if s.get('rotation_deg') not in (0,90,180,270):raise ValueError('Surface readable orientation must be explicit')
        surfaces[key]=s
    if not plan.get('placements'):raise ValueError('Empty plan is not a produced skin')
    asset_root=plan_path.resolve().parent
    resolved=[]
    ids=set()
    for placement in plan['placements']:
        key=safe_id(placement['id'])
        if key.casefold() in ids:raise ValueError('Case-insensitive duplicate placement ID')
        ids.add(key.casefold())
        if placement['surface'] not in surfaces:raise ValueError('Unknown surface in plan')
        s=surfaces[placement['surface']]
        if not placement.get('reason'):raise ValueError('Each placement needs a local design purpose')
        record=catalog_assets.get(placement.get('asset_id'))
        if not record or placement.get('kind')!=record['kind']:raise ValueError('Explicit asset_id and matching kind required')
        authorize(record,intent,catalog_path.parent)
        if record.get('trial_eligible') is not True:raise ValueError('Asset is not eligible for vehicle trials')
        has_text=record.get('contains_text',True)
        if has_text and s['sharing']=='mirrored':raise ValueError('Readable text on mirrored shared UV is not supported')
        if has_text and s.get('planar') is not True:raise ValueError('Text needs one verified planar carrier')
        if has_text and placement.get('text_height_px',0)<8:raise ValueError('Text height must be declared and at least eight final texture pixels')
        if has_text and placement.get('allow_clip'):raise ValueError('Do not clip text modules')
        if s['sharing']!='unique' and placement.get('accept_shared') is not True:raise ValueError('Shared-UV impact not acknowledged')
        opacity=placement.get('opacity',1)
        if type(opacity) not in (int,float) or not math.isfinite(opacity) or not 0<opacity<=1:raise ValueError('Invalid opacity')
        asset=path_at(asset_root,placement['asset'])
        if sha(asset)!=placement['asset_sha256']:raise ValueError('Asset hash mismatch')
        if sha(asset)!=record['sha256']:raise ValueError('Selected pixels differ from frozen catalog asset')
        quad=points(placement['quad_px'],inputs[s['texture']]['image'].size,4)
        if intent=='style_transfer':
            check_detail(record,quad,read_image(asset).size,s['rotation_deg'],plan.get('quality_budget'))
        resolved.append((placement,s,asset,quad))
    return profile,plan,inputs,resolved

def warp(im,quad,size):
    # Inverse projective transform: native output pixel -> module source pixel.
    corners=[(0,0),(im.width-1,0),(im.width-1,im.height-1),(0,im.height-1)]
    a=[];b=[]
    for (x,y),(u,v) in zip(quad,corners):
        a.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]])
        b.extend([u,v])
    matrix=np.asarray(a,float)
    if np.linalg.cond(matrix)>1e14:raise ValueError('Degenerate or unstable placement transform')
    coeff=np.linalg.solve(matrix,b)
    # Coverage alpha must be premultiplied when filtering decals, unlike source C alpha.
    return im.convert('RGBa').transform(size,Image.Transform.PERSPECTIVE,coeff,
        resample=Image.Resampling.BICUBIC,fillcolor=(0,0,0,0)).convert('RGBA')

def compose(profile_path:Path,plan_path:Path,out:Path,dry=False):
    profile,plan,inputs,resolved=load(profile_path,plan_path)
    if dry:return {'profile_valid':True,'placements':len(resolved),'vehicle':profile['vehicle']}
    out=out.resolve()
    if out.exists():raise FileExistsError('Use a new output directory')
    out.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.spectre-stage-',dir=out.parent))
    try:
        (stage/'layers').mkdir();(stage/'colors').mkdir();(stage/'preview').mkdir()
        merged={k:v['image'].copy() for k,v in inputs.items()}
        receipts=[]
        for placement,s,asset,quad in resolved:
            key=s['texture'];size=merged[key].size
            im=read_image(asset).rotate(s['rotation_deg'],expand=True)
            layer=warp(im,quad,size)
            area=Image.new('L',size);ImageDraw.Draw(area).polygon(s['polygon_px'],fill=255)
            allowed=ImageChops.multiply(area,inputs[key]['allowed'])
            original=layer.getchannel('A')
            coverage=ImageChops.multiply(original,allowed)
            total=float(np.asarray(original,dtype=float).sum())
            kept=float(np.asarray(coverage,dtype=float).sum())/total if total else 0
            if kept<0.98 and placement.get('allow_clip') is not True:
                raise ValueError(f"{placement['id']}: {1-kept:.1%} lies outside its approved surface; explicitly re-layout or allow clipping")
            if kept==0:raise ValueError('Placement has no visible coverage')
            alpha=coverage.point(lambda v:round(v*placement.get('opacity',1)))
            layer.putalpha(alpha)
            layer.save(stage/'layers'/(placement['id']+'.png'))
            # Never alpha-composite onto a zero-A game C map: its RGB still matters.
            rgb=Image.composite(layer.convert('RGB'),merged[key].convert('RGB'),alpha)
            merged[key]=Image.merge('RGBA',(*rgb.split(),inputs[key]['image'].getchannel('A')))
            receipts.append({'id':placement['id'],'surface':s['id'],'asset_sha256':sha(asset),'coverage_retained':kept})
        outputs=[]
        for key,im in merged.items():
            original=np.asarray(inputs[key]['image']);result=np.asarray(im)
            outside=np.asarray(inputs[key]['allowed'])==0
            if not np.array_equal(original[:,:,3],result[:,:,3]):raise RuntimeError('Alpha changed')
            if not np.array_equal(original[outside],result[outside]):raise RuntimeError('Protected pixels changed')
            im.save(stage/'colors'/(key+'.png'))
            im.convert('RGB').save(stage/'preview'/(key+'.png'))
            outputs.append({'id':key,'sha256':sha(stage/'colors'/(key+'.png')),'alpha_exact':True,'protected_pixels_exact':True})
        report={'vehicle':profile['vehicle'],'intent':plan.get('intent','style_transfer'),'profile_sha256':sha(profile_path),'plan_sha256':sha(plan_path),
                'placements':receipts,'outputs':outputs,'normal_ao':'not_modified','game':'not_run',
                'visual':'pending','scope':'native colour composition only; not a full transferred vehicle validation'}
        (stage/'composition.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        stage.rename(out)
        return report
    except BaseException:
        shutil.rmtree(stage)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['check','compose']);p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path)
    a=p.parse_args()
    if a.command=='compose' and a.out is None:p.error('--out is required for compose')
    print(json.dumps(compose(a.profile,a.plan,a.out,dry=a.command=='check'),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
