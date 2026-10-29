"""Measure graphic placement on native planar carrier triangles; margins are computed, not asserted."""
from __future__ import annotations
import numpy as np
from skill_contract import checked_file, read_json, require_text, number, policy


def _area(polygon):
    if len(polygon)<3:return 0.
    p=np.asarray(polygon,float)
    return abs(float(np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1)))/2)


def _clip(subject,triangle):
    clip=np.asarray(triangle,float)
    signed=np.sum(clip[:,0]*np.roll(clip[:,1],-1)-clip[:,1]*np.roll(clip[:,0],-1))
    if signed<0:clip=clip[::-1]
    output=[np.asarray(p,float) for p in subject]
    for a,b in zip(clip,np.roll(clip,-1,axis=0)):
        source=output;output=[]
        if not source:break
        def side(p):return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
        previous=source[-1];previous_d=side(previous)
        for current in source:
            current_d=side(current)
            if (current_d>=-1e-10)!=(previous_d>=-1e-10):
                denominator=previous_d-current_d
                if abs(denominator)>1e-15:output.append(previous+(current-previous)*(previous_d/denominator))
            if current_d>=-1e-10:output.append(current)
            previous,previous_d=current,current_d
    return output


def measure_fit(positions,origin,u_axis,v_axis,center,size,rotation_deg=0,minimum_margin_m=0):
    p=np.asarray(positions,float);origin=np.asarray(origin,float)
    u,v=np.asarray(u_axis,float),np.asarray(v_axis,float)
    center,size=np.asarray(center,float),np.asarray(size,float)
    if p.ndim!=3 or p.shape[1:]!=(3,3) or not len(p) or not np.isfinite(p).all():
        raise ValueError("Actual native carrier triangles required")
    if origin.shape!=(3,) or u.shape!=(3,) or v.shape!=(3,) or not np.isfinite(np.concatenate((origin,u,v))).all():
        raise ValueError("Finite native carrier frame required")
    if abs(np.linalg.norm(u)-1)>1e-6 or abs(np.linalg.norm(v)-1)>1e-6 or abs(float(u@v))>1e-6:
        raise ValueError("Carrier u/v axes must be orthonormal unit vectors")
    if center.shape!=(2,) or size.shape!=(2,) or not np.isfinite(np.concatenate((center,size))).all() or (size<=0).any():
        raise ValueError("Finite center and positive unrotated graphic dimensions required")
    number(rotation_deg,"rotation degrees",-360,360)
    number(minimum_margin_m,"minimum edge margin",0,1)
    relative=p-origin;n=np.cross(u,v)
    if np.max(np.abs(relative@n))>.002:raise ValueError("Selected carrier is not planar within 2 mm")
    triangles=np.stack((relative@u,relative@v),axis=-1)
    if any(_area(t)<1e-12 for t in triangles):raise ValueError("Degenerate carrier triangles")
    angle=np.deg2rad(rotation_deg);matrix=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    quad=np.array([[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]])*size
    quad=quad@matrix.T+center
    graphic_area=float(np.prod(size))
    covered=sum(_area(_clip(quad,t)) for t in triangles)
    if covered>graphic_area+max(1e-9,graphic_area*1e-6):
        raise ValueError("Overlapping coplanar carrier faces; select the true exterior once")
    lo,hi=triangles.reshape(-1,2).min(0),triangles.reshape(-1,2).max(0)
    qlo,qhi=quad.min(0),quad.max(0)
    margins=[float(qlo[0]-lo[0]),float(hi[0]-qhi[0]),float(qlo[1]-lo[1]),float(hi[1]-qhi[1])]
    missing=max(0.,graphic_area-covered)
    native_area=sum(_area(t) for t in triangles)
    errors=[]
    if missing>max(1e-9,graphic_area*1e-6):errors.append("Graphic extends outside actual native carrier")
    if min(margins)<minimum_margin_m-1e-6:errors.append("Graphic violates declared native edge margin")
    return {"technical_pass":not errors,"errors":errors,"carrier_bounds_uv_m":[lo.tolist(),hi.tolist()],
            "graphic_corners_uv_m":quad.tolist(),"computed_margins_m":margins,
            "covered_fraction":min(1.,covered/graphic_area),"graphic_area_m2":graphic_area,
            "carrier_area_m2":native_area,"carrier_fill_fraction":graphic_area/native_area,
            "edge_scope":"AABB edge margin plus exact triangle-union fit; concave internal clearance requires actual observation"}


