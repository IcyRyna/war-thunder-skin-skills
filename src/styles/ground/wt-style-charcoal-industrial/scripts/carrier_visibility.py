"""Blender BVH probe of physical exterior carriers; not a replacement for visual QA."""
from pathlib import Path
import argparse,json,sys,hashlib
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

def main():
 p=argparse.ArgumentParser();p.add_argument('--geometry',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--exclude-material',action='append',default=[]);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
 if a.out.exists():raise FileExistsError('Use a new visibility result')
 with np.load(a.geometry) as z:g={k:z[k] for k in z.files}
 pts=g['positions'];centers=pts.mean(1);cross=np.cross(pts[:,1]-pts[:,0],pts[:,2]-pts[:,0]);area=np.linalg.norm(cross,axis=1);normal=cross/np.maximum(area[:,None],1e-12)
 excluded=[i for i,n in enumerate(g['material_names']) if any(s in str(n) for s in a.exclude_material)];keep=~np.isin(g['material_ids'],excluded);indices=np.flatnonzero(keep);vertices=pts[keep].reshape(-1,3);faces=np.arange(len(vertices)).reshape(-1,3).tolist();tree=BVHTree.FromPolygons(vertices.tolist(),faces,all_triangles=True)
 visible=np.zeros(len(pts),np.uint8)
 for i in indices:
  if area[i]<1e-7:continue
  n=Vector(normal[i]);hit=0
  for point in [centers[i],pts[i,0]*.2+centers[i]*.8,pts[i,1]*.2+centers[i]*.8]:
   location,_,_,_=tree.ray_cast(Vector(point)+n*20,-n,20.01)
   if location is not None and (location-Vector(point)).length<.008:hit+=1
  visible[i]=hit
 uv=g['uvs'];det=(uv[:,1,0]-uv[:,0,0])*(uv[:,2,1]-uv[:,0,1])-(uv[:,1,1]-uv[:,0,1])*(uv[:,2,0]-uv[:,0,0]);valid=np.abs(det)>1e-8
 a.out.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(a.out,visible_samples=visible,valid_uv=valid,face_area_twice=area,normal=normal)
 with a.geometry.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 a.out.with_suffix('.json').write_text(json.dumps({'geometry_sha256':digest,'triangles':len(pts),'visible_two_or_three_samples':int((visible>=2).sum()),'degenerate_uv':int((~valid).sum()),'excluded_material_names':[str(g['material_names'][i]) for i in excluded],'method':'three outward-normal ray probes per triangle; 8mm hit agreement; conservative geometry-only visibility, still check actual model/material/UV','game':'not a game renderer'},indent=2),encoding='utf-8');print('CARRIER_VISIBILITY_PROBED',int((visible>=2).sum()),flush=True)
if __name__=='__main__':main()
