"""Native source extraction and face/resource identity for schema 3."""
from __future__ import annotations
import json
from pathlib import Path
import struct
import numpy as np
from skill_contract import checked_file, read_json, require_text

def source_geometry(path):
    path=Path(path)
    if path.suffix.lower()==".npz":
        with np.load(path,allow_pickle=False) as z:
            p=np.asarray(z["positions"],float); uv=np.asarray(z["uvs"],float)
            n=len(p)
            result={"positions":p,"uvs":uv,
                    "materials":np.asarray(z["materials"]).astype(str) if "materials" in z else np.full(n,"plate"),
                    "nodes":np.asarray(z["nodes"]).astype(str) if "nodes" in z else np.full(n,"plate")}
            for role in ("normal","ao"):
                result["uvs_"+role]=np.asarray(z["uvs_"+role],float) if "uvs_"+role in z else uv
    elif path.suffix.lower()==".obj":
        vertices=[];texcoords=[];positions=[];uvs=[];materials=[];nodes=[]
        material=None;node="root"
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                fields=line.split()
                if not fields:continue
                if fields[0]=="v":vertices.append([float(x) for x in fields[1:4]])
                elif fields[0]=="vt":texcoords.append([float(x) for x in fields[1:3]])
                elif fields[0] in ("o","g"):node=" ".join(fields[1:])
                elif fields[0]=="usemtl":material=" ".join(fields[1:])
                elif fields[0]=="f":
                    if len(fields)!=4 or not material:raise ValueError("Native OBJ must retain triangulation and material identity")
                    pp=[];tt=[]
                    for token in fields[1:]:
                        indices=token.split("/")
                        if len(indices)<2 or not indices[1]:raise ValueError("Native face has no texture coordinates")
                        vi,ti=int(indices[0]),int(indices[1])
                        if vi==0 or ti==0:raise ValueError("Invalid zero OBJ index")
                        pp.append(vertices[vi-1 if vi>0 else vi]);tt.append(texcoords[ti-1 if ti>0 else ti])
                    positions.append(pp);uvs.append(tt);materials.append(material);nodes.append(node)
        result={"positions":np.asarray(positions,float),"uvs":np.asarray(uvs,float),
                "materials":np.asarray(materials),"nodes":np.asarray(nodes)}
        result.update(uvs_normal=result["uvs"],uvs_ao=result["uvs"])
    elif path.suffix.lower()==".glb":
        result=_glb(path)
    else:raise ValueError("Native validation requires an actual OBJ, GLB or geometry NPZ; export .blend explicitly")
    p=result["positions"];n=len(p)
    if p.shape!=(n,3,3) or not n or not np.isfinite(p).all():raise ValueError("Invalid native source positions")
    for key in ("uvs","uvs_normal","uvs_ao"):
        if result[key].shape!=(n,3,2) or not np.isfinite(result[key]).all():raise ValueError("Invalid native UV channel")
    if result["materials"].shape!=(n,) or result["nodes"].shape!=(n,):raise ValueError("Native material/node inventory is incomplete")
    return result