def validate_layout_checks(root,choice,model_sha256,native=None):
    required=choice.get("required_instances")
    rows=choice.get("placement_checks")
    if not isinstance(required,list) or not required or len(set(required))!=len(required) or not isinstance(rows,list):
        raise ValueError("Roof needs actual intended instance IDs and native placement checks")
    reports={};seen=set()
    for row in rows:
        ident=require_text(row.get("id"),"roof group instance")
        if ident in seen:raise ValueError("Duplicate roof group instance")
        seen.add(ident)
        if row.get("source_model_sha256")!=model_sha256:raise ValueError("Roof carrier belongs to different model/UV state")
        geometry=checked_file(root,row.get("geometry"),"native roof carrier geometry")
        faces=row.get("faces")
        with np.load(geometry,allow_pickle=False) as g:
            positions=np.asarray(g["positions"],float)
        if not isinstance(faces,list) or not faces or any(type(i) is not int or not 0<=i<len(positions) for i in faces) or len(set(faces))!=len(faces):
            raise ValueError("Actual roof carrier face IDs required")
        if native is not None:
            from visibility_probe import scene_geometry
            _,posed,_,source_ids=scene_geometry(root,row,native)
            positions=posed[source_ids]
        frame=row.get("frame",{})
        mode=row.get("mode")
        if mode=="actual_ink":
            if row.get("contains_text") is True:
                require_front_facing_text(positions[faces],frame.get("u"),frame.get("v"))
            from PIL import Image
            asset=checked_file(root,row.get("asset"),"actual warning artwork Alpha")
            with Image.open(asset) as image:
                if image.mode!="RGBA":raise ValueError("Actual warning source must preserve Alpha")
                alpha=np.array(image)[...,3]
                points=ink_points(alpha,row.get("center_uv_m"),row.get("graphic_size_m"),row.get("rotation_deg",0))
                ink_y,ink_x=np.nonzero(alpha)
                content_fraction=((ink_x.max()-ink_x.min()+1)/alpha.shape[1])*((ink_y.max()-ink_y.min()+1)/alpha.shape[0])
            report=measure_ink_fit(positions[faces],points,frame.get("origin"),frame.get("u"),frame.get("v"),
                row.get("scope_polygon_uv_m"),row.get("depth_interval_m"),row.get("minimum_margin_m",0))
            composition=measure_composition(positions[faces],points,frame.get("origin"),frame.get("u"),frame.get("v"),
                                            float(np.prod(row["graphic_size_m"]))*float(content_fraction))
            report.update(composition)
            report["canvas_fill_fraction"]=float(np.prod(row["graphic_size_m"]))/report["carrier_area_m2"]
            report["scope_fill_fraction"]=float(np.prod(row["graphic_size_m"]))*float(content_fraction)/report["scope_area_m2"]
            report["fill_basis"]="actual nonzero-Alpha group bounds / complete selected native carrier; clipping scope is not the composition denominator"
        elif mode=="solid_rectangle":
            report=measure_fit(positions[faces],frame.get("origin"),frame.get("u"),frame.get("v"),
                               row.get("center_uv_m"),row.get("graphic_size_m"),row.get("rotation_deg",0),
                               row.get("minimum_margin_m",0))
        else:
            raise ValueError("Choose actual_ink for transparent graphics or solid_rectangle for a true solid panel")
        if not report["technical_pass"]:raise ValueError(ident+": "+"; ".join(report["errors"]))
        requirement=row.get("composition_requirement")
        if requirement is not None:
            if mode!="actual_ink" or requirement.get("basis")!="complete_native_carrier":
                raise ValueError("Composition extent must use the complete native carrier")
            require_text(requirement.get("reason"),"composition extent reason")
            minimum=requirement.get("min_span_fraction")
            if not isinstance(minimum,list) or len(minimum)!=2:raise ValueError("Choose both native panel span requirements")
            minimum=[number(x,"native panel span minimum",0,1) for x in minimum]
            if any(a+1e-9<b for a,b in zip(report["ink_span_fraction"],minimum)):
                raise ValueError("Graphic leaves the requested full native panel extent unfilled")
        fill=row.get("target_fill")
        if not isinstance(fill,dict):raise ValueError("Choose target graphic-group scale before painting")
        low=number(fill.get("min"),"target fill minimum",.01,1)
        high=number(fill.get("max"),"target fill maximum",low,1)
        if low<policy()["layout_checks"]["roof_min_fill_fraction"]:
            override=fill.get("smaller_group_basis",{})
            require_text(override.get("reason"),"smaller panel-group design reason")
            checked_file(root,override.get("evidence"),"specific smaller group reference")
        require_text(fill.get("reason"),"target group scale basis")
        if not low<=report["carrier_fill_fraction"]<=high:
            raise ValueError("Roof group scale differs from declared target, even though it fits")
        visibility=row.get("visibility")
        if not isinstance(visibility,dict):raise ValueError("Actual model occlusion probe required")
        proof=read_json(checked_file(root,visibility.get("probe"),"roof glyph/stripe visibility probe"))
        if proof.get("source_model_sha256")!=model_sha256 or proof.get("geometry_sha256")!=row["geometry"]["sha256"]:
            raise ValueError("Roof visibility probe refers to different model/carrier")
        for key in ("center_uv_m","graphic_size_m","rotation_deg"):
            if proof.get(key)!=row.get(key,0 if key=="rotation_deg" else None):
                raise ValueError("Roof visibility probe does not match actual layout")
        if proof.get("frame")!=row.get("frame"):
            raise ValueError("Roof visibility probe uses different local axes/origin")
        if mode=="actual_ink" and proof.get("asset_sha256")!=row.get("asset",{}).get("sha256"):
            raise ValueError("Roof visibility probe refers to different warning artwork")
        measured=None
        if native is not None:
            from visibility_probe import compute_visibility
            measured=compute_visibility(root,row,native)
            proof={**proof,**measured}
        total=number(proof.get("ink_samples"),"actual ink samples",1,10**9,True)
        visible=number(proof.get("visible_ink_samples"),"visible ink samples",0,total,True)
        required_fraction=max(policy()["layout_checks"]["roof_min_visible_fraction"],
                              number(visibility.get("minimum_visible_fraction"),"minimum visible fraction",.5,1))
        fraction=visible/total
        if fraction<required_fraction:
            override=visibility.get("accepted_occlusion")
            if not isinstance(override,dict):raise ValueError("Roof warning is physically obstructed")
            require_text(override.get("reason"),"specific accepted obstruction")
            checked_file(root,override.get("evidence"),"current target occlusion acceptance")
        if measured and measured["text_samples"]:
            text_fraction=measured["visible_text_samples"]/measured["text_samples"]
            if text_fraction<required_fraction and not visibility.get("accepted_text_occlusion"):
                raise ValueError("Core warning text is physically obstructed")
            if text_fraction<required_fraction:
                override=visibility["accepted_text_occlusion"]
                require_text(override.get("reason"),"specific core text obstruction acceptance")
                checked_file(root,override.get("evidence"),"current core text acceptance")
            report["visible_text_fraction"]=text_fraction
        report["recomputed_visibility"]=measured
        report["visible_ink_fraction"]=fraction;reports[ident]=report
    if seen!=set(required):raise ValueError("Missing or extra actual roof warning group")
    return reports


