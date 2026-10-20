"""Transfer artwork per texel between native UV atlases through 3D surfaces."""
from __future__ import annotations
import argparse
import json
import os
import tempfile
from pathlib import Path
import sys
os.environ.setdefault('NUMBA_CACHE_DIR', str(Path(tempfile.gettempdir())/'endfield-tank-numba'))
import cv2
import moderngl
import numpy as np
from numba import njit
from PIL import Image

VS = '''#version 430
in vec3 p; in vec3 n; in vec2 uv; in float tag; in float paintable;
out vec3 pos; out vec3 norm; out vec2 target_tc;
flat out int component_tag; flat out int can_paint;
void main(){pos=p;norm=n;target_tc=vec2(uv.x,1.-uv.y);component_tag=int(tag+.5);can_paint=int(paintable+.5);gl_Position=vec4(uv*2.-1.,0.,1.);}
'''
FS = '''#version 430
in vec3 pos; in vec3 norm; in vec2 target_tc;
flat in int component_tag; flat in int can_paint;
layout(location=0) out vec4 out_c;
layout(location=1) out vec4 out_n;
layout(location=2) out vec4 out_debug;
struct Box{vec4 lo;vec4 hi;};
layout(std430,binding=0) readonly buffer Boxes{Box boxes[];};
layout(std430,binding=1) readonly buffer Triangles{vec4 tris[];};
uniform sampler2D source_c,source_n,source_base_n,target_c,target_n,design_logo;
uniform vec3 source_offset;
uniform float radius;
uniform int material_role;
uniform int normal_mode;
#ifdef TRANSFER_AO
uniform sampler2D source_ao,target_ao;
layout(location=3) out vec4 out_ao;
#endif
float owner_depth_override=-1.;
float source_ao_weight=1.;
float boxDist(vec3 p,vec3 lo,vec3 hi){vec3 q=max(max(lo-p,p-hi),vec3(0));return dot(q,q);}
vec3 baryClosest(vec3 p,vec3 a,vec3 b,vec3 c){
 vec3 ab=b-a,ac=c-a,ap=p-a;float d1=dot(ab,ap),d2=dot(ac,ap);
 if(d1<=0.&&d2<=0.)return vec3(1,0,0);
 vec3 bp=p-b;float d3=dot(ab,bp),d4=dot(ac,bp);
 if(d3>=0.&&d4<=d3)return vec3(0,1,0);
 float vc=d1*d4-d3*d2;
 if(vc<=0.&&d1>=0.&&d3<=0.){float v=d1/(d1-d3);return vec3(1.-v,v,0);}
 vec3 cp=p-c;float d5=dot(ab,cp),d6=dot(ac,cp);
 if(d6>=0.&&d5<=d6)return vec3(0,0,1);
 float vb=d5*d2-d1*d6;
 if(vb<=0.&&d2>=0.&&d6<=0.){float w=d2/(d2-d6);return vec3(1.-w,0,w);}
 float va=d3*d6-d5*d4;
 if(va<=0.&&d4-d3>=0.&&d5-d6>=0.){float w=(d4-d3)/((d4-d3)+(d5-d6));return vec3(0,1.-w,w);}
 float f=1./(va+vb+vc),v=vb*f,w=vc*f;return vec3(1.-v-w,v,w);
}
int query(vec3 point,vec3 N,out vec3 weights,out float dist,out float alignment){
 int stack[64];int count=1;stack[0]=0;int chosen=-1;
 float best=radius*radius;dist=radius;alignment=0.;
 while(count>0){
  int k=stack[--count];Box b=boxes[k];if(boxDist(point,b.lo.xyz,b.hi.xyz)>best)continue;
  int left=int(b.lo.w),right=int(b.hi.w);
  if(left<0){
   for(int j=0;j<right;j++){
    int i=-left-1+j,q=i*6;
    vec3 sn=normalize(tris[q+3].xyz+tris[q+4].xyz+tris[q+5].xyz);
    float an=dot(sn,N);if(an<.55)continue;
    vec3 w=baryClosest(point,tris[q].xyz,tris[q+1].xyz,tris[q+2].xyz);
    vec3 hit=tris[q].xyz*w.x+tris[q+1].xyz*w.y+tris[q+2].xyz*w.z;
    float d=dot(hit-point,hit-point),cost=d+.00012*(1.-an);
    if(cost<best){best=cost;chosen=i;weights=w;dist=sqrt(d);alignment=an;}
   }
  }else if(count<62){
   float dl=boxDist(point,boxes[left].lo.xyz,boxes[left].hi.xyz);
   float dr=boxDist(point,boxes[right].lo.xyz,boxes[right].hi.xyz);
   if(dl<dr){stack[count++]=right;stack[count++]=left;}
   else{stack[count++]=left;stack[count++]=right;}
  }
 }
 return chosen;
}
mat3 tangentFrame(vec3 N,vec3 dp1,vec3 dp2,vec2 a,vec2 b){
 float det=a.x*b.y-a.y*b.x;if(abs(det)<1e-12)return mat3(1);
 vec3 T=(dp1*b.y-dp2*a.y)/det,Braw=(dp2*a.x-dp1*b.x)/det;
 T=normalize(T-N*dot(N,T));vec3 B=normalize(cross(N,T))*(dot(cross(N,T),Braw)<0.?-1.:1.);
 return mat3(T,B,N);
}
vec3 normalValue(vec4 value){vec2 xy=value.ga*2.-1.;xy*=min(1.,.995/max(length(xy),.001));return vec3(xy,sqrt(max(.0001,1.-dot(xy,xy))));}
// COATING_HOOK
void main(){
 vec3 N=normalize(norm);vec4 stock=texture(target_c,target_tc),pbr=texture(target_n,target_tc);
 float paint=smoothstep(.10,.70,stock.a);
 #ifdef TRANSFER_AO
 vec4 transferred_ao=texture(target_ao,target_tc);
 #endif
 vec3 bare=stock.rgb;
 vec3 fallback=mix(bare,N.y>.4?vec3(.165):vec3(.73,.735,.72),paint);
 vec4 color=vec4(fallback,1);float dist,align;vec3 weights;bool matched=false;
 int index=query(pos+source_offset,N,weights,dist,align);
 if(index>=0){
  matched=true;int q=index*6;
  vec2 u0=vec2(tris[q].w,1.-tris[q+3].w),u1=vec2(tris[q+1].w,1.-tris[q+4].w),u2=vec2(tris[q+2].w,1.-tris[q+5].w);
  vec2 st=u0*weights.x+u1*weights.y+u2*weights.z;
  color=vec4(texture(source_c,st).rgb,1);
  #ifdef TRANSFER_AO
  transferred_ao=texture(source_ao,st);
  #endif
  vec4 authored=texture(source_n,st),old_base=texture(source_base_n,st);
  vec3 sn=normalize(tris[q+3].xyz*weights.x+tris[q+4].xyz*weights.y+tris[q+5].xyz*weights.z);
  mat3 sf=tangentFrame(sn,tris[q+1].xyz-tris[q].xyz,tris[q+2].xyz-tris[q].xyz,u1-u0,u2-u0);
  mat3 tf=tangentFrame(N,dFdx(pos),dFdy(pos),dFdx(target_tc),dFdy(target_tc));
  vec3 delta=sf*(normalValue(authored)-normalValue(old_base));
  float trust=(1.-smoothstep(.003,.035,dist))*smoothstep(.85,.99,align);
  vec3 world=normalize(tf*normalValue(pbr)+delta*trust);
  vec3 tn=transpose(tf)*world;
  if(normal_mode==1)tn=transpose(tf)*(sf*normalValue(authored));
  if(normal_mode!=2)pbr.ga=clamp(tn.xy*.5+.5,0.,1.);
  pbr.rb=authored.rb;
 }
 bool recoated=false;
 applyCoating(pos,N,stock,paint,matched,color,pbr,recoated);
 out_c=vec4(color.rgb,1);out_n=pbr;
 out_debug=vec4(matched?1.:0.,clamp(dist/radius,0.,1.),align,1.);
 #ifdef TRANSFER_AO
 out_ao=mix(texture(target_ao,target_tc),transferred_ao,clamp(source_ao_weight,0.,1.));
 #endif
 gl_FragDepth=owner_depth_override>=0.?owner_depth_override:(recoated?.02:(matched?.15+.20*clamp(dist/radius,0.,1.):.8));
}
'''


