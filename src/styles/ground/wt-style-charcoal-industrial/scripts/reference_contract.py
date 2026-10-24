"""Check named paint/color roles without treating UV pixels as visible vehicle area."""
from __future__ import annotations
import numpy as np

REQUIRED_ROLES={'honey_band','module_focus','circuit','pixel_field','warning','micro_accents'}
def check_roles(placements,omissions=None):
    raw_roles={p['role'] for p in placements if p.get('pixels',0)>0};observed={'module_focus' if r in {'instrument','armour_identifier','equipment_id'} else r for r in raw_roles};omissions=omissions or {}
    for role,reason in omissions.items():
        if role not in REQUIRED_ROLES or not isinstance(reason,str) or len(reason.strip())<12:raise ValueError('Omission needs a specific physical explanation')
    missing=REQUIRED_ROLES-observed-set(omissions)
    if missing:raise ValueError('Incomplete SPECTRE42 system: '+', '.join(sorted(missing)))
    return {'observed_roles':sorted(observed),'source_role_names':sorted(raw_roles),'explicit_omissions':omissions,'visual_acceptance':'not inferred'}

def check_base_color(rgba,base_mask,reference=(31,31,31),max_median_delta=5,max_neutral_chroma=6):
    a=np.asarray(rgba);mask=np.asarray(base_mask,dtype=bool)
    if a.ndim!=3 or a.shape[2] not in (3,4) or mask.shape!=a.shape[:2] or mask.sum()<32:raise ValueError('A named nonempty base-paint mask is required')
    p=a[:,:,:3][mask].astype(float);median=np.median(p,axis=0);chroma=p.max(1)-p.min(1)
    if np.max(abs(median-np.asarray(reference)))>max_median_delta:raise ValueError('Base paint drifts from the frozen AZUR color anchor')
    if np.percentile(chroma,95)>max_neutral_chroma:raise ValueError('Base paint retains a color cast or source camouflage')
    return {'masked_UV_pixels':int(mask.sum()),'median_rgb':median.tolist(),'chroma_p95':float(np.percentile(chroma,95)),'denominator':'named base-paint UV pixels only; not whole-vehicle visible area'}

def masked_gloss(native,mask,factor=.72,ceiling=82):
    a=np.asarray(native);m=np.asarray(mask,dtype=bool)
    if a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=4 or m.shape!=a.shape[:2]:raise ValueError('Packed N needs uint8 RGBA and matching explicit mask')
    if not 0<factor<=1 or not 0<=ceiling<=255:raise ValueError('Invalid declared paint-finish adjustment')
    out=a.copy();out[m,0]=np.uint8(np.minimum(np.rint(a[m,0].astype(float)*factor),ceiling))
    if not np.array_equal(out[:,:,1:],a[:,:,1:]) or not np.array_equal(out[~m],a[~m]):raise AssertionError('Packed-channel or protected-pixel invariant broken')
    return out
