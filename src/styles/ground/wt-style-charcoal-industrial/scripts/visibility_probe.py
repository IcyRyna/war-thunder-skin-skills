"""Deterministic visibility from the complete posed native scene, not reported counts."""
from __future__ import annotations
import hashlib,json
import numpy as np
from numba import njit
from PIL import Image
from skill_contract import checked_file,read_json,load_mask,number

def _bvh(triangles):
    lo=triangles.min(1);hi=triangles.max(1);centers=(lo+hi)*.5
    bounds=[];links=[];order=[]
    def build(ids):
        index=len(bounds);bounds.append([lo[ids].min(0),hi[ids].max(0)]);links.append([-1,-1,0,0])
        if len(ids)<=12:
            offset=len(order);order.extend(ids.tolist());links[index]=[-1,-1,offset,len(ids)]
        else:
            axis=int(np.argmax(np.ptp(centers[ids],axis=0)));sorted_ids=ids[np.argsort(centers[ids,axis],kind="stable")]
            mid=len(ids)//2;left=build(sorted_ids[:mid]);right=build(sorted_ids[mid:]);links[index]=[left,right,0,0]
        return index
    if not len(triangles):raise ValueError("Empty visible native scene")
    build(np.arange(len(triangles)))
    return np.asarray(bounds),np.asarray(links,np.int64),np.asarray(order,np.int64)

@njit(cache=False)
def _rays_bvh(points,triangles,carrier,origin,direction,perspective,bounds,links,order):
    visible=np.zeros(len(points),np.bool_);blockers=np.full(len(points),-1,np.int64)
    distance_bound=2*np.sqrt(((bounds[0,1]-bounds[0,0])**2).sum())+1
    for j in range(len(points)):
        target=points[j]
        if perspective:
            eye=origin;delta=target-eye;distance=np.sqrt((delta*delta).sum())
            if distance<1e-9:continue
            ray=delta/distance
        else:
            distance=distance_bound;eye=target-direction*distance;ray=direction
        best=distance+1e-5;winner=-1
        stack=np.empty(128,np.int64);stack[0]=0;length=1
        while length:
            length-=1;node=stack[length];near=0.;far=best;hit=True
            for axis in range(3):
                if abs(ray[axis])<1e-15:
                    if eye[axis]<bounds[node,0,axis]-1e-8 or eye[axis]>bounds[node,1,axis]+1e-8:hit=False;break
                else:
                    a=(bounds[node,0,axis]-eye[axis])/ray[axis];b=(bounds[node,1,axis]-eye[axis])/ray[axis]
                    near=max(near,min(a,b)-1e-8);far=min(far,max(a,b)+1e-8)
                    if near>far:hit=False;break
            if not hit:continue
            left,right,offset,count=links[node]
            if left>=0:
                stack[length]=left;stack[length+1]=right;length+=2;continue
            for entry in range(offset,offset+count):
                i=order[entry];a,b,c=triangles[i];e1=b-a;e2=c-a
                h=np.cross(ray,e2);det=np.dot(e1,h)
                if abs(det)<1e-12:continue
                f=1./det;delta=eye-a;u=f*np.dot(delta,h)
                if u < -1e-8 or u>1.+1e-8:continue
                q=np.cross(delta,e1);v=f*np.dot(ray,q)
                if v < -1e-8 or u+v>1.+1e-8:continue
                t=f*np.dot(e2,q)
                if t>=0 and t<best:best=t;winner=i
        if winner>=0 and carrier[winner] and abs(best-distance)<1e-4:visible[j]=True
        elif winner>=0:blockers[j]=winner
    return visible,blockers

def _rays(points,triangles,carrier,origin,direction,perspective):
    return _rays_bvh(points,triangles,carrier,origin,direction,perspective,*_bvh(triangles))

