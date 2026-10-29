"""Transform packed tangent normals and downsample explicit masks without alpha misuse."""
from __future__ import annotations
import numpy as np
from PIL import Image
from skill_contract import binary, number


def transform_packed(packed, rotation=0, mirror_u=False, mirror_v=False):
    data=np.asarray(packed)
    if data.dtype!=np.uint8 or data.ndim!=3 or data.shape[2]!=4:
        raise ValueError("Packed material must be RGBA8: R, normal X, B, normal Y")
    if type(rotation) is not int or rotation not in (0,90,180,270) or type(mirror_u) is not bool or type(mirror_v) is not bool:
        raise ValueError("Explicit right-angle rotation and boolean mirror axes required")
    result=np.rot90(data,rotation//90).copy()
    x=result[...,1].astype(float)/127.5-1
    y=result[...,3].astype(float)/127.5-1
    for _ in range(rotation//90):
        x,y=-y,x
    if mirror_u:
        result=result[:,::-1].copy();x=-x[:,::-1];y=y[:,::-1]
    if mirror_v:
        result=result[::-1].copy();x=x[::-1];y=-y[::-1]
    result[...,1]=np.rint(np.clip(x*127.5+127.5,0,255)).astype("uint8")
    result[...,3]=np.rint(np.clip(y*127.5+127.5,0,255)).astype("uint8")
    return result


def _box(array,size):
    return np.asarray(Image.fromarray(np.asarray(array,np.float32)).resize(size,Image.Resampling.BOX),dtype=np.float32)


def conservative_mask(mask,size):
    source=binary(mask,"source structural/protection mask")
    if not isinstance(size,(tuple,list)) or len(size)!=2:raise ValueError("Target width/height required")
    width=number(size[0],"width",1,source.shape[1],True)
    height=number(size[1],"height",1,source.shape[0],True)
    # Keep any contributing sample, including one-pixel lips and protected glass.
    return _box(source.astype(np.float32),(width,height))>0


def downsample_patch(packed,coverage,size):
    data=np.asarray(packed);cover=np.asarray(coverage)
    if data.dtype!=np.uint8 or data.ndim!=3 or data.shape[2]!=4 or cover.shape!=data.shape[:2] or cover.dtype!=np.uint8:
        raise ValueError("Aligned packed RGBA8 and separate coverage L8 required")
    if not isinstance(size,(tuple,list)) or len(size)!=2:raise ValueError("Target width/height required")
    width=number(size[0],"width",1,data.shape[1],True)
    height=number(size[1],"height",1,data.shape[0],True)
    if width*data.shape[0]!=height*data.shape[1]:
        raise ValueError("Anisotropic grain scaling needs actual target regeneration or independent UV mapping")
    if not cover.any():raise ValueError("Empty patch")
    if (width,height)==(data.shape[1],data.shape[0]):return data.copy(),cover.copy()
    weight=cover.astype(float)/255;denominator=_box(weight,(width,height))
    result=np.empty((height,width,4),np.uint8)
    for channel in (0,2):
        average=np.divide(_box(data[...,channel]*weight,(width,height)),denominator,
                          out=np.zeros_like(denominator),where=denominator>0)
        result[...,channel]=np.rint(np.clip(average,0,255)).astype("uint8")
    x=data[...,1].astype(float)/127.5-1;y=data[...,3].astype(float)/127.5-1
    z=np.sqrt(np.maximum(1-x*x-y*y,0))
    vector=np.stack([_box(v*weight,(width,height)) for v in (x,y,z)],axis=-1)
    vector/=np.maximum(np.linalg.norm(vector,axis=-1,keepdims=True),1e-12)
    result[...,1]=np.rint(np.clip(vector[...,0]*127.5+127.5,0,255)).astype("uint8")
    result[...,3]=np.rint(np.clip(vector[...,1]*127.5+127.5,0,255)).astype("uint8")
    result[denominator==0]=[0,128,0,128]
    return result,np.rint(np.clip(denominator*255,0,255)).astype("uint8")
