"""A bounded sRGB coverage-rounding check; never use this for packed N/AO."""
import numpy as np

def check_composite(expected,actual,fractional_coverage):
 a=np.asarray(expected);b=np.asarray(actual);m=np.asarray(fractional_coverage,dtype=bool)
 if a.dtype!=np.uint8 or b.dtype!=np.uint8 or a.shape!=b.shape or a.ndim!=3 or a.shape[2]!=4 or m.shape!=a.shape[:2]:raise ValueError('Expected matching uint8 RGBA and explicit fractional-coverage mask')
 if not np.array_equal(a[:,:,3],b[:,:,3]):raise ValueError('Composite changed coverage Alpha')
 delta=np.abs(a[:,:,:3].astype(np.int16)-b[:,:,:3].astype(np.int16));changed=delta.max(2)>0
 if np.any(changed&~m):raise ValueError('Color changed outside fractional-coverage pixels')
 if delta.max()>1:raise ValueError('Composite exceeds the observed one-unit sRGB rounding bound')
 return {'max_RGB_delta':int(delta.max()),'changed_pixels':int(changed.sum()),'Alpha_exact':True,'outside_fractional_coverage_exact':True,'scope':'8-bit sRGB color compositing only; canonical color output is declared by the caller; N/AO require exact data'}
