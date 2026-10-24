"""Apply ordered subtle material regions while preserving tangent-normal data."""
import numpy as np
def apply_region(normal,mask,metalness,roughness_shift=0,roughness_level=None):
 a=np.asarray(normal);m=np.asarray(mask,bool)
 if a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=4 or m.shape!=a.shape[:2] or not m.any():raise ValueError('Packed RGBA and a nonempty explicit mask are required')
 if not 0<=metalness<=255 or not -255<=roughness_shift<=255 or (roughness_level is not None and not 0<=roughness_level<=255):raise ValueError('Invalid packed material values')
 b=a.copy();b[m,2]=metalness;b[m,0]=np.uint8(np.clip(a[m,0].astype(np.int16)+roughness_shift,0,255)) if roughness_level is None else roughness_level
 assert np.array_equal(a[:,:,[1,3]],b[:,:,[1,3]]) and np.array_equal(a[~m],b[~m])
 return b
