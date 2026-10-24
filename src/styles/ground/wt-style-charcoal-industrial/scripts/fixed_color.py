"""Explicit fixed-paint coverage and BLK binding, separate from decal opacity."""
from pathlib import Path
import argparse,json,struct,re
import numpy as np
from PIL import Image
from ground_dds import rewrite_blk,semantic_mips,decode_mips

def opaque_resource(materials,resource):
 resource=resource.rstrip('*');matches=[]
 for row in materials['materials']:
  slots=row.get('texture_slots',[])
  if slots and slots[0] and slots[0].rstrip('*')==resource:matches.append(row)
 if not matches:raise ValueError('Color resource not present in native material slots: '+resource)
 for row in matches:
  shader=row.get('shader','').lower();test=re.search(r'\batest\s*=\s*([0-9.]+)',row.get('parameters',''))
  if any(k in shader for k in ['atest','alpha_test','cutout']) or (test and float(test.group(1))>0):raise ValueError('Alpha-tested surface: fixed opaque coverage is forbidden')
  if shader not in {'dynamic_masked_tank'}:raise ValueError('Opaque fixed-paint coverage is not verified for this shader: '+shader)
 return [r['obj_name'] for r in matches]

def prepare(image,materials,resource):
 opaque_resource(materials,resource);a=np.asarray(image.convert('RGBA')).copy();before=a[:,:,:3].copy();a[:,:,3]=255
 if not np.array_equal(a[:,:,:3],before):raise ValueError('Fixed coverage changed RGB')
 return Image.fromarray(a)

