"""Build a fresh transparent SVG/PNG master from measured geometric declarations."""
from pathlib import Path
import argparse,hashlib,json,math
import numpy as np
from PIL import Image,ImageColor,ImageDraw

def color(value):
 if not isinstance(value,str) or len(value)!=7 or not value.startswith('#'):raise ValueError('Use explicit #RRGGBB paint colors')
 return ImageColor.getrgb(value)

def stroke_polygon(points,width):
 p=np.asarray(points,dtype='f8')
 if p.ndim!=2 or p.shape[0]<2 or p.shape[1]!=2 or not np.isfinite(p).all() or not math.isfinite(width) or width<=0:raise ValueError('Invalid measured stroke')
 d=np.diff(p,axis=0);length=np.linalg.norm(d,axis=1)
 if np.any(length<1e-8):raise ValueError('Repeated stroke point')
 n=np.stack((-d[:,1],d[:,0]),axis=1)/length[:,None];offsets=[]
 for i in range(len(p)):
  if i==0:o=n[0]
  elif i==len(p)-1:o=n[-1]
  else:
   denominator=1+np.dot(n[i-1],n[i])
   if denominator<.05:raise ValueError('Stroke reverses direction; split into separate paths')
   o=(n[i-1]+n[i])/denominator
  offsets.append(o*width/2)
 return np.concatenate((p+offsets,(p-offsets)[::-1]))

def build(spec,out):
 size=spec['canvas']
 if not isinstance(size,list) or len(size)!=2 or any(type(v)!=int or not 1<=v<=8192 for v in size):raise ValueError('Canvas needs two positive pixel dimensions up to 8192')
 w,h=size;scale=spec.get('supersample',4)
 if scale not in [1,2,4] or w*h*scale*scale>134217728:raise ValueError('Supersampling exceeds the bounded raster budget')
 out=Path(out);out.mkdir(parents=True,exist_ok=False);im=Image.new('RGBA',(w*scale,h*scale));draw=ImageDraw.Draw(im);polygons=[];svg=[f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'];centers=[];vertices=None
 cells=spec.get('hex_cells',[])
 if cells:
  r=float(spec['hex_radius']);gap=float(spec['hex_gap']);origin=np.asarray(spec['hex_origin'],dtype='f8')
  if not math.isfinite(r) or r<=0 or not math.isfinite(gap) or gap<=0 or origin.shape!=(2,) or not np.isfinite(origin).all():raise ValueError('Invalid hex radius/gap/origin')
  vertices=np.array([[r*math.cos(i*math.pi/3),r*math.sin(i*math.pi/3)] for i in range(6)])
  svg.append('<defs><polygon id="regular-hex" points="'+' '.join(f'{x:.9f},{y:.9f}' for x,y in vertices)+'"/></defs>');seen=set()
  for cell in cells:
   col,row=cell['col'],cell['row'];fill=cell['fill'];color(fill)
   if type(col)!=int or type(row)!=int or (col,row) in seen:raise ValueError('Hex grid cells must have unique integer coordinates')
   seen.add((col,row));c=origin+[col*(1.5*r+math.sqrt(3)*gap/2),(row+.5*(col%2))*(math.sqrt(3)*r+gap)];centers.append(c.tolist());p=vertices+c;polygons.append((p,fill,False));svg.append(f'<use xlink:href="#regular-hex" transform="translate({c[0]:.9f},{c[1]:.9f})" fill="{fill}"/>')
 for row in spec.get('polygons',[]):polygons.append((np.asarray(row['points'],dtype='f8'),row['fill'],True))
 widths=[]
 for row in spec.get('strokes',[]):
  width=float(row['width']);widths.append(width);polygons.append((stroke_polygon(row['points'],width),row['color'],True))
 if not polygons:raise ValueError('No paint shapes declared')
 for p,fill,emit in polygons:
  color(fill)
  if p.ndim!=2 or p.shape[0]<3 or p.shape[1]!=2 or not np.isfinite(p).all():raise ValueError('Invalid polygon')
  if (p[:,0]<0).any() or (p[:,0]>w).any() or (p[:,1]<0).any() or (p[:,1]>h).any():raise ValueError('Graphic would clip at canvas boundary')
  draw.polygon([(round(float(x)*scale),round(float(y)*scale)) for x,y in p],fill=fill)
  if emit:svg.append('<polygon fill="'+fill+'" points="'+' '.join(f'{x:.9f},{y:.9f}' for x,y in p)+'"/>')
 svg.append('</svg>');(out/'master.svg').write_text('\n'.join(svg)+'\n',encoding='utf-8');rgba=np.asarray(im.resize((w,h),Image.Resampling.LANCZOS)).copy();rgba[rgba[:,:,3]==0,:3]=0;Image.fromarray(rgba).save(out/'master.png')
 def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
 report={'schema_version':1,'method':'new geometry-constrained master; raster source pixels are not reconstructed','canvas':size,'hex_count':len(cells),'hex_centers':centers,'hex_radius':float(spec['hex_radius']) if cells else None,'normal_gap':float(spec['hex_gap']) if cells else None,'edge_lengths':np.linalg.norm(vertices-np.roll(vertices,1,axis=0),axis=1).tolist() if cells else [],'internal_angles_deg':[120]*6 if cells else [],'minimum_stroke_width_px':min(widths) if widths else None,'transparent_pixels':int((rgba[:,:,3]==0).sum()),'opaque_pixels':int((rgba[:,:,3]==255).sum()),'svg_sha256':sha(out/'master.svg'),'png_sha256':sha(out/'master.png'),'visual_review':'separate from this geometry check'}
 (out/'geometry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(build(json.loads(a.spec.read_bytes()),a.out),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
