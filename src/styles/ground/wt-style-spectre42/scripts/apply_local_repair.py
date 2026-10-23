"""Local RGB repair or alpha cleanup; all pixels outside permission stay exact."""
from pathlib import Path
import argparse, hashlib, json
import numpy as np
from PIL import Image, ImageFilter

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read_mask(path, size):
    im=Image.open(path); a=np.asarray(im)
    if im.mode!='L' or im.size!=size or not np.isin(a,[0,255]).all():
        raise ValueError('Mask must be binary native-size L')
    return a==255

def component(alpha, seed, threshold=128):
    x,y=map(int,seed); h,w=alpha.shape
    if not (0<=x<w and 0<=y<h) or alpha[y,x]<threshold:
        raise ValueError(f'Component seed is not foreground: {seed}')
    found=np.zeros((h,w),bool); stack=[(x,y)]; found[y,x]=True
    while stack:
        x,y=stack.pop()
        for xx,yy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if 0<=xx<w and 0<=yy<h and not found[yy,xx] and alpha[yy,xx]>=threshold:
                found[yy,xx]=True; stack.append((xx,yy))
    return found

def dilate(mask,radius):
    if not isinstance(radius,int) or not 0<=radius<=32: raise ValueError('Margin must be 0..32 pixels')
    return np.asarray(Image.fromarray(mask.astype('uint8')*255).filter(ImageFilter.MaxFilter(radius*2+1)))>0