def legacy_mips(raw):
 if raw[:4]!=b'DDS ' or len(raw)<128:raise ValueError('Expected complete legacy BGRA8 DDS')
 h=struct.unpack_from('<31I',raw,4)
 if h[0]!=124 or h[18:26]!=(32,0x41,0,32,0xff0000,0xff00,0xff,0xff000000):raise ValueError('Not legacy BGRA8; do not reinterpret packed/compressed channels')
 height,width,count=h[2],h[3],h[6];offset=128;levels=[]
 if min(width,height,count)<1 or max(width,height)>16384 or count>32:raise ValueError('Invalid DDS dimensions or mip count')
 expected=1+int(np.floor(np.log2(max(width,height))))
 if count!=expected:raise ValueError('Incomplete or repeated mip chain')
 for _ in range(count):
  size=height*width*4
  if offset+size>len(raw):raise ValueError('Truncated DDS')
  levels.append(np.frombuffer(raw,dtype='uint8',count=size,offset=offset).reshape(height,width,4));offset+=size;height=max(1,height//2);width=max(1,width//2)
 if offset!=len(raw) or levels[-1].shape[:2]!=(1,1):raise ValueError('DDS trailing bytes or missing 1x1 tail')
 return levels

def write_rgba8(path,levels):
 if not levels:raise ValueError('No semantic mip levels')
 h,w=levels[0].shape[:2];count=1+int(np.floor(np.log2(max(h,w))));dims=[(max(1,h>>i),max(1,w>>i)) for i in range(count)]
 if len(levels)!=len(dims) or any(a.dtype!=np.uint8 or a.shape!=(height,width,4) for a,(height,width) in zip(levels,dims)):raise ValueError('Invalid complete mip chain')
 header=[0]*31;header[:7]=[124,0x2100f,h,w,w*4,0,len(levels)];header[18:26]=[32,0x41,0,32,0xff0000,0xff00,0xff,0xff000000];header[26]=0x401008
 with Path(path).open('xb') as f:
  f.write(b'DDS '+struct.pack('<31I',*header))
  for a in levels:f.write(a[:,:,[2,1,0,3]].tobytes())
 actual=legacy_mips(bytearray(Path(path).read_bytes()))
 if any(not np.array_equal(a[:,:,[2,1,0,3]],b) for a,b in zip(actual,levels)):raise ValueError('Mip readback changed RGBA')
 if not np.array_equal(np.asarray(Image.open(path).convert('RGBA')),levels[0]):raise ValueError('Independent top-mip decoder mismatch')

def bind(text,contract,materials):
 table={};opaque=set()
 for row in contract['bindings']:
  p=Path(row['file'])
  if p.is_absolute() or '..' in p.parts or p.suffix.lower()!='.dds':raise ValueError('Bindings require relative DDS filenames')
  if row['file'].casefold() in table:raise ValueError('Duplicate DDS target')
  table[row['file'].casefold()]={'file':p,'output':p,'role':row['role']}
  if row.get('coverage')=='opaque_fixed':
   if row['role']!='color':raise ValueError('Opaque coverage applies to colors only')
   opaque_resource(materials,row['resource']);opaque.add(row['resource'].rstrip('*').casefold())
 _,rows=rewrite_blk(text,table);lines=['name:t="user"']
 actual={r['resource'].rstrip('*').casefold() for r in rows}
 if not opaque<=actual:raise ValueError('Opaque color resource absent from BLK')
 for row in rows:
  if row['kind']=='set_tex' and row['role']!='color':raise ValueError('camo_skin_tex is not a packed N/AO binding')
  kind='set_tex' if row['resource'].rstrip('*').casefold() in opaque else row['kind']
  block=[kind+'{','  from:t='+json.dumps(row['resource']),'  to:t='+json.dumps(row['target'])]
  if kind=='set_tex':block.append('  param:t="camo_skin_tex"')
  lines.append('\n'.join(block+['}']))
 return '\n\n'.join(lines)+'\n'

def check(folder,blk,contract,materials):
 text=Path(blk).read_text(encoding='utf-8');expected=bind(text,contract,materials)
 table={r['file'].casefold():{'file':Path(r['file']),'output':Path(r['file']),'role':r['role']} for r in contract['bindings']};canonical,_=rewrite_blk(text,table)
 if canonical!=expected:raise ValueError('Fixed paint must use set_tex / camo_skin_tex')
 rows=[]
 for r in contract['bindings']:
  path=Path(folder)/r['file']
  if not path.is_file():raise ValueError('Missing bound texture: '+r['file'])
  if r.get('coverage')=='opaque_fixed':
   raw=bytearray(path.read_bytes())
   if raw[84:88]==b'DX10':_,mips=decode_mips(path)
   else:mips=legacy_mips(raw)
   if any(np.any(a[:,:,3]!=255) for a in mips):raise ValueError('Incomplete fixed paint coverage at a mip: '+r['resource'])
   rows.append({'resource':r['resource'],'mips':len(mips),'alpha':255})
 return {'fixed_color_resources':rows,'game_visual':'separate check required'}

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 q=sub.add_parser('prepare');q.add_argument('--input',type=Path,required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--materials',type=Path,required=True);q.add_argument('--resource',required=True)
 q=sub.add_parser('bind');q.add_argument('--input',type=Path,required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--materials',type=Path,required=True);q.add_argument('--contract',type=Path,required=True)
 q=sub.add_parser('check');q.add_argument('--skin',type=Path,required=True);q.add_argument('--blk',type=Path,required=True);q.add_argument('--materials',type=Path,required=True);q.add_argument('--contract',type=Path,required=True)
 q=sub.add_parser('export');q.add_argument('--input',type=Path,required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--semantics',choices=['fixed_rgb','opacity','packed_data','scalar_data'],required=True);q.add_argument('--space',choices=['srgb','linear'],required=True)
 a=p.parse_args()
 if getattr(a,'output',None) and a.output.exists():raise FileExistsError('Choose a new output file')
 if a.command=='export':write_rgba8(a.output,semantic_mips(Image.open(a.input),a.semantics,a.space));return
 materials=json.loads(a.materials.read_bytes())
 if a.command=='prepare':prepare(Image.open(a.input),materials,a.resource).save(a.output);return
 contract=json.loads(a.contract.read_bytes())
 if a.command=='bind':a.output.write_text(bind(a.input.read_text(encoding='utf-8'),contract,materials),encoding='utf-8');return
 print(json.dumps(check(a.skin,a.blk,contract,materials),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