def measure_composition(positions,points,origin,u_axis,v_axis,graphic_bounds_area):
    """Use the real support, never a conveniently cropped clipping polygon."""
    p=np.asarray(positions,float);xy=np.asarray(points,float);o=np.asarray(origin,float)
    u,v=np.asarray(u_axis,float),np.asarray(v_axis,float)
    if p.ndim!=3 or p.shape[1:]!=(3,3) or not len(p) or not np.isfinite(p).all():raise ValueError("Actual native carrier required")
    if xy.ndim!=2 or xy.shape[1]!=2 or not len(xy) or not np.isfinite(xy).all():raise ValueError("Actual ink points required")
    if o.shape!=(3,) or u.shape!=(3,) or v.shape!=(3,) or not np.isfinite(np.r_[o,u,v]).all():raise ValueError("Finite carrier frame required")
    if abs(np.linalg.norm(u)-1)>1e-6 or abs(np.linalg.norm(v)-1)>1e-6 or abs(float(u@v))>1e-6:raise ValueError("Orthonormal carrier frame required")
    area=number(graphic_bounds_area,"graphic bounds area",0,1e8)
    projected=np.stack(((p-o)@u,(p-o)@v),axis=-1)
    carrier_area=sum(_area(t) for t in projected)
    bounds=np.array([projected.reshape(-1,2).min(0),projected.reshape(-1,2).max(0)])
    extent=bounds[1]-bounds[0]
    if carrier_area<=1e-12 or (extent<=1e-12).any():raise ValueError("Degenerate native composition carrier")
    span=xy.max(0)-xy.min(0)
    return {"carrier_area_m2":float(carrier_area),"carrier_fill_fraction":float(area/carrier_area),
            "native_carrier_bounds_uv_m":bounds.tolist(),"ink_span_fraction":(span/extent).tolist()}


