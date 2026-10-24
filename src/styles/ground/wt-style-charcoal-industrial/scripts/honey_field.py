"""Physical-scale SPECTRE42 regular cells derived from the AZUR production recipe.

Inputs are tangent-plane metres. This generates new flat paint, not donor C/N pixels.
"""
import math
import numpy as np

def regular_hex_field(u,v,r=.072):
 dx=math.sqrt(3)*r;dy=1.5*r;row0=np.rint(v/dy).astype('i4');best=np.full(u.shape,np.inf);xx=np.zeros_like(u);yy=np.zeros_like(v);rr=np.zeros_like(row0);cc=np.zeros_like(row0)
 for shift in [-1,0,1]:
  row=row0+shift;col=np.rint(u/dx-.5*(row%2)).astype('i4');x=u-(col+.5*(row%2))*dx;y=v-row*dy;distance=x*x+y*y;m=distance<best;best[m]=distance[m];xx[m]=x[m];yy[m]=y[m];rr[m]=row[m];cc[m]=col[m]
 inward=np.minimum(.8660254038*r-abs(xx),.8660254038*r-.5*abs(xx)-.8660254038*abs(yy))-.003
 code=(cc.astype('i8')*73856093^rr.astype('i8')*19349663^42)&0x7fffffff;palette=np.array([30,37,44,51,58,66,76,105],np.float32);val=palette[np.where(code%37==0,7,code%7)];val=np.where(inward<.008,24,val);val+=np.sin(u*491+v*297)*1.3
 return np.uint8(np.clip(val,0,255)),np.uint8(np.clip(inward/.0015+.5,0,1)*255)
