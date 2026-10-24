"""Native-detail satin metal with explicit masking and no donor pixels."""
import numpy as np
from scipy.ndimage import gaussian_filter

def wear_field(source, mask):
    a=np.asarray(source,dtype=np.float32)
    low=gaussian_filter(a,1.)-gaussian_filter(a,7.)
    edge=abs(low)
    scale=max(float(np.percentile(edge[mask],85)),1.)
    return np.clip(edge/scale-.25,0,1)

def satin_color(native, mask, level=143, wear_contrast=18):
    a=np.asarray(native);m=np.asarray(mask,bool)
    if a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=4 or m.shape!=a.shape[:2] or not m.any():raise ValueError('Native RGBA and explicit nonempty mask required')
    lum=a[:,:,:3].astype(np.float32).mean(2);wear=wear_field(lum,m);fine=lum-gaussian_filter(lum,2.)
    value=np.uint8(np.clip(np.rint(level+.10*fine-wear_contrast*wear),level-wear_contrast-3,level+3))
    out=np.zeros_like(a);out[m,:3]=value[m,None];out[m,3]=255
    return out

def satin_normal(native, coated, mask, inverted_roughness=145, metalness=229, roughness_variation=24):
    a,b,m=np.asarray(native),np.asarray(coated),np.asarray(mask,bool)
    if a.dtype!=np.uint8 or a.shape!=b.shape or a.ndim!=3 or a.shape[2]!=4 or m.shape!=a.shape[:2] or not m.any():raise ValueError('Matching native/painted packed RGBA and explicit mask required')
    if not 0<=inverted_roughness<=255 or not 0<=metalness<=255:raise ValueError('Packed values must be bytes')
    out=b.copy();wear=wear_field(a[:,:,0],m)
    out[m,0]=np.uint8(np.clip(np.rint(inverted_roughness-roughness_variation*wear[m]),0,255));out[m,2]=metalness
    for k in [1,3]:
        detail=a[:,:,k].astype(np.float32)-gaussian_filter(a[:,:,k].astype(np.float32),1.25)
        out[m,k]=np.uint8(np.clip(np.rint(127+.06*detail[m]),124,130))
    assert np.array_equal(out[~m],b[~m])
    return out
