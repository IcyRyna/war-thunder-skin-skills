"""Compare corresponding, explicitly masked paint surfaces without recoloring."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from PIL import Image


def sample_stats(image, mask):
    image, mask = np.asarray(image), np.asarray(mask)
    if image.dtype != np.uint8 or image.ndim not in (2,3):
        raise ValueError('expected uint8 scalar or channel image')
    if mask.shape != image.shape[:2] or not np.all(np.isin(mask,[0,1,255])):
        raise ValueError('mask must be binary and match image height/width')
    mask = mask.astype(bool)
    if not mask.any():
        raise ValueError('paint sample must not be empty')
    values = image[mask]
    return {'pixels':int(mask.sum()), 'q10_q50_q90':np.quantile(values,[.1,.5,.9],axis=0).tolist()}


def compare(left_c, right_c, left_mask, right_mask, left_n=None, right_n=None,
            left_ao=None, right_ao=None):
    for c in (left_c,right_c):
        if np.asarray(c).ndim != 3 or np.asarray(c).shape[2] not in (3,4):
            raise ValueError('C must contain RGB or RGBA')
    result = {'C':{'left':sample_stats(np.asarray(left_c)[...,:3],left_mask),
                   'right':sample_stats(np.asarray(right_c)[...,:3],right_mask)},
              'verdict':'measurements_only; inspect materials and visual evidence'}
    for name,l,r in [('N',left_n,right_n),('AO',left_ao,right_ao)]:
        if (l is None) != (r is None):
            raise ValueError(name+' requires both corresponding images')
        if l is not None:
            if name=='N' and any(np.asarray(x).ndim!=3 or np.asarray(x).shape[2]!=4 for x in (l,r)):
                raise ValueError('packed N requires all four raw channels')
            result[name]={'left':sample_stats(l,left_mask),'right':sample_stats(r,right_mask)}
    for name in ('C','N','AO'):
        if name in result:
            ql=np.asarray(result[name]['left']['q10_q50_q90'])
            qr=np.asarray(result[name]['right']['q10_q50_q90'])
            if ql.shape!=qr.shape:
                raise ValueError(name+' channel counts must correspond')
            result[name]['max_quantile_difference']=float(np.max(abs(ql-qr)))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for side in ('left','right'):
        for kind in ('c','mask','n','ao'):
            p.add_argument('--'+side+'-'+kind,type=Path,required=kind in ('c','mask'))
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():
        p.error('output exists; use a new path')
    inputs={}
    def load(name):
        path=getattr(a,name)
        if path is None:
            return None
        inputs[name]={'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        with Image.open(path) as im:
            # Packed data must already be RGBA, never invent an N Alpha.
            if name.endswith('_n') and im.mode!='RGBA':
                raise ValueError('N must be a decoded four-channel RGBA image')
            return np.array(im.convert('L') if name.endswith(('_mask','_ao')) else im)
    result=compare(*(load(k) for k in ('left_c','right_c','left_mask','right_mask',
                                     'left_n','right_n','left_ao','right_ao')))
    result['inputs']=inputs
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