def select(g, resource, model_dir=None):
    if model_dir is not None:
        materials=json.loads((model_dir/'materials.json').read_text(encoding='utf-8'))['materials']
        names={m['obj_name'] for m in materials if m.get('texture_slots') and (m['texture_slots'][0] or '').rstrip('*')==resource}
        ids=[i for i,n in enumerate(g['material_names']) if n in names]
    else:
        ids=[i for i,n in enumerate(g['material_names']) if str(n).startswith(resource.removesuffix('_c')+'_')]
    if not ids:
        raise ValueError('Missing material for '+resource)
    return np.flatnonzero(np.isin(g['material_ids'],ids))


def bvh(geometry, faces):
    positions=geometry['positions'][faces];normals=geometry['normals'][faces];uvs=geometry['uvs'][faces]
    lo=positions.min(1);hi=positions.max(1);centers=(lo+hi)*.5
    boxes=[];order=[]
    def split(indices):
        k=len(boxes);boxes.append(None)
        minimum=lo[indices].min(0);maximum=hi[indices].max(0)
        if len(indices)<=8:
            left=-len(order)-1;right=len(indices);order.extend(indices.tolist())
        else:
            axis=int(np.argmax(np.ptp(centers[indices],axis=0)));half=len(indices)//2
            ids=indices[np.argpartition(centers[indices,axis],half)]
            left=split(ids[:half]);right=split(ids[half:])
        boxes[k]=[list(minimum)+[left],list(maximum)+[right]]
        return k
    split(np.arange(len(faces)))
    order=np.asarray(order)
    tri=np.zeros((len(faces),6,4),dtype='f4')
    tri[:,:3,:3]=positions[order];tri[:,3:,:3]=normals[order]
    tri[:,:3,3]=uvs[order,:,0];tri[:,3:,3]=uvs[order,:,1]
    return np.asarray(boxes,dtype='f4'),tri


