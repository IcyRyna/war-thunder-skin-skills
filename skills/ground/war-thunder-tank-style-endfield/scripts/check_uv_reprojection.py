"""GPU regression: tiled helper UVs must not overwrite the main painted panel."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skill-scripts',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    sys.path.insert(0,str(args.skill_scripts.resolve()))
    from tank_core import resize_data_image
    packed=Image.new('RGBA',(2,1))
    packed.putdata([(0,0,0,0),(200,240,100,255)])
    assert resize_data_image(packed,(1,1)).getpixel((0,0))==(100,120,50,128)
    color=Image.new('RGBA',(2,2),(220,230,240,0))
    assert resize_data_image(color,(1,1)).getpixel((0,0))==(220,230,240,0)
    script=Path(__file__).with_name('reproject_surface.py')
    with tempfile.TemporaryDirectory(prefix='endfield-uv-regression-') as temporary:
        root=Path(temporary).resolve()
        assert root.is_relative_to(Path(tempfile.gettempdir()).resolve()) and root.name.startswith('endfield-uv-regression-')
        source=root/'source';target=root/'target'
        source.mkdir();target.mkdir()
        base='''v 0 0 0
v 1 0 0
v 1 0 1
v 0 0 1
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 1 0
o main_panel
usemtl arbitrary_material_name
f 1/1/1 2/2/1 3/3/1
f 1/1/1 3/3/1 4/4/1
'''
        helper='''v 0 0.2 0
v 0.01 0.2 0
v 0.01 0.2 0.01
v 0 0.2 0.01
o tiny_helper
f 5/1/1 6/2/1 7/3/1
f 5/1/1 7/3/1 8/4/1
'''
        materials={'materials':[{'obj_name':'arbitrary_material_name','texture_slots':['synthetic_c*',None,'synthetic_n*',None]}]}
        for folder,text in [(source,base),(target,base+helper)]:
            (folder/'assembly.obj').write_text(text,encoding='utf-8')
            (folder/'materials.json').write_text(json.dumps(materials),encoding='utf-8')
        Image.new('RGBA',(16,16),(240,240,240,0)).save(root/'art.png')
        Image.new('RGBA',(16,16),(117,128,5,128)).save(root/'normal.png')
        Image.new('RGBA',(16,16),(120,120,120,255)).save(root/'stock.png')
        shader='''void applyCoating(vec3 p,vec3 N,vec4 stock,float paint,bool matched,inout vec4 color,inout vec4 pbr,inout bool recoated){
if(p.y>.15){color.rgb=vec3(.1);pbr=texture(target_n,target_tc);recoated=true;}
}'''
        (root/'coat.glsl').write_text(shader,encoding='utf-8')
        fingerprints={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for folder in [source,target] for f in folder.iterdir()}
        results={}
        for name,density in [('unrestricted',0.),('owned',.1)]:
            cfg={'runtime':{'skill_scripts':str(args.skill_scripts.resolve())},'parts':{'panel':{
                'inputs':{'source_model':'source','target_model':'target','source_c':'art.png','source_n':'normal.png',
                          'source_base_n':'normal.png','target_c':'stock.png','target_n':'normal.png','coating_shader':'coat.glsl'},
                'source_resource':'synthetic_c','target_resource':'synthetic_c','size':[64,64],
                'role':1,'radius':.10,'output':name,'minimum_uv_owner_density':density}}}
            path=root/(name+'.json');path.write_text(json.dumps(cfg),encoding='utf-8')
            cp=subprocess.run([sys.executable,'-B',str(script),'--config',str(path),'--part','panel'],capture_output=True,text=True)
            if cp.returncode:raise RuntimeError(cp.stdout+'\n'+cp.stderr)
            with Image.open(root/name/'color.png') as im:
                results[name]=im.getpixel((24,32))
            with Image.open(root/name/'normal.png') as im:
                normal=im.getpixel((24,32))
                assert normal[1]==128 and normal[3]==128,normal
        assert max(results['unrestricted'][:3])<40,results
        assert min(results['owned'][:3])>220,results
        assert results['owned'][3]==0,results
        for file,digest in fingerprints.items():assert hashlib.sha256(Path(file).read_bytes()).hexdigest()==digest
        assert not (source/'geometry.npz').exists() and not (target/'geometry.npz').exists()
        report={'status':'PASS','actual_pixel_rgba':results,'checks':['Reproduces full-panel contamination by a tiny tiled helper',
                'UV ownership filter restores the intended white main panel','Material resources resolved through materials.json, not object-name guessing',
                'Hooks with optimized-out optional uniforms and attributes work','Source models unchanged; caches stay in output',
                'Color alpha remains zero; target GA normal components remain intact','Packed RGBA resampling preserves raw bands and zero-alpha RGB']}
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
