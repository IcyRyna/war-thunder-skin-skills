"""Audit explicitly masked neutral paint in sRGB; never infer masks from color."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image

def measure(image,mask,blue_limit=2.0,chroma_limit=3.0,minimum=64):
 rgb=np.asarray(image)
 m=np.asarray(mask)
 if rgb.ndim!=3 or rgb.shape[2]<3 or m.shape!=rgb.shape[:2]:raise ValueError('RGB image and same-size single-channel mask required')
 if rgb.dtype!=np.uint8 or m.dtype not in (np.dtype('uint8'),np.dtype('bool')):raise ValueError('Expected 8-bit sRGB and binary mask')
 if not np.isin(m,[0,1,255]).all():raise ValueError('Mask must be binary; do not silently resample')
 if not np.isfinite([blue_limit,chroma_limit]).all() or min(blue_limit,chroma_limit)<0 or minimum<1:raise ValueError('Invalid thresholds')
 px=rgb[m>0,:3].astype(float)
 if len(px)<minimum:raise ValueError('Insufficient declared paint samples')
 delta=float(np.mean(px[:,2]-px[:,0]));chroma=float(np.percentile(np.ptp(px,axis=1),95));lum=px@np.array([.2126,.7152,.0722])
 return {'scope':'declared neutral paint only, visual approval separate','pixels':len(px),'mean_rgb':px.mean(0).tolist(),'mean_B_minus_R':delta,'p95_chroma':chroma,'luminance_p10_p50_p90':np.percentile(lum,[10,50,90]).tolist(),'neutral_pass':abs(delta)<=blue_limit and chroma<=chroma_limit,'threshold_status':'proposed engineering tolerance; not visual acceptance'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--mask',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():raise FileExistsError(a.out)
 result=measure(np.asarray(Image.open(a.image).convert('RGB')),np.asarray(Image.open(a.mask).convert('L')))
 a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result));return 0 if result['neutral_pass'] else 2
if __name__=='__main__':raise SystemExit(main())
