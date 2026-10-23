"""Offline UV/material preview for static ground vehicle OBJ assemblies."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import moderngl
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from artifact_io import ArtifactTransaction
from tank_core import load_image,load_obj,unit,write_json
from texture_semantics import binding_alpha_semantics,resize_for_preview,iter_mipmaps,validate_color_space

CAMERAS={'iso':[1.4,.95,1.5],'iso_right':[1.4,.95,-1.5],'opposite':[-1.3,.8,-1.4],'top':[0,1,0],'left':[0,.1,1],'right':[0,.1,-1],'rear':[-1,.12,0],'front':[1,.12,0]}

VS = """#version 330
in vec3 p; in vec3 n; in vec2 uv;
uniform mat4 mvp; uniform mat4 light_mvp;
out vec3 pos; out vec3 normal; out vec2 tc; out vec4 shadow_pos;
void main(){ pos=p;normal=n;tc=uv;shadow_pos=light_mvp*vec4(p,1);gl_Position=mvp*vec4(p,1);}
"""
FS = """#version 330
in vec3 pos; in vec3 normal; in vec2 tc; in vec4 shadow_pos;
out vec4 frag;
uniform sampler2D color_tex; uniform sampler2D packed_tex; uniform sampler2D ao_tex;
uniform sampler2DShadow shadow_tex;
uniform vec3 eye; uniform vec3 key_light; uniform int flip_v;uniform int cutout;uniform int is_floor;uniform int color_linear;
uniform float bump_strength;uniform float exposure;
const float PI=3.14159265359;
vec3 film(vec3 c){return clamp((c*(2.51*c+.03))/(c*(2.43*c+.59)+.14),0.,1.);}
float shadow(){
 vec3 s=shadow_pos.xyz/shadow_pos.w*.5+.5;
 if(any(lessThan(s,vec3(0)))||any(greaterThan(s,vec3(1))))return 1.;
 float v=0.;vec2 texel=1./vec2(textureSize(shadow_tex,0));
 for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++)v+=texture(shadow_tex,vec3(s.xy+vec2(x,y)*texel,s.z-.0012));
 return .25+.75*v/9.;
}
void main(){
 vec2 t=vec2(tc.x,flip_v==1?1.-tc.y:tc.y);
 vec4 c=texture(color_tex,t);
 if(cutout==1 && c.a<.45)discard;
 vec4 packed_value=texture(packed_tex,t);
 vec3 N=normalize(normal); if(!gl_FrontFacing)N=-N;
 vec3 dp1=dFdx(pos),dp2=dFdy(pos);vec2 duv1=dFdx(t),duv2=dFdy(t);
 float det=duv1.x*duv2.y-duv1.y*duv2.x;
 if(abs(det)>1e-10){
  vec3 T=(dp1*duv2.y-dp2*duv1.y)/det;
  vec3 Braw=(dp2*duv1.x-dp1*duv2.x)/det;
  T=normalize(T-N*dot(N,T));vec3 B=normalize(cross(N,T))*(dot(cross(N,T),Braw)<0.?-1.:1.);
  vec2 xy=(packed_value.ga*2.-1.)*bump_strength;
  xy*=min(1.,.98/max(length(xy),.001));
  N=normalize(mat3(T,B,N)*vec3(xy,sqrt(max(.01,1.-dot(xy,xy)))));
 }
 if(is_floor==1){frag=vec4(vec3(.695)*shadow(),1);return;}
 vec3 encoded=max(c.rgb,vec3(0));
 vec3 base=color_linear==1?encoded:mix(encoded/12.92,pow((encoded+.055)/1.055,vec3(2.4)),step(vec3(.04045),encoded));
 float rough=clamp(1.-packed_value.r,.2,.96),metal=clamp(packed_value.b,0.,1.);
 float ao=texture(ao_tex,t).r;
 vec3 V=normalize(eye-pos),L=normalize(key_light),H=normalize(V+L);
 float nl=max(dot(N,L),0.),nv=max(dot(N,V),.001),nh=max(dot(N,H),0.),vh=max(dot(V,H),0.);
 float a=rough*rough,a2=a*a;
 float D=a2/(PI*pow(nh*nh*(a2-1.)+1.,2.)+.00001);
 float k=pow(rough+1.,2.)/8.;
 float G=(nv/(nv*(1.-k)+k))*(nl/(nl*(1.-k)+k));
 vec3 F0=mix(vec3(.04),base,metal),F=F0+(1.-F0)*pow(1.-vh,5.);
 vec3 spec=D*G*F/max(4.*nv*nl,.001);
 vec3 diffuse=(1.-F)*(1.-metal)*base/PI;
 float sky=clamp(N.y*.5+.5,0.,1.);
 vec3 ambient=base*(.16+.24*sky)*(1.-metal*.35)*(.42+.58*ao);
 vec3 reflection=mix(vec3(.06,.065,.07),vec3(.5,.52,.54),sky)*F0*(.2+.35*(1.-rough))*(.6+.4*ao);
 vec3 lighting=ambient+reflection+(diffuse+spec)*nl*3.0*shadow();
 vec3 fill=normalize(vec3(-.7,.3,-.4));
 lighting+=base*max(dot(N,fill),0.)*.1*(1.-metal);
 frag=vec4(pow(film(lighting*exposure),vec3(1./2.2)),1);
}
"""
DEPTH_VS="#version 330\nin vec3 p;in vec2 uv;uniform mat4 mvp;out vec2 tc;void main(){tc=uv;gl_Position=mvp*vec4(p,1);}"
DEPTH_FS="#version 330\nin vec2 tc;uniform sampler2D color_tex;uniform int cutout;uniform int flip_v;void main(){vec2 t=vec2(tc.x,flip_v==1?1.-tc.y:tc.y);if(cutout==1 && texture(color_tex,t).a<.45)discard;}"

def look_at(eye,target,up):
    f=unit(np.asarray(target)-eye);s=unit(np.cross(f,up));u=np.cross(s,f)
    m=np.eye(4,dtype='f4');m[0,:3]=s;m[1,:3]=u;m[2,:3]=-f;m[:3,3]=-m[:3,:3]@eye
    return m

def ortho(l,r,b,t,near,far):
    m=np.eye(4,dtype='f4');m[0,0]=2/(r-l);m[1,1]=2/(t-b);m[2,2]=-2/(far-near)
    m[0,3]=-(r+l)/(r-l);m[1,3]=-(t+b)/(t-b);m[2,3]=-(far+near)/(far-near)
    return m

def frame(positions,eye_dir,size,margin=1.13,target=None):
    lo=positions.min((0,1));hi=positions.max((0,1))
    center=(lo+hi)/2 if target is None else np.asarray(target)
    eye=center+unit(eye_dir)*25
    up=np.asarray([0,1,0],dtype='f4') if abs(unit(eye_dir)[1])<.99 else np.asarray([-1,0,0],dtype='f4')
    view=look_at(eye,center,up)
    verts=positions.reshape(-1,3)
    pts=verts@view[:3,:3].T+view[:3,3]
    mn=pts.min(0);mx=pts.max(0)
    width,height=mx[0]-mn[0],mx[1]-mn[1]
    aspect=size[0]/size[1];height=max(height,width/aspect)*margin;width=height*aspect
    cx,cy=(mn[0]+mx[0])/2,(mn[1]+mx[1])/2
    return ortho(cx-width/2,cx+width/2,cy-height/2,cy+height/2,.05,80)@view,eye

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--profile',type=Path,help='Optional profile declaring texture_alpha_semantics by role')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--width',type=int,default=1800)
    parser.add_argument('--height',type=int,default=1150)
    parser.add_argument('--bounds',type=float,nargs=6)
    parser.add_argument('--views',nargs='+',default=['iso','opposite','top','left','right','rear','front'])
    args=parser.parse_args()
    if not 128<=args.width<=8192 or not 128<=args.height<=8192:raise ValueError('Preview dimensions out of range')
    if len(set(args.views))!=len(args.views) or any(view not in CAMERAS for view in args.views):raise ValueError('Views must be unique and chosen from '+', '.join(CAMERAS))
    if args.out.exists():raise FileExistsError('Preview output directory already exists; choose a fresh output directory')
    outputs=[args.out/'geometry.npz',args.out/'preview-report.json']+[args.out/(view+'.png') for view in args.views]
    inputs=[args.model,args.config]+([args.profile] if args.profile else [])
    with ArtifactTransaction(outputs,inputs,label='ground-preview') as transaction:
        ctx=moderngl.create_standalone_context(require=330)
        try:
            render(args,transaction,ctx)
            transaction.commit()
        finally:
            ctx.release()

def render(args,transaction,ctx):
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    profile=json.loads(args.profile.read_text(encoding='utf-8-sig')) if args.profile else config
    model=load_obj(args.model/'assembly.obj')
    np.savez(transaction.stage(args.out/'geometry.npz'),**model)
    mats=json.loads((args.model/'materials.json').read_text(encoding='utf-8'))['materials']
    bindings=config.get('textures',{})
    material_bindings=config.get('material_bindings',{})
    if args.bounds:config['framing_bounds']=[args.bounds[:3],args.bounds[3:]]
    for binding in list(bindings.values())+list(material_bindings.values()):
        if isinstance(binding,dict):
            for key in ['color','normal','ao']:
                if binding.get(key) and not Path(binding[key]).is_absolute():binding[key]=str((args.config.resolve().parent/binding[key]).resolve())
    lookup={m['obj_name']:m for m in mats}
    prog=ctx.program(vertex_shader=VS,fragment_shader=FS)
    depth_prog=ctx.program(vertex_shader=DEPTH_VS,fragment_shader=DEPTH_FS)
    texture_cache={};texture_filtering=[]
    def texture(path,default,semantics=None,color_space=None):
        if semantics is not None:color_space=validate_color_space(color_space,semantics)
        key=(str(path) if path else str(default),semantics,color_space)
        if key not in texture_cache:
            if path:
                img=load_image(path)
                source_size=img.size
                img=resize_for_preview(img,semantics,color_space=color_space)
                texture_filtering.append({'path':str(path),'source_size':list(source_size),'preview_size':list(img.size),'alpha_semantics':semantics,'color_space':color_space,'resized':source_size!=img.size,'mip_policy':'explicit semantic BOX to 1x1' if semantics else 'legacy OpenGL generated mips; semantics undeclared'})
            else:img=Image.new('RGBA',(2,2),default)
            tex=ctx.texture(img.size,4,img.tobytes(),alignment=1)
            tex.build_mipmaps();tex.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
            if semantics is not None:
                # Override GL-generated children: sRGB needs linear-light mips;
                # coverage needs premultiplied colour; data stays independent.
                for level,mip in enumerate(iter_mipmaps(img,semantics,color_space)):
                    if level:tex.write(mip.tobytes(),level=level,alignment=1)
            tex.anisotropy=min(8.,ctx.max_anisotropy)
            texture_cache[key]=tex
        return texture_cache[key]
    batches=[];missing=[]
    for i,name in enumerate(model['material_names']):
        select=model['material_ids']==i
        if not select.any():continue
        material=lookup.get(str(name),{})
        slots=material.get('texture_slots',[])
        resource=(slots[0] or '').rstrip('*') if slots else ''
        binding=material_bindings.get(str(name),bindings.get(resource,{}))
        if isinstance(binding,str):binding={'color':binding}
        semantics=binding_alpha_semantics(binding,profile)
        color_spaces=binding.get('color_space',{})
        if not isinstance(color_spaces,dict):raise ValueError('Binding color_space must be a role mapping')
        for role,color_space in color_spaces.items():
            if role not in ('color','normal','ao'):raise ValueError('Unknown texture role in color_space: '+role)
            if role not in semantics:raise ValueError('A colour space declaration requires alpha_semantics for '+role)
            validate_color_space(color_space,semantics[role])
        if binding.get('alpha_test') and semantics.get('color') not in (None,'opacity'):
            raise ValueError('alpha_test requires opacity colour semantics; fixed replacement alpha is independent data')
        is_glass='glass' in str(name)
        default=(28,38,41,255) if is_glass else ((32,32,31,255) if 'track' in str(name) else (43,43,43,255))
        if not binding.get('color'):missing.append({'material':str(name),'albedo_resource':resource})
        c=texture(binding.get('color'),default,semantics.get('color'),color_spaces.get('color'))
        n=texture(binding.get('normal'),(130,128,30,128),semantics.get('normal'),color_spaces.get('normal'))
        ao=texture(binding.get('ao'),(255,255,255,255),semantics.get('ao'),color_spaces.get('ao'))
        packed_value=np.concatenate([model['positions'][select],model['normals'][select],model['uvs'][select]],axis=2).reshape(-1,8).astype('f4')
        vb=ctx.buffer(packed_value.tobytes())
        vao=ctx.vertex_array(prog,[(vb,'3f 3f 2f','p','n','uv')])
        db=ctx.buffer(np.concatenate([model['positions'][select],model['uvs'][select]],axis=2).astype('f4').tobytes())
        dvao=ctx.vertex_array(depth_prog,[(db,'3f 2f','p','uv')])
        color_space=validate_color_space(color_spaces.get('color'),semantics['color']) if 'color' in semantics else 'srgb'
        batches.append((vao,dvao,c,n,ao,int(binding.get('alpha_test',False)),int(color_space=='linear')))
    positions=model['positions'];lo=positions.min((0,1));hi=positions.max((0,1))
    floor_y=float(lo[1]-.025)
    floor=np.asarray([[[-15,floor_y,-15],[15,floor_y,-15],[15,floor_y,15]],[[-15,floor_y,-15],[15,floor_y,15],[-15,floor_y,15]]],dtype='f4')
    floor=floor[:,[0,2,1],:]
    floor_n=np.broadcast_to([0.,1.,0.],floor.shape).astype('f4')
    floor_uv=np.zeros((2,3,2),dtype='f4')
    floor_vb=ctx.buffer(np.concatenate([floor,floor_n,floor_uv],axis=2).tobytes())
    floor_vao=ctx.vertex_array(prog,[(floor_vb,'3f 3f 2f','p','n','uv')])
    fc=texture(None,(142,143,140,255));fn=texture(None,(80,128,0,128));fa=texture(None,(255,255,255,255))
    light_dir=unit([.65,1.4,.8]);light_mvp,_=frame(positions,light_dir,(3072,3072),1.15)
    depth_tex=ctx.depth_texture((3072,3072));depth_tex.compare_func='<=';depth_tex.repeat_x=False;depth_tex.repeat_y=False
    shadow=ctx.framebuffer(depth_attachment=depth_tex);shadow.use();shadow.clear(depth=1.0)
    ctx.enable(moderngl.DEPTH_TEST);ctx.disable(moderngl.CULL_FACE)
    depth_prog['mvp'].write(light_mvp.T.tobytes())
    depth_prog['color_tex'].value=0;depth_prog['flip_v'].value=int(config.get('flip_v',False))
    for _,vao,c,_,_,cutout,_ in batches:
        c.use(0);depth_prog['cutout'].value=cutout;vao.render()
    size=(args.width,args.height)
    target=ctx.framebuffer([ctx.renderbuffer(size,4,samples=4)],ctx.depth_renderbuffer(size,samples=4))
    resolved=ctx.simple_framebuffer(size,components=4)
    prog['light_mvp'].write(light_mvp.T.tobytes());prog['key_light'].value=tuple(light_dir)
    prog['color_tex'].value=0;prog['packed_tex'].value=1;prog['ao_tex'].value=2;prog['shadow_tex'].value=3
    prog['flip_v'].value=int(config.get('flip_v',False));prog['bump_strength'].value=float(config.get('bump_strength',.4));prog['exposure'].value=float(config.get('exposure',1.1))
    for name in args.views:
        direction=CAMERAS[name]
        frame_positions=positions
        if config.get('framing_bounds'):
            lo_f,hi_f=np.asarray(config['framing_bounds'])
            frame_positions=np.asarray([[lo_f[0] if i&1==0 else hi_f[0],lo_f[1] if i&2==0 else hi_f[1],lo_f[2] if i&4==0 else hi_f[2]] for i in range(8)],dtype='f4')[None,:,:]
        mvp,eye=frame(frame_positions,direction,size)
        target.use();target.clear(.695,.695,.695,1,depth=1)
        prog['mvp'].write(mvp.T.tobytes());prog['eye'].value=tuple(eye)
        depth_tex.use(3)
        fc.use(0);fn.use(1);fa.use(2);prog['cutout'].value=0;prog['color_linear'].value=0;prog['is_floor'].value=1;floor_vao.render();prog['is_floor'].value=0
        for vao,_,c,n,ao,cutout,color_linear in batches:
            c.use(0);n.use(1);ao.use(2);prog['cutout'].value=cutout;prog['color_linear'].value=color_linear;vao.render()
        ctx.copy_framebuffer(resolved,target)
        img=Image.frombytes('RGB',size,resolved.read(components=3,alignment=1)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        img.save(transaction.stage(args.out/(name+'.png')))
        print('rendered',name,flush=True)
    write_json(transaction.stage(args.out/'preview-report.json'),{'renderer':'Independent OpenGL preview; approximate lighting, not the game engine','gpu':ctx.info.get('GL_RENDERER'),'texture_bindings':bindings,'material_bindings':material_bindings,'texture_filtering':texture_filtering,'profile_alpha_semantics':profile.get('texture_alpha_semantics',{}),'missing_stock_preview_materials':missing,'bounds':[lo.tolist(),hi.tolist()],'views':args.views})
if __name__=='__main__':main()
