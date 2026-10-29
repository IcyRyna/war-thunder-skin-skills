"""Preflight graphic content and effective detail, separate from artistic approval."""
from pathlib import Path
import hashlib,math
import numpy as np

def authorize(record,intent,root,target_profile=None):
    if intent not in ('style_transfer','source_reproduction'):raise ValueError('Unknown task intent')
    if intent not in record.get('allowed_modes',[]):raise ValueError('Asset is reference/reproduction only for this intent: '+record.get('id','?'))
    if intent=='source_reproduction':return
    from equipment_labels import check_label
    check_label(record,target_profile)
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
    # det(J)/||J||_F is a conservative lower bound for the smallest
    # singular value. Linear numerators and denominator attain extrema
    # on the four corners, including strong perspective between samples.
    corners=np.array([[0,0],[w,0],[w,h],[0,h]],float)
    denominators=g*corners[:,0]+k*corners[:,1]+1
    if np.min(denominators)*np.max(denominators)<=0:raise ValueError("Projective horizon crosses source canvas")
    min_z=np.min(np.abs(denominators));max_z=np.max(np.abs(denominators))
    numerators=np.stack(((a*k-b*g)*corners[:,1]+a-c*g,
                         (b*g-a*k)*corners[:,0]+b-c*k,
                         (d*k-e*g)*corners[:,1]+d-f*g,
                         (e*g-d*k)*corners[:,0]+e-f*k),axis=1)
    norm_upper=np.sqrt(np.sum(np.max(np.abs(numerators),axis=0)**2))/min_z**2
    det=abs(np.linalg.det(np.array([[a,b,c],[d,e,f],[g,k,1]])))
    if abs(g)+abs(k)<1e-14:return min(scales)
    return min(min(scales),det/max_z**3/norm_upper)

def check_detail(record,quad,image_size,rotation=0,budget=None,source_image=None):
    size=record.get('native_detail_size')
    if not isinstance(size,list) or len(size)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<2 for v in size):
        raise ValueError('Measured native_detail_size is required; PNG canvas size is insufficient')
    if any(s>i for s,i in zip(size,image_size)):raise ValueError('Effective raster detail cannot exceed the actual image')
    limits={'min_line_px':2.,'min_text_cap_px':12.}
    if budget is not None and not isinstance(budget,dict):raise ValueError('Quality budget must be a mapping')
    for key,value in (budget or {}).items():
        if key not in limits or type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid quality budget')
        if value<limits[key]:raise ValueError('Quality budget cannot silently lower current line/text minimums')
        limits[key]=float(value)
    scale=minimum_scale(quad,image_size,rotation);features=record.get('critical_features',{})
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
    raster_checks={}
    if source_image is not None:
        raster_checks=check_projected_features(record,quad,source_image,rotation,limits)
    return {'raster_features':raster_checks,'estimated_min_pixel_scale':scale,'features':checks,'coordinate_space':'source_canvas_pixels','visual_review':'still required'}


def check_projected_features(record,quad,source,rotation,limits):
    from PIL import Image
    from compose_native import warp
    im=source.convert("RGBA")
    regions=record.get("feature_regions")
    if not isinstance(regions,dict):raise ValueError("Actual graphic needs source-pixel feature_regions")
    result={}
    for feature,limit in (("line_width_px","min_line_px"),("text_cap_height_px","min_text_cap_px")):
        if feature not in record["critical_features"]:continue
        spec=regions.get(feature,{})
        box=spec.get("bounds_px");axis=spec.get("axis")
        if not isinstance(box,list) or len(box)!=4 or any(type(x) is not int for x in box) or axis not in ("x","y"):
            raise ValueError("Critical feature needs integer source bounds and axis")
        x0,y0,x1,y1=box
        if not 0<=x0<x1<=im.width or not 0<=y0<y1<=im.height:raise ValueError("Critical feature bounds escape source canvas")
        span=x1-x0 if axis=="x" else y1-y0
        if abs(span-record["critical_features"][feature])>.5:raise ValueError("Feature measurement disagrees with source-pixel bounds")
        pixels=np.asarray(im);alpha=pixels[...,3].copy()
        selector=spec.get("selector")
        if selector is not None:
            if selector.get("mode")!="rgb_equal" or not isinstance(selector.get("rgb"),list) or len(selector["rgb"])!=3 or any(type(v) is not int or not 0<=v<=255 for v in selector["rgb"]):
                raise ValueError("Invalid source feature selector")
            alpha[~np.all(pixels[...,:3]==selector["rgb"],axis=-1)]=0
        ys,xs=np.nonzero(alpha[y0:y1,x0:x1]>=128)
        if not len(xs) or (xs.max()-xs.min()+1 if axis=="x" else ys.max()-ys.min()+1)!=span:
            raise ValueError("Declared critical feature is not supported by actual source ink")
        isolated=np.zeros((im.height,im.width,4),np.uint8)
        isolated[y0:y1,x0:x1,:3]=255;isolated[y0:y1,x0:x1,3]=alpha[y0:y1,x0:x1]
        # Translate the target quad to a bounded local raster without changing its scale.
        q=np.asarray(quad,float);lo=np.floor(q.min(0))-2;local=q-lo
        size=tuple((np.ceil(local.max(0))+3).astype(int))
        if max(size)>16384 or min(size)<1:raise ValueError("Projected feature raster exceeds supported bounds")
        rendered=np.asarray(warp(Image.fromarray(isolated).rotate(rotation,expand=True),local,size))[...,3]
        py,px=np.nonzero(rendered>=128)
        if not len(px):raise ValueError("Projected critical feature has no opaque pixels")
        # The rotated local feature axis is carried by the same corner homography.
        rw,rh=im.size if rotation in (0,180) else (im.height,im.width)
        corners=np.array([[0,0],[rw-1,0],[rw-1,rh-1],[0,rh-1]],float)
        matrix=[];rhs=[]
        for (x,y),(u,v) in zip(corners,local):
            matrix.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
        H=np.r_[np.linalg.solve(np.array(matrix),rhs),1].reshape(3,3)
        cx,cy=(x0+x1-1)/2,(y0+y1-1)/2
        delta=np.array([1.,0.]) if axis=="x" else np.array([0.,1.])
        def turn(p):
            x,y=p
            return {0:(x,y),90:(y,im.width-1-x),180:(im.width-1-x,im.height-1-y),270:(im.height-1-y,x)}[rotation]
        ends=np.array([turn(np.array([cx,cy])-delta*.5),turn(np.array([cx,cy])+delta*.5)])
        projected=np.c_[ends,np.ones(2)]@H.T;projected=projected[:,:2]/projected[:,2,None]
        vector=projected[1]-projected[0];vector/=np.linalg.norm(vector)
        pixels=np.c_[px,py]@vector
        extent=float(pixels.max()-pixels.min()+1)
        if extent+1e-6<limits[limit]:raise ValueError("Actual rasterized "+feature+" is below declared budget")
        result[feature]={"opaque_projected_extent_px":extent,"source_bounds_px":box}
    return result
