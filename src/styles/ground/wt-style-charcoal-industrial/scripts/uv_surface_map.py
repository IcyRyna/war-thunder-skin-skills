"""Native UV-to-surface evidence, with explicit top-left image convention."""
import numpy as np
from numba import njit

@njit(cache=False)
def rasterize(positions,uv,nodes,height,width):
    xyz=np.zeros((height,width,3),np.float32);normal=np.zeros_like(xyz)
    node=np.full((height,width),-1,np.int32);triangle=np.full((height,width),-1,np.int32);shared=np.zeros((height,width),np.uint8)
    for t in range(len(positions)):
        q=uv[t];umin=int(np.floor(q[:,0].min()));umax=int(np.floor(q[:,0].max()));vmin=int(np.floor(q[:,1].min()));vmax=int(np.floor(q[:,1].max()))
        if umax-umin>2 or vmax-vmin>2:continue
        n=np.cross(positions[t,1]-positions[t,0],positions[t,2]-positions[t,0]);length=np.sqrt(np.sum(n*n))
        if length<1e-12:continue
        n/=length
        for tileu in range(umin,umax+1):
            for tilev in range(vmin,vmax+1):
                px=(q[:,0]-tileu)*width-.5;py=(1-(q[:,1]-tilev))*height-.5
                x0=max(0,int(np.ceil(px.min())));x1=min(width-1,int(np.floor(px.max())));y0=max(0,int(np.ceil(py.min())));y1=min(height-1,int(np.floor(py.max())))
                den=(py[1]-py[2])*(px[0]-px[2])+(px[2]-px[1])*(py[0]-py[2])
                if abs(den)<1e-9:continue
                for y in range(y0,y1+1):
                    for x in range(x0,x1+1):
                        a=((py[1]-py[2])*(x-px[2])+(px[2]-px[1])*(y-py[2]))/den;b=((py[2]-py[0])*(x-px[2])+(px[0]-px[2])*(y-py[2]))/den;c=1-a-b
                        if min(a,b,c)<-1e-5:continue
                        p=positions[t,0]*a+positions[t,1]*b+positions[t,2]*c
                        if node[y,x]>=0 and (np.sum((xyz[y,x]-p)**2)>.0001 or np.sum(normal[y,x]*n)<.996):shared[y,x]=255
                        xyz[y,x]=p;normal[y,x]=n;node[y,x]=nodes[t];triangle[y,x]=t
    return xyz,normal,node,triangle,shared

def build_surface_map(geometry,material_ids,size):
    height,width=map(int,size)
    if not 1<=height<=8192 or not 1<=width<=8192:raise ValueError('Invalid target dimensions')
    selected=np.flatnonzero(np.isin(geometry['material_ids'],material_ids))
    if not len(selected):raise ValueError('No native triangles bind the requested material')
    p=np.asarray(geometry['positions'][selected],dtype=np.float32);uv=np.asarray(geometry['uvs'][selected],dtype=np.float32)
    if not np.isfinite(p).all() or not np.isfinite(uv).all():raise ValueError('Nonfinite native geometry')
    xyz,nor,nid,tri,shared=rasterize(p,uv,geometry['node_ids'][selected],height,width)
    valid=tri>=0;tri[valid]=selected[tri[valid]]
    return {'xyz':xyz,'nor':nor,'nid':nid,'triangle':tri,'shared':shared}
