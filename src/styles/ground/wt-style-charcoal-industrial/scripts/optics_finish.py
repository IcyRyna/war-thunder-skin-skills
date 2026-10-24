"""Polish confirmed vehicle glass normals without changing color/opacity or normal components."""
import numpy as np
def polish_glass(normal,roughness_floor,shader):
 a=np.asarray(normal)
 if shader not in ['dynamic_pbr_glass','dynamic_masked_chrome_bump']:raise ValueError('Native optical shader must be explicitly confirmed')
 if a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=4 or not 0<=roughness_floor<=255:raise ValueError('Packed RGBA and a byte roughness floor required')
 b=a.copy();b[:,:,0]=np.maximum(b[:,:,0],roughness_floor);assert np.array_equal(b[:,:,1:],a[:,:,1:]);return b
