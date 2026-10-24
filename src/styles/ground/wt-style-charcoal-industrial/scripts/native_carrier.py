"""Measure one real carrier plane and its native UV sampling before composition."""
import numpy as np

def fit_carrier(geometry,triangle_ids,texture_size,image_size,width=None,center=None,side=1,offset_uv=(0.,0.),u_hint=None):
 p=geometry['positions'];ids=np.asarray(triangle_ids,dtype=np.int64)
 if not len(ids) or ids.min()<0 or ids.max()>=len(p):raise ValueError('Carrier has no valid native triangles')
 cross=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);area=np.linalg.norm(cross,axis=1);norm=cross/np.maximum(area[:,None],1e-12);seed=ids[np.argmax(area[ids])];n=norm[seed];dist=float(p[seed].mean(0)@n)
 ids=ids[(norm[ids]@n>.998)&(np.max(abs(p[ids]@n-dist),axis=1)<.016)];pts=p[ids]
 u=np.array([float(side),0.,0.] if u_hint is None else u_hint,dtype=float)
 if u.shape!=(3,) or not np.isfinite(u).all():raise ValueError('A finite three-component surface axis is required')
 u-=n*(u@n)
 if np.linalg.norm(u)<1e-6:raise ValueError('Requested horizontal axis is perpendicular to the carrier')
 u/=np.linalg.norm(u);v=np.array([0.,-1.,0.]);v-=n*(v@n)+u*(v@u)
 if np.linalg.norm(v)<.1:v=np.cross(u,n)
 v/=np.linalg.norm(v)
 if np.dot(np.cross(u,v),n)>=0:v=-v
 org=pts.mean((0,1));local=np.stack(((pts-org)@u,(pts-org)@v),-1);lo=local.min((0,1));hi=local.max((0,1));org+=(lo[0]+hi[0])/2*u+(lo[1]+hi[1])/2*v
 iw,ih=image_size;tw,th=texture_size;width=float(width or min((hi[0]-lo[0])*.82,(hi[1]-lo[1])*.75*iw/ih));height=width*ih/iw
 if min(width,height)<=0:raise ValueError('Carrier has zero physical extent')
 if center is not None:org=np.asarray(center,dtype=float);org-=n*((org-pts[0,0])@n)
 du,dv=map(float,offset_uv)
 if width+2*abs(du)>hi[0]-lo[0]+1e-6 or height+2*abs(dv)>hi[1]-lo[1]+1e-6:raise ValueError('Offset graphic exceeds the measured carrier bounds')
 org+=du*u+dv*v
 scales=[]
 for pt,uv in zip(pts,geometry['uvs'][ids]):
  A=np.stack(((pt[1:]-pt[0])@u,(pt[1:]-pt[0])@v));B=(uv[1:]-uv[0]).T*np.array([[tw],[-th]])
  if abs(np.linalg.det(A))>1e-10:scales.append(float(np.linalg.svd(B@np.linalg.inv(A)@np.diag([width/(iw-1),height/(ih-1)]),compute_uv=False)[-1]))
 if not scales or min(scales)<=1e-8:raise ValueError('Carrier has degenerate UV sampling')
 return {'ids':ids,'normal':n,'origin':org,'u':u,'v':v,'width':width,'height':height,'min_scale':min(scales),'available_size':(hi-lo).tolist(),'offset_uv':[du,dv]}