def scene_geometry(root,row,native):
    spec=row.get("visibility",{}).get("scene")
    scene=read_json(checked_file(root,spec,"frozen visibility scene"))
    if scene.get("schema_version")!=1 or scene.get("model_sha256")!=native.data["model"]["sha256"]:
        raise ValueError("Visibility scene model identity mismatch")
    if scene.get("attachment_state")!=native.data["attachment_state"]:
        raise ValueError("Visibility attachment state differs from current vehicle")
    for field in ("pose_id","lod"):
        if not isinstance(scene.get(field),str) or not scene[field]:raise ValueError("Explicit visibility pose and LOD required")
    nodes=scene.get("nodes",[]);by_id={r.get("id"):r for r in nodes}
    source_nodes=set(native.source["nodes"].tolist())
    if len(by_id)!=len(nodes) or set(by_id)!=source_nodes:raise ValueError("Scene must account for every native node")
    positions=native.source["positions"].copy();visible=np.zeros(len(positions),bool)
    for key,node in by_id.items():
        matrix=np.asarray(node.get("matrix"),float)
        if matrix.shape!=(4,4) or not np.isfinite(matrix).all() or not np.array_equal(matrix[3],[0,0,0,1]) or abs(np.linalg.det(matrix[:3,:3]))<1e-12:
            raise ValueError("Invalid frozen scene node transform")
        if type(node.get("visible")) is not bool:raise ValueError("Explicit scene visibility required")
        selected=native.source["nodes"]==key
        positions[selected]=positions[selected]@matrix[:3,:3].T+matrix[:3,3]
        visible[selected]=node["visible"]
    with np.load(checked_file(root,row["geometry"],"visibility carrier"),allow_pickle=False) as g:
        if "source_face_ids" not in g:raise ValueError("Visibility carrier needs source face identity")
        ids=np.asarray(g["source_face_ids"])
        if ids.dtype.kind not in "iu" or ids.ndim!=1 or len(set(ids.tolist()))!=len(ids) or np.any(ids<0) or np.any(ids>=len(positions)):
            raise ValueError("Invalid visibility source face IDs")
        if not np.array_equal(g["positions"],native.source["positions"][ids]):raise ValueError("Visibility carrier differs from actual source")
    return scene,positions,visible,ids