def image_coordinates(points,center,size,rotation_deg=0):
    """Inverse of ink_points: native planar XY to top-left image UV."""
    points=np.asarray(points,float);center=np.asarray(center,float);size=np.asarray(size,float)
    if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all():raise ValueError("Finite planar points required")
    if center.shape!=(2,) or size.shape!=(2,) or not np.isfinite(np.r_[center,size]).all() or (size<=0).any():raise ValueError("Finite placement and positive size required")
    angle=np.deg2rad(number(rotation_deg,"rotation",-360,360))
    matrix=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    local=(points-center)@matrix/size
    return np.stack((local[:,0]+.5,.5-local[:,1]),axis=-1)


def require_front_facing_text(positions,u_axis,v_axis):
    """A back-facing planar basis mirrors text even if UV inversion is exact."""
    p=np.asarray(positions,float);u=np.asarray(u_axis,float);v=np.asarray(v_axis,float)
    if p.ndim!=3 or p.shape[1:]!=(3,3) or not len(p) or u.shape!=(3,) or v.shape!=(3,) or not np.isfinite(np.r_[p.ravel(),u,v]).all():
        raise ValueError("Finite actual carrier and text axes required")
    normal=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]).sum(0)
    facing=float(np.cross(u,v)@normal)
    if facing<=1e-12:raise ValueError("Text frame faces the back of the native carrier and would mirror its glyphs")



def _inside_triangles(points,triangles):
    points=np.asarray(points,float)
    inside=np.zeros(len(points),bool)
    for t in triangles:
        a,b,c=t;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-12:continue
        alpha=((b[1]-c[1])*(points[:,0]-c[0])+(c[0]-b[0])*(points[:,1]-c[1]))/den
        beta=((c[1]-a[1])*(points[:,0]-c[0])+(a[0]-c[0])*(points[:,1]-c[1]))/den
        inside|=(alpha>=-1e-7)&(beta>=-1e-7)&(alpha+beta<=1+1e-7)
    return inside


def ink_points(alpha,center,size,rotation_deg=0):
    a=np.asarray(alpha)
    if a.ndim!=2 or a.dtype!=np.uint8 or not a.any():raise ValueError("Actual nonempty source Alpha L8 required")
    y,x=np.nonzero(a)
    if len(x)>4000000:raise ValueError("Use actual final-resolution Alpha; ink sample budget exceeded")
    center,size=np.asarray(center,float),np.asarray(size,float)
    if center.shape!=(2,) or size.shape!=(2,) or not np.isfinite(np.r_[center,size]).all() or (size<=0).any():
        raise ValueError("Finite physical placement required")
    points=np.stack(((x+.5)/a.shape[1]-.5,.5-(y+.5)/a.shape[0]),axis=-1)*size
    angle=np.deg2rad(number(rotation_deg,"rotation",-360,360))
    matrix=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    return points@matrix.T+center


