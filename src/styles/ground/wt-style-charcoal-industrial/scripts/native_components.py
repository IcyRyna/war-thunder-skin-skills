"""Identify complete native mesh parts before applying fine edge materials."""
import numpy as np
from numba import njit
@njit(cache=False)
def _roots(v):
 parent=np.arange(v.max()+1)
 for t in v:
  a=t[0]
  while parent[a]!=a:a=parent[a]
  for b in t[1:]:
   while parent[b]!=b:b=parent[b]
   parent[b]=a
 roots=np.empty(len(v),np.int64)
 for i in range(len(v)):
  a=v[i,0]
  while parent[a]!=a:a=parent[a]
  roots[i]=a
 return roots

def face_components(positions,tolerance=.0001):
 p=np.asarray(positions)
 if p.ndim!=3 or p.shape[1:]!=(3,3) or not len(p) or not np.isfinite(p).all() or not 0<tolerance<=.01:raise ValueError('Finite native triangles and a declared welding tolerance are required')
 _,inverse=np.unique(np.rint(p.reshape(-1,3)/tolerance).astype(np.int64),axis=0,return_inverse=True)
 return _roots(inverse.reshape(-1,3))

def expand_reviewed_components(components,seed_faces,allowed_components,protected_faces=()):
 c=np.asarray(components);seed=np.asarray(seed_faces,dtype=np.int64);protected=np.asarray(protected_faces,dtype=np.int64)
 if c.ndim!=1 or not len(c) or np.any(seed<0) or np.any(seed>=len(c)) or np.any(protected<0) or np.any(protected>=len(c)):raise ValueError('Invalid native component indices')
 allowed=set(allowed_components)-set(c[protected]);chosen=set(seed)-set(np.flatnonzero(np.isin(c,c[protected])))
 for component in set(c[seed])&allowed:chosen.update(np.flatnonzero(c==component).tolist())
 return np.asarray(sorted(chosen),dtype=np.int64)
