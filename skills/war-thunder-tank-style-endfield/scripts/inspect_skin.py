"""Read-only BLK/DDS inspection for modern ground vehicle skin packages."""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path
from tank_core import load_image,write_json

def inspect(folder: Path, materials: Path | None=None):
 folder=folder.resolve();blks=list(folder.glob('*.blk'));issues=[];notes=[];rows=[];bindings=[]
 if len(blks)!=1:raise ValueError('Expected exactly one BLK in selected skin folder')
 text=blks[0].read_text(encoding='utf-8-sig')
 for kind,body in re.findall(r'(replace_tex|set_tex)\s*\{([^{}]*)\}',text,re.S):
  source=re.search(r'from:t\s*=\s*"([^"]+)"',body);target=re.search(r'to:t\s*=\s*"([^"]+)"',body)
  if source is None or target is None:issues.append('Incomplete '+kind+' mapping');continue
  resource=source.group(1);relative=Path(target.group(1));path=(folder/relative).resolve()
  if relative.is_absolute() or not path.is_relative_to(folder):issues.append('Target escapes skin folder');continue
  if not path.is_file():issues.append('Missing texture: '+str(relative));continue
  if path.suffix.lower() not in {'.dds','.tga'}:issues.append('Unsupported game texture: '+str(relative));continue
  if kind=='set_tex' and 'camo_skin_tex' not in body:issues.append('set_tex is missing camo_skin_tex: '+str(relative))
  image=load_image(path)
  role='normal' if re.search(r'_n(?:_dmg)?\*?$',resource) else ('ao' if '_ao' in resource else 'color')
  extrema=dict(zip(image.getbands(),image.getextrema()))
  with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
  rows.append({'resource':resource,'target':relative.as_posix(),'mapping':kind,'role':role,'dimensions':list(image.size),'mode':image.mode,'channel_extrema':extrema,'bytes':path.stat().st_size,'sha256':sha})
  bindings.append(resource)
  if role=='color' and kind=='replace_tex' and extrema.get('A')!=(0,0):notes.append('Review color Alpha for replace_tex: '+str(relative))
 if materials:
  data=json.loads(materials.read_text(encoding='utf-8-sig'))
  aliases={v for m in data['materials'] for v in m.get('texture_slots',[]) if v}
  issues.extend('Resource absent in model: '+r for r in bindings if r not in aliases)
 targets={r['target'] for r in rows}
 notes.extend('Unreferenced texture: '+p.name for p in folder.iterdir() if p.suffix.lower() in {'.dds','.tga'} and p.name not in targets)
 return {'folder':str(folder),'blk':blks[0].name,'texture_count':len(rows),'textures':rows,'issues':issues,'notes':notes,'passed':not issues}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path);parser.add_argument('--out',type=Path);parser.add_argument('--materials',type=Path);args=parser.parse_args()
 result=inspect(args.folder,args.materials)
 if args.out:write_json(args.out,result)
 print(json.dumps({'passed':result['passed'],'texture_count':result['texture_count'],'issues':result['issues'],'notes':result['notes']},ensure_ascii=False,indent=2))
 raise SystemExit(0 if result['passed'] else 1)
if __name__=='__main__':main()