def measure_ink_fit(positions,points,origin,u_axis,v_axis,scope_polygon,
                    depth_interval_m=(-.002,.002),minimum_margin_m=0):
    p=np.asarray(positions,float);xy=np.asarray(points,float)
    origin=np.asarray(origin,float);u=np.asarray(u_axis,float);v=np.asarray(v_axis,float)
    polygon=np.asarray(scope_polygon,float);depth=np.asarray(depth_interval_m,float)
    if p.ndim!=3 or p.shape[1:]!=(3,3) or not len(p) or not np.isfinite(p).all():
        raise ValueError("Actual complete support triangles required")
    if xy.ndim!=2 or xy.shape[1]!=2 or not len(xy) or not np.isfinite(xy).all():
        raise ValueError("Actual projected ink samples required")
    if origin.shape!=(3,) or u.shape!=(3,) or v.shape!=(3,) or not np.isfinite(np.r_[origin,u,v]).all():
        raise ValueError("Finite actual carrier frame required")
    if abs(np.linalg.norm(u)-1)>1e-6 or abs(np.linalg.norm(v)-1)>1e-6 or abs(u@v)>1e-6:
        raise ValueError("Orthonormal carrier axes required")
    if polygon.ndim!=2 or polygon.shape[1]!=2 or len(polygon)<3 or not np.isfinite(polygon).all():
        raise ValueError("Independent physical panel clip polygon required")
    signs=[]
    for i in range(len(polygon)):
        a=polygon[(i+1)%len(polygon)]-polygon[i];b=polygon[(i+2)%len(polygon)]-polygon[(i+1)%len(polygon)]
        signs.append(a[0]*b[1]-a[1]*b[0])
    if not (all(s>1e-10 for s in signs) or all(s< -1e-10 for s in signs)):
        raise ValueError("Use a convex physical clip; split concave carriers explicitly")
    if depth.shape!=(2,) or not np.isfinite(depth).all() or not -.2<=depth[0]<=depth[1]<=.2:
        raise ValueError("Explicit bounded carrier relief required")
    number(minimum_margin_m,"ink edge margin",0,1)
    local=p-origin
    heights=local@np.cross(u,v)
    if heights.min()<depth[0]-1e-6 or heights.max()>depth[1]+1e-6:
        raise ValueError("Actual carrier relief exceeds documented depth range")
    projected=np.stack((local@u,local@v),axis=-1)
    support=_inside_triangles(xy,projected)
    fan=np.array([[polygon[0],polygon[i],polygon[i+1]] for i in range(1,len(polygon)-1)])
    in_scope=_inside_triangles(xy,fan)
    distances=[]
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        d=b-a;t=np.clip(((xy-a)@d)/(d@d),0,1)
        distances.append(np.linalg.norm(xy-(a+t[:,None]*d),axis=1))
    clearance=float(np.min(distances))
    unsupported=int((~support).sum());outside=int((~in_scope).sum())
    errors=[]
    if unsupported:errors.append(f"{unsupported} ink samples have no real support")
    if outside:errors.append(f"{outside} ink samples escape the independent physical panel boundary")
    if clearance<minimum_margin_m-1e-6:errors.append("Actual ink is too close to physical panel edge")
    return {"technical_pass":not errors,"errors":errors,"ink_samples":len(xy),
            "unsupported_ink_samples":unsupported,"outside_panel_samples":outside,
            "minimum_ink_clearance_m":clearance,"native_relief_m":[float(heights.min()),float(heights.max())],
            "scope_area_m2":_area(polygon),"ink_bounds_uv_m":[xy.min(0).tolist(),xy.max(0).tolist()],
            "scope":"actual ink centers on complete support plus independent panel clip; transparent canvas is excluded"}