def repair(source,generated,mask,out,max_area=.15,*,mode='rgb',protected=None,recipe=None,max_tone_shift=12,min_anchor_iou=.98):
    source,generated,mask,out=map(Path,(source,generated,mask,out))
    if out.exists(): raise FileExistsError(out)
    if mode not in ('rgb','alpha') or not 0<max_area<=1: raise ValueError('Invalid mode or area bound')
    if not np.isfinite(max_tone_shift) or max_tone_shift<0 or not 0<=min_anchor_iou<=1: raise ValueError('Invalid comparison limits')
    recipe=recipe or {}; original=Image.open(source).convert('RGBA'); guide=Image.open(generated).convert('RGBA')
    if max(*original.size,*guide.size)>8192: raise ValueError('Image dimension limit exceeded')
    transform=recipe.get('alignment')
    if transform is not None:
        if len(transform)!=6 or not np.isfinite(transform).all(): raise ValueError('Alignment needs six finite inverse affine coefficients')
        if abs(transform[0]*transform[4]-transform[1]*transform[3])<1e-8: raise ValueError('Singular alignment')
        guide=guide.convert('RGBa').transform(original.size,Image.Transform.AFFINE,transform,Image.Resampling.BICUBIC).convert('RGBA')
    elif guide.size!=original.size: raise ValueError('Different size: supply measured explicit alignment')
    a=np.asarray(original).copy(); b=np.asarray(guide).copy(); permission=read_mask(mask,original.size)
    locked=read_mask(protected,original.size) if protected else np.zeros(permission.shape,bool)
    allowed=permission & ~locked; original_allowed=allowed.copy(); reports=[]
    if mode=='rgb': allowed &= (a[:,:,3]>0)&(b[:,:,3]>0)
    if recipe.get('components'):
        region=np.zeros_like(allowed)
        for entry in recipe['components']:
            sa=component(a[:,:,3],entry['source_seed']); sb=component(b[:,:,3],entry['generated_seed'])
            low,high=entry.get('area_range',[1,a.shape[0]*a.shape[1]])
            if not low<=sa.sum()<=high or not low<=sb.sum()<=high: raise ValueError('Component area outside declared range')
            local=dilate(sa|sb,entry.get('margin',1)) & ~((a[:,:,3]>=128)&~sa) & ~((b[:,:,3]>=128)&~sb) & allowed
            region |= local; offset=np.zeros(3)
            if entry.get('colour_sample'):
                x0,y0,x1,y1=map(int,entry['colour_sample'])
                if not (0<=x0<x1<=a.shape[1] and 0<=y0<y1<=a.shape[0]): raise ValueError('Colour sample outside canvas')
                samples=sa[y0:y1,x0:x1]&sb[y0:y1,x0:x1]
                if samples.sum()<8: raise ValueError('Insufficient opaque colour samples')
                offset=np.median(a[y0:y1,x0:x1,:3][samples].astype(float)-b[y0:y1,x0:x1,:3][samples],axis=0)
                if max(abs(offset))>entry.get('max_colour_offset',40): raise ValueError('Local colour correction exceeds bound')
                b[local,:3]=np.uint8(np.clip(b[local,:3].astype(float)+offset,0,255))
            reports.append({'source_pixels':int(sa.sum()),'guide_pixels':int(sb.sum()),'allowed_pixels':int(local.sum()),'colour_offset':offset.tolist()})
        allowed &= region
    fraction=float(allowed.sum()/max(1,(a[:,:,3]>0).sum()))
    if not allowed.any() or fraction>max_area: raise ValueError(f'Repair area {fraction:.3%} exceeds scope or is empty')
    anchor=~original_allowed
    if recipe.get('anchor_mask'): anchor &= read_mask(recipe['anchor_mask'],original.size)
    aa=(a[:,:,3]>=128)&anchor; bb=(b[:,:,3]>=128)&anchor; union=aa|bb; common=aa&bb
    if union.sum()<8 or common.sum()<8: raise ValueError('Insufficient unchanged alignment anchors')
    iou=float(common.sum()/union.sum())
    if iou<min_anchor_iou: raise ValueError(f'Guide alignment drift: anchor IoU={iou:.6f}')
    tone=np.median(b[common,:3].astype(float)-a[common,:3],axis=0)
    if max(abs(tone))>max_tone_shift: raise ValueError(f'Global tone drift rejected: {tone.tolist()}')
    result=a.copy()
    if mode=='rgb': result[allowed,:3]=b[allowed,:3]
    else:
        result[allowed]=b[allowed]
        result[allowed&(b[:,:,3]==0)]=0
    if not np.array_equal(result[~allowed],a[~allowed]): raise RuntimeError('Locked RGBA changed')
    if mode=='rgb' and not np.array_equal(result[:,:,3],a[:,:,3]): raise RuntimeError('RGB mode changed Alpha')
    out.mkdir(parents=True); Image.fromarray(result).save(out/'repaired-candidate.png')
    Image.fromarray(allowed.astype('uint8')*255).save(out/'actual-edit-mask.png')
    report={'mode':mode,'source_sha256':sha(source),'generated_sha256':sha(generated),'permission_mask_sha256':sha(mask),
            'protected_sha256':sha(protected) if protected else None,'output_sha256':sha(out/'repaired-candidate.png'),
            'alignment':transform or 'native-identity','anchor_iou':iou,'anchor_median_rgb_drift':tone.tolist(),'components':reports,
            'permitted_fraction_of_visible_source':fraction,'actual_changed_pixels':int(np.any(result!=a,axis=2).sum()),
            'locked_pixels_exact':True,'alpha_exact':bool(np.array_equal(result[:,:,3],a[:,:,3])),
            'visual_review':'pending','whole_generated_image_accepted':False}
    (out/'repair.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','generated','mask','out'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--mode',choices=['rgb','alpha'],required=True); p.add_argument('--protected',type=Path); p.add_argument('--recipe',type=Path)
    p.add_argument('--max-area',type=float,default=.15); p.add_argument('--max-tone-shift',type=float,default=12); p.add_argument('--min-anchor-iou',type=float,default=.98)
    args=vars(p.parse_args()); path=args.pop('recipe'); args['recipe']=json.loads(path.read_text(encoding='utf-8')) if path else {}
    if path and args['recipe'].get('anchor_mask'): args['recipe']['anchor_mask']=str((path.parent/args['recipe']['anchor_mask']).resolve())
    print(json.dumps(repair(**args),indent=2))

if __name__=='__main__': main()