def compute_visibility(root,row,native,*,verify_receipt=True):
    from layout_fit import ink_points,_inside_triangles
    scene,positions,active,ids=scene_geometry(root,row,native)
    faces=np.asarray(row["faces"],int);selected_ids=ids[faces]
    if not active[selected_ids].all():raise ValueError("Warning carrier is hidden in actual scene")
    if row["mode"]!="actual_ink":
        raise ValueError("Visibility requires a bound actual graphic, including solid panels")
    with Image.open(checked_file(root,row["asset"],"visible graphic")) as im:alpha=np.array(im.convert("RGBA"))[...,3]
    xy=ink_points(alpha,row["center_uv_m"],row["graphic_size_m"],row.get("rotation_deg",0))
    frame=row["frame"];origin=np.array(frame["origin"]);u=np.array(frame["u"]);v=np.array(frame["v"]);normal=np.cross(u,v)
    triangles=positions[selected_ids];local=triangles-origin
    projected=np.stack((local@u,local@v),axis=-1);height=local@normal
    z=np.full(len(xy),np.nan)
    for tri,h in zip(projected,height):
        den=(tri[1,1]-tri[2,1])*(tri[0,0]-tri[2,0])+(tri[2,0]-tri[1,0])*(tri[0,1]-tri[2,1])
        if abs(den)<1e-12:continue
        a=((tri[1,1]-tri[2,1])*(xy[:,0]-tri[2,0])+(tri[2,0]-tri[1,0])*(xy[:,1]-tri[2,1]))/den
        b=((tri[2,1]-tri[0,1])*(xy[:,0]-tri[2,0])+(tri[0,0]-tri[2,0])*(xy[:,1]-tri[2,1]))/den
        hit=(a>=-1e-7)&(b>=-1e-7)&(a+b<=1+1e-7)
        val=a*h[0]+b*h[1]+(1-a-b)*h[2]
        replace=hit&(np.isnan(z)|(val>z));z[replace]=val[replace]
    if np.isnan(z).any():raise ValueError("Visibility ink has no real posed support")
    points=origin+xy[:,0,None]*u+xy[:,1,None]*v+z[:,None]*normal
    cam=scene.get("camera",{});kind=cam.get("kind")
    if kind not in {"orthographic","perspective"}:raise ValueError("Explicit camera kind required")
    direction=np.asarray(cam.get("direction",[0,0,-1]),float);eye=np.asarray(cam.get("position",[0,0,0]),float)
    if direction.shape!=(3,) or eye.shape!=(3,) or not np.isfinite(np.r_[direction,eye]).all() or np.linalg.norm(direction)<1e-12:
        raise ValueError("Invalid visibility camera")
    direction/=np.linalg.norm(direction)
    active_ids=np.flatnonzero(active);carrier=np.isin(active_ids,selected_ids)
    visible,blockers=_rays(points,positions[active],carrier,eye,direction,kind=="perspective")
    if kind=="perspective":
        up=np.asarray(cam.get("up"),float)
        if up.shape!=(3,) or not np.isfinite(up).all() or np.linalg.norm(np.cross(direction,up))<1e-9:
            raise ValueError("Perspective camera needs a valid up vector")
        right=np.cross(direction,up);right/=np.linalg.norm(right);up=np.cross(right,direction)
        fov=number(cam.get("vertical_fov_deg"),"camera FOV",1,179);aspect=number(cam.get("aspect"),"camera aspect",.1,10)
        delta=points-eye;depth=delta@direction;half=depth*np.tan(np.deg2rad(fov/2))
        visible&=(depth>0)&(np.abs(delta@up)<=half)&(np.abs(delta@right)<=half*aspect)
    text_count=0;text_visible=0
    contains=row.get("contains_text")
    if type(contains) is not bool:raise ValueError("Declare whether the actual warning contains text")
    if contains:
        mask=load_mask(root,row.get("core_text_mask"),"core text bound to source image",alpha.shape)
        if not mask.any() or np.any(mask&(alpha==0)):raise ValueError("Core text mask must select actual source ink")
        proof=read_json(checked_file(root,row.get("text_region_evidence"),"core text identity"))
        if proof.get("asset_sha256")!=row["asset"]["sha256"] or proof.get("mask_sha256")!=row["core_text_mask"]["sha256"]:
            raise ValueError("Core text region differs from reviewed source")
        text=mask[alpha>0];text_count=int(text.sum());text_visible=int(visible[text].sum())
    result={"ink_samples":len(xy),"visible_ink_samples":int(visible.sum()),
            "text_samples":text_count,"visible_text_samples":text_visible,
            "scene_sha256":row["visibility"]["scene"]["sha256"],
            "blocked_source_faces":np.unique(active_ids[blockers[blockers>=0]]).tolist()}
    if verify_receipt:
        reported=read_json(checked_file(root,row["visibility"]["probe"],"visibility measurement receipt"))
        for key in ("ink_samples","visible_ink_samples","text_samples","visible_text_samples","scene_sha256"):
            if reported.get(key)!=result[key]:raise ValueError("Visibility receipt differs from recomputed scene: "+key)
    result.update(source_model_sha256=native.data["model"]["sha256"],geometry_sha256=row["geometry"]["sha256"],asset_sha256=row["asset"]["sha256"],frame=row["frame"],center_uv_m=row["center_uv_m"],graphic_size_m=row["graphic_size_m"],rotation_deg=row.get("rotation_deg",0))
    return result



def main():
    import argparse
    from pathlib import Path
    from native_inventory import NativeContext
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("manifest",type=Path);p.add_argument("--instance",required=True);p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();data=read_json(a.manifest);native=NativeContext(a.manifest.parent,data)
    rows=[r for r in data["part_layouts"]["roof_warning"]["placement_checks"] if r["id"]==a.instance]
    if len(rows)!=1:raise ValueError("Visibility instance is missing or ambiguous")
    result=compute_visibility(a.manifest.parent,rows[0],native,verify_receipt=False)
    with a.out.open("x",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!="blocked_source_faces"},ensure_ascii=False))
if __name__=="__main__":main()