@njit
def bleed_ring(color,normal,mask,ys,xs):
    h,w=mask.shape
    for i in range(len(ys)):
        y,x=ys[i],xs[i];found=False
        for dy in range(-1,2):
            for dx in range(-1,2):
                yy,xx=y+dy,x+dx
                if 0<=yy<h and 0<=xx<w and mask[yy,xx]:
                    color[y,x]=color[yy,xx];normal[y,x]=normal[yy,xx];found=True;break
            if found:break


@njit
def component_coating(indices,areas,vertex_count,minimum_area):
    parent=np.arange(vertex_count)
    for row in indices:
        roots=np.empty(3,dtype=np.int64)
        for k in range(3):
            v=row[k]
            while parent[v]!=v:
                parent[v]=parent[parent[v]];v=parent[v]
            roots[k]=v
        parent[roots[1]]=roots[0];parent[roots[2]]=roots[0]
    labels=np.empty(len(indices),dtype=np.int64)
    totals=np.zeros(vertex_count,dtype=np.float64)
    for i in range(len(indices)):
        v=indices[i,0]
        while parent[v]!=v:
            parent[v]=parent[parent[v]];v=parent[v]
        labels[i]=v;totals[v]+=areas[i]
    result=np.zeros(len(indices),dtype=np.float32)
    for i in range(len(indices)):
        result[i]=1. if totals[labels[i]]>=minimum_area else 0.
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--part',required=True)
    a=p.parse_args();cfgpath=a.config.resolve();cfg=json.loads(cfgpath.read_text(encoding='utf-8'))
    resolve=lambda value:(cfgpath.parent/value).resolve()
    runtime_scripts=cfg.get('runtime',{}).get('skill_scripts')
    sys.path.insert(0,str(resolve(runtime_scripts) if runtime_scripts else Path(__file__).resolve().parent))
    from tank_core import load_obj,load_image,write_json
    part=cfg['parts'][a.part];paths={k:resolve(v) for k,v in part['inputs'].items()}
    normal_modes={'delta':0,'source':1,'target':2}
    if part.get('normal_mode','delta') not in normal_modes:raise ValueError('normal_mode must be delta, source or target')
    transfer_ao='source_ao' in paths or 'target_ao' in paths
    if transfer_ao and not {'source_ao','target_ao'}<=paths.keys():raise ValueError('AO transfer requires both source_ao and target_ao')
    required={'source_model','target_model','source_c','source_n','source_base_n','target_c','target_n','coating_shader'}
    missing=required-paths.keys()
    if missing:raise ValueError('Missing input fields: '+', '.join(sorted(missing)))
    for name,path in paths.items():
        if not path.exists():raise FileNotFoundError(f'{name}: {path}')
    output=resolve(part['output'])
    if output.exists():raise FileExistsError('Choose a new bake version: '+str(output))
    output.mkdir(parents=True)
    def geometry(folder,label):
        obj=folder/'assembly.obj';existing=folder/'geometry.npz'
        cache=existing if existing.exists() and existing.stat().st_mtime>=obj.stat().st_mtime else output/(label+'-geometry.npz')
        return load_obj(obj,cache)
    source=geometry(paths['source_model'],'source')
    target=geometry(paths['target_model'],'target')
    sf=select(source,part['source_resource'],paths['source_model']);tf=select(target,part['target_resource'],paths['target_model'])
    # A tiny part can use repeating UVs that span the entire atlas. Such faces
    # sample the atlas but must not own every texel during a surface bake.
    all_target_count=len(tf)
    density_limit=part.get('minimum_uv_owner_density',0.)
    if density_limit>0:
        pu=target['uvs'][tf];pp=target['positions'][tf]
        edge_a=pu[:,1]-pu[:,0];edge_b=pu[:,2]-pu[:,0]
        ua=np.abs(edge_a[:,0]*edge_b[:,1]-edge_a[:,1]*edge_b[:,0])*.5
        pa=np.linalg.norm(np.cross(pp[:,1]-pp[:,0],pp[:,2]-pp[:,0]),axis=1)*.5
        owners=(ua<1e-12)|(pa/np.maximum(ua,1e-20)>=density_limit)
        tf=tf[owners]
    excluded_faces=all_target_count-len(tf)
    positions=target['positions'][tf];normals=target['normals'][tf];uvs=target['uvs'][tf]
    tags=np.zeros(len(tf),dtype='f4')
    face_names=target['node_names'][target['node_ids'][tf]]
    for name,value in part.get('node_tags',{}).items():tags[face_names==name]=value
    paintable=np.ones(len(tf),dtype='f4')
    minimum_component_area=part.get('coating_component_min_area',0.)
    if minimum_component_area>0:
        vertices,inverse=np.unique(np.round(positions.reshape(-1,3),5),axis=0,return_inverse=True)
        face_area=np.linalg.norm(np.cross(positions[:,1]-positions[:,0],positions[:,2]-positions[:,0]),axis=1)*.5
        paintable=component_coating(inverse.reshape(-1,3),face_area,len(vertices),minimum_component_area)
    shader=paths['coating_shader'].read_text(encoding='utf-8')
    ctx=moderngl.create_standalone_context(require=430)
    fragment=FS.replace('// COATING_HOOK',shader)
    if transfer_ao:fragment=fragment.replace('#version 430','#version 430\n#define TRANSFER_AO')
    prog=ctx.program(vertex_shader=VS,fragment_shader=fragment)
    boxes,triangles=bvh(source,sf)
    buffers=[ctx.buffer(boxes.tobytes()),ctx.buffer(triangles.tobytes())]
    for i,b in enumerate(buffers):b.bind_to_storage_buffer(i)
    vertices=np.concatenate([positions,normals,uvs,np.broadcast_to(tags[:,None,None],(len(tf),3,1)),np.broadcast_to(paintable[:,None,None],(len(tf),3,1))],axis=2).astype('f4')
    fields=['3f','3f','2f'];attributes=['p','n','uv']
    for name in ['tag','paintable']:
        fields.append('1f' if name in prog else '4x')
        if name in prog:attributes.append(name)
    vb=ctx.buffer(vertices.tobytes());vao=ctx.vertex_array(prog,[(vb,' '.join(fields),*attributes)])
    textures=[]
    for i,name in enumerate(['source_c','source_n','source_base_n','target_c','target_n','design_logo','source_ao','target_ao']):
        if name not in prog:continue
        image=load_image(paths[name]) if name in paths else Image.new('RGBA',(1,1),(0,0,0,0))
        t=ctx.texture(image.size,4,image.tobytes(),alignment=1)
        t.filter=(moderngl.LINEAR,moderngl.LINEAR);t.repeat_x=False;t.repeat_y=False
        t.use(i);prog[name].value=i;textures.append(t)
    prog['radius'].value=part.get('radius',.18)
    prog['source_offset'].value=tuple(part.get('source_offset',[0,0,0]))
    if 'material_role' in prog:prog['material_role'].value=part['role']
    if 'normal_mode' in prog:prog['normal_mode'].value=normal_modes[part.get('normal_mode','delta')]
    w,h=part['size'];images=[ctx.texture((w,h),4) for _ in range(4 if transfer_ao else 3)]
    fbo=ctx.framebuffer(images,ctx.depth_renderbuffer((w,h)));fbo.use();fbo.clear(0,0,0,0,depth=1.)
    ctx.enable(moderngl.DEPTH_TEST);ctx.disable(moderngl.CULL_FACE)
    for y in range(0,h,512):
        for x in range(0,w,512):
            ctx.scissor=(x,y,min(512,w-x),min(512,h-y));vao.render();ctx.finish()
        print(a.part,'row',min(y+512,h),'/',h,flush=True)
    ctx.scissor=None
    arrays=[np.frombuffer(fbo.read(attachment=i,components=4,alignment=1),dtype='u1').reshape(h,w,4)[::-1].copy() for i in range(4 if transfer_ao else 3)]
    color,normal,debug=arrays[:3]
    ao=arrays[3] if transfer_ao else None
    used=(color[:,:,3]>0).astype('u1')
    # Explicit masks are case data. Include collapsed walls' bilinear sampling footprint.
    e1=uvs[:,1]-uvs[:,0];e2=uvs[:,2]-uvs[:,0]
    area=np.abs(e1[:,0]*e2[:,1]-e1[:,1]*e2[:,0])
    centers=positions.mean(1)
    collapsed=area<1e-12
    collapsed_faces=0
    native_image=load_image(paths['target_n'])
    native_n=np.asarray(Image.merge('RGBA',tuple(b.resize((w,h),Image.Resampling.BILINEAR) for b in native_image.split())))
    for region in part.get('collapsed_uv_regions',[]):
        lo,hi=np.asarray(region['bounds'])
        active=collapsed&np.all(centers>=lo,axis=1)&np.all(centers<=hi,axis=1)
        mask=np.zeros((h,w),dtype='u1')
        for t in uvs[active]:
            points=np.rint(np.c_[t[:,0]*w-.5,(1-t[:,1])*h-.5]).astype('i4')
            cv2.polylines(mask,[points],True,255,thickness=5)
        hit=mask>0
        color[hit,:3]=region['rgb'];normal[hit]=native_n[hit]
        if region.get('packed_rb') is not None:
            normal[hit,0]=region['packed_rb'][0];normal[hit,2]=region['packed_rb'][1]
        used[hit]=1;collapsed_faces+=int(active.sum())
    original_used=used.copy()
    for _ in range(8):
        expanded=cv2.dilate(used,np.ones((3,3),dtype='u1'));ys,xs=np.where((expanded>0)&(used==0))
        bleed_ring(color,normal,used,ys,xs)
        if transfer_ao:bleed_ring(ao,ao,used,ys,xs)
        used=expanded
    color[used==0]=[42,42,42,0];normal[used==0]=[125,128,6,128]
    color[:,:,3]=0
    Image.fromarray(color).save(output/'color.png',compress_level=3)
    Image.fromarray(color[:,:,:3]).save(output/'color-view.png',compress_level=3)
    Image.fromarray(normal).save(output/'normal.png',compress_level=3)
    Image.fromarray(original_used*255).save(output/'used.png')
    Image.fromarray(debug[:,:,:3]).save(output/'mapping-diagnostic.png')
    if transfer_ao:
        ao[used==0]=255
        Image.fromarray(ao).save(output/'ao.png',compress_level=3)
    matched=(debug[:,:,0]>200)&(original_used>0)
    write_json(output/'bake-report.json',dict(part=a.part,size=[w,h],used_texels=int(original_used.sum()),
               matched_texels=int(matched.sum()),matched_used_fraction=float(matched.sum()/max(1,original_used.sum())),
               source_radius_m=part.get('radius',.18),collapsed_wall_faces=collapsed_faces,
               non_owner_tiled_faces_excluded=excluded_faces,minimum_uv_owner_density=density_limit,
               coating_component_min_area=minimum_component_area,paintable_faces=int(paintable.sum()),
               method='Per-texel closest surface BVH; original source UV interpolation per hit, no cross-island vertex UV extrapolation.',
               normal_mode=part.get('normal_mode','delta'),ao_transferred=transfer_ao,
               normal_method=('Source authored normal transformed between tangent frames' if part.get('normal_mode')=='source' else 'Target normal with optional source-minus-base delta'),
               caveat='Mapping coverage is diagnostic and does not establish visual correctness; inspect target model views.'))
    ctx.release()
    print('BAKED',a.part,flush=True)


if __name__=='__main__':main()
