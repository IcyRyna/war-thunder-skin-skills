"""Preflight graphic content and effective detail, separate from artistic approval."""
from pathlib import Path
import hashlib,math
import numpy as np

def authorize(record,intent,root):
    if intent not in ('style_transfer','source_reproduction'):raise ValueError('Unknown task intent')
    if intent not in record.get('allowed_modes',[]):raise ValueError('Asset is reference/reproduction only for this intent: '+record.get('id','?'))
    if intent=='source_reproduction':return
    if record.get('origin_class') not in ('clean_graphic','target_authored'):
        raise ValueError('Style asset needs a clean graphic or target-authored source')
    if record.get('source_surface_content') is not False or record.get('lighting_content')!='flat_graphic':
        raise ValueError('Source-surface or baked-lighting content is unresolved')
    review=record.get('graphic_validation',{})
    if review.get('state')!='checked_local':raise ValueError('Graphic content check is pending')
    evidence=review.get('evidence',{})
    file=(Path(root)/evidence.get('file','')).resolve()
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=evidence.get('sha256'):
        raise ValueError('Graphic review evidence is missing or changed')

def minimum_scale(quad,detail_size,rotation=0):
    """Estimate local minimum pixel scale on a 5x5 homography sample grid."""
    size=np.asarray(detail_size,dtype=float)
    if size.shape!=(2,) or not np.isfinite(size).all() or (size<2).any():raise ValueError('Measured native_detail_size is required')
    if rotation in (90,270):size=size[::-1]
    w,h=size-1;source=[(0,0),(w,0),(w,h),(0,h)]
    target=np.asarray(quad,dtype=float)
    if target.shape!=(4,2) or not np.isfinite(target).all():raise ValueError('Invalid target quad')
    matrix=[];rhs=[]
    for (x,y),(u,v) in zip(source,target):
        matrix.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
    try:a,b,c,d,e,f,g,k=np.linalg.solve(np.asarray(matrix,float),np.asarray(rhs,float))
    except np.linalg.LinAlgError as exc:raise ValueError('Degenerate projected detail transform') from exc
    scales=[]
    for y in np.linspace(0,h,5):
        for x in np.linspace(0,w,5):
            z=g*x+k*y+1
            if abs(z)<1e-8:raise ValueError('Singular projected detail transform')
            u=a*x+b*y+c;v=d*x+e*y+f
            j=np.array([[(a*z-u*g)/z**2,(b*z-u*k)/z**2],[(d*z-v*g)/z**2,(e*z-v*k)/z**2]])
            scales.append(float(np.linalg.svd(j,compute_uv=False)[-1]))
    return min(scales)

def check_detail(record,quad,image_size,rotation=0,budget=None):
    size=record.get('native_detail_size')
    if not isinstance(size,list) or len(size)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<2 for v in size):
        raise ValueError('Measured native_detail_size is required; PNG canvas size is insufficient')
    if any(s>i for s,i in zip(size,image_size)):raise ValueError('Effective raster detail cannot exceed the actual image')
    limits={'min_line_px':2.,'min_text_cap_px':12.}
    if budget is not None and not isinstance(budget,dict):raise ValueError('Quality budget must be a mapping')
    for key,value in (budget or {}).items():
        if key not in limits or type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid quality budget')
        limits[key]=float(value)
    scale=minimum_scale(quad,size,rotation);features=record.get('critical_features',{})
    if not isinstance(features,dict) or not features:raise ValueError('Measured critical features required')
    checks={}
    for name,key in [('line_width_px','min_line_px'),('text_cap_height_px','min_text_cap_px')]:
        if name not in features:continue
        width=features[name]
        if type(width) not in (int,float) or not math.isfinite(width) or width<=0:raise ValueError('Invalid native feature measurement')
        projected=width*scale
        if projected+1e-6<limits[key]:raise ValueError(f'Projected {name} {projected:.3f}px is below declared budget {limits[key]:.3f}px')
        checks[name]={'native_px':width,'estimated_min_projected_px':projected,'budget_px':limits[key]}
    if not checks:raise ValueError('No supported critical feature measurements')
    if record.get('contains_text',True) and 'text_cap_height_px' not in checks:raise ValueError('Readable text needs measured cap height')
    return {'estimated_min_pixel_scale':scale,'features':checks,'visual_review':'still required'}