def _glb(path):
    raw=path.read_bytes()
    if len(raw)<20 or raw[:4]!=b"glTF" or struct.unpack_from("<II",raw,4)!=(2,len(raw)):
        raise ValueError("Invalid GLB container")
    chunks={};offset=12
    while offset<len(raw):
        size,kind=struct.unpack_from("<II",raw,offset);offset+=8
        if offset+size>len(raw) or kind in chunks:raise ValueError("Invalid GLB chunks")
        chunks[kind]=raw[offset:offset+size];offset+=size
    doc=json.loads(chunks[0x4e4f534a]);blob=chunks[0x004e4942]
    def accessor(index):
        a=doc["accessors"][index]
        if "sparse" in a or a.get("normalized"):raise ValueError("Sparse/normalized native accessors require explicit export")
        v=doc["bufferViews"][a["bufferView"]]
        if v.get("buffer",0)!=0:raise ValueError("External GLB buffer unsupported")
        dt=np.dtype({5126:"<f4",5125:"<u4",5123:"<u2",5121:"u1"}[a["componentType"]])
        width={"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4}[a["type"]]
        start=v.get("byteOffset",0)+a.get("byteOffset",0);stride=v.get("byteStride",width*dt.itemsize)
        if a["count"] and start+(a["count"]-1)*stride+width*dt.itemsize>v.get("byteOffset",0)+v["byteLength"]:
            raise ValueError("GLB accessor exceeds its buffer view")
        return np.ndarray((a["count"],width),dt,blob,start,strides=(stride,dt.itemsize)).copy()
    outputs={key:[] for key in ("positions","uvs","uvs_normal","uvs_ao","materials","nodes")};seen=set()
    def visit(index,parent):
        if index in seen:raise ValueError("Repeated/cyclic native scene node")
        seen.add(index);node=doc["nodes"][index]
        if "skin" in node:raise ValueError("Skinned geometry needs a frozen evaluated pose")
        if "matrix" in node:m=np.asarray(node["matrix"],float).reshape(4,4).T
        else:
            x,y,z,w=node.get("rotation",[0,0,0,1])
            r=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
            m=np.eye(4);m[:3,:3]=r@np.diag(node.get("scale",[1,1,1]));m[:3,3]=node.get("translation",[0,0,0])
        matrix=parent@m
        if "mesh" in node:
            for pi,pr in enumerate(doc["meshes"][node["mesh"]]["primitives"]):
                if pr.get("mode",4)!=4 or "targets" in pr:raise ValueError("Freeze nontriangle/morphed geometry before audit")
                a=pr["attributes"];p=accessor(a["POSITION"]);ix=accessor(pr["indices"]).ravel() if "indices" in pr else np.arange(len(p))
                tris=ix.reshape(-1,3);p=(np.c_[p,np.ones(len(p))]@matrix.T)[:,:3][tris]
                material=doc["materials"][pr["material"]];baseuv=accessor(a["TEXCOORD_0"])[tris]
                outputs["positions"].append(p);outputs["uvs"].append(baseuv)
                for role,field in (("normal","normalTexture"),("ao","occlusionTexture")):
                    tex=material.get(field,{});channel=tex.get("texCoord",0)
                    if tex.get("extensions"):raise ValueError("Native UV texture transforms need explicit export")
                    outputs["uvs_"+role].append(accessor(a["TEXCOORD_"+str(channel)])[tris])
                outputs["materials"].extend([material.get("name",str(pr["material"]))]*len(p))
                outputs["nodes"].extend([str(index)+":"+node.get("name","node")]*len(p))
        for child in node.get("children",[]):visit(child,matrix)
    for index in doc["scenes"][doc.get("scene",0)]["nodes"]:visit(index,np.eye(4))
    return {key:np.asarray(value) if key in ("materials","nodes") else np.concatenate(value) for key,value in outputs.items()}

class NativeContext:
    def __init__(self,root,data):
        self.root=Path(root);self.data=data
        self.source=source_geometry(checked_file(root,data["model"],"native source model"))
        bindings=read_json(checked_file(root,data["bindings"],"native material inventory"))
        self.bindings=bindings
        if bindings.get("unit_id")!=data["unit_id"] or bindings.get("model_sha256")!=data["model"]["sha256"]:
            raise ValueError("Native inventory belongs to a different model/unit")
        self.resources={}
        for row in bindings.get("resources",[]):
            key=row.get("resource","").rstrip("*").casefold()
            if not key or key in self.resources or row.get("role") not in {"color","normal","ao"}:
                raise ValueError("Invalid native resource inventory")
            users=row.get("users")
            if not isinstance(users,list) or not users or len(set(users))!=len(users):raise ValueError("Native users must be unique material names")
            available=set(self.source["materials"].tolist())
            if not set(users)<=available:raise ValueError("Native resource user is absent from actual source model")
            ids=np.flatnonzero(np.isin(self.source["materials"],users))
            if not len(ids):raise ValueError("Native resource has no real faces")
            self.resources[key]={**row,"face_ids":ids}
        self.claims={}
    def geometry(self,claim,role="color"):
        name=require_text(claim.get("native_resource"),"native resource").rstrip("*").casefold()
        slot=self.resources.get(name)
        if slot is None or slot["role"]!=role:raise ValueError("Coverage resource role mismatch")
        with np.load(checked_file(self.root,claim["geometry"],"complete native coverage"),allow_pickle=False) as z:
            if "source_face_ids" not in z:raise ValueError("Coverage needs stable source_face_ids")
            ids=np.asarray(z["source_face_ids"])
            p=np.asarray(z["positions"],float);uv=np.asarray(z["uvs"],float)
        if ids.dtype.kind not in "iu" or ids.ndim!=1 or not np.array_equal(ids,slot["face_ids"]):
            raise ValueError("Coverage omits/reorders native users or has duplicate/foreign faces")
        key="uvs" if role=="color" else "uvs_"+role
        if not np.array_equal(p,self.source["positions"][ids]) or not np.array_equal(uv,self.source[key][ids]):
            raise ValueError("Coverage positions/UV differ from actual native resource")
        return ids,p,uv
    def validate_claims(self,coverage):
        for name,claim in coverage.items():
            ids,p,uv=self.geometry(claim)
            self.claims[name]=(ids,p,uv)
        return {"source_faces":len(self.source["positions"]),"resources":len(self.resources),"claims":len(coverage)}
    def selected(self,coverage_id,group_ids):
        claim=next((c for c in self.data["coverage"] if c["id"]==coverage_id),None)
        if claim is None or coverage_id not in self.claims:raise ValueError("Unknown verified native coverage")
        groups={g["id"]:g for g in claim["face_groups"]}
        if not isinstance(group_ids,list) or not group_ids or len(set(group_ids))!=len(group_ids) or not set(group_ids)<=set(groups):
            raise ValueError("Explicit native surface groups required")
        ids=self.claims[coverage_id][0]
        local=sorted({f for g in group_ids for f in groups[g]["faces"]})
        if any(type(f) is not int or f<0 or f>=len(ids) for f in local):raise ValueError("Invalid surface face")
        return ids[local]
    def validate_scope_contracts(self,coverage):
        from source_bindings import audit_source_bindings
        self.source_binding_report=audit_source_bindings(self.root,self.bindings,set(self.source['materials'].tolist()))
        reports=[]
        for key,claim in coverage.items():
            frozen=read_json(checked_file(self.root,claim.get('scope_contract'),'frozen intended native scope'))
            for field,expected in [('model_sha256',self.data['model']['sha256']),('native_resource',claim['native_resource']),
                                   ('layer_role',claim['layer_role']),('mode',claim['mode'])]:
                if frozen.get(field)!=expected:raise ValueError('Intended native scope changed '+field+': '+key)
            require_text(frozen.get('reason'),'independent native scope basis')
            ids=self.selected(key,claim['target_groups']).tolist()
            expected=frozen.get('target_source_faces')
            if not isinstance(expected,list) or not expected or any(type(x) is not int for x in expected) or len(set(expected))!=len(expected):
                raise ValueError('Frozen native scope needs unique complete source face IDs')
            if sorted(expected)!=sorted(ids):raise ValueError('Target groups shrink or change the frozen intended native surface: '+key)
            reports.append({'coverage':key,'source_faces':len(ids),'mode':claim['mode'],'scope_contract_sha256':claim['scope_contract']['sha256']})
        return reports
    def mask(self,face_ids,resource,shape):
        from surface_coverage import _raster
        slot=self.resources.get(resource.rstrip("*").casefold())
        if slot is None or not set(map(int,face_ids))<=set(map(int,slot["face_ids"])):
            raise ValueError("Material/component faces do not belong to the native resource")
        key="uvs" if slot["role"]=="color" else "uvs_"+slot["role"]
        ids=slot["face_ids"];target=np.isin(ids,face_ids)
        zeros=np.zeros(shape,bool)
        p=self.source["positions"][ids]
        renderable=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)>=1e-12
        _,requested,_,samples,_=_raster(self.source[key][ids],zeros,target,np.zeros(len(ids),bool),renderable)
        if np.any(target&renderable&(samples==0)):raise ValueError("Material/component has unsampled native faces")
        return requested



def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("manifest",type=Path);p.add_argument("--resource",required=True);p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();data=read_json(a.manifest);native=NativeContext(a.manifest.parent,data)
    slot=native.resources[a.resource.rstrip("*").casefold()];ids=slot["face_ids"]
    uv="uvs" if slot["role"]=="color" else "uvs_"+slot["role"]
    with a.out.open("xb") as f:np.savez_compressed(f,positions=native.source["positions"][ids],uvs=native.source[uv][ids],source_face_ids=ids)
    print(json.dumps({"resource":a.resource,"native_faces":len(ids),"source_model_sha256":data["model"]["sha256"],"output":str(a.out)}))
if __name__=="__main__":main()
