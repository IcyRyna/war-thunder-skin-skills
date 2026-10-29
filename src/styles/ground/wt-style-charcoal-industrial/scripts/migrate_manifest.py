"""Explicit schema-2 inspection/migration; missing evidence never becomes a pass."""
from __future__ import annotations
import argparse,copy,json
from pathlib import Path
from skill_contract import read_json

def migrate(data):
    if data.get("schema_version") not in (2,3):raise ValueError("Only schema 2/3 manifests can be inspected")
    result=copy.deepcopy(data);result["schema_version"]=3;missing=[]
    for i,c in enumerate(result.get("coverage",[])):
        if not c.get("native_resource"):missing.append(f"coverage[{i}].native_resource")
        missing.append(f"coverage[{i}]: verify geometry source_face_ids against actual model")
    for i,r in enumerate(result.get("runtime_textures",[])):
        if not r.get("native_resources"):missing.append(f"runtime_textures[{i}].native_resources from actual BLK")
    for i,m in enumerate(result.get("materials",[])):
        if m.get("state")=="paint" and not m.get("surfaces"):missing.append(f"materials[{i}].surfaces and C/N sample surface_id")
    for i,r in enumerate(result.get("channel_repairs",[])):
        for channel,d in r.get("decisions",{}).items():
            if d.get("action")!="absent" and not d.get("runtime_texture_id"):
                missing.append(f"channel_repairs[{i}].decisions.{channel}.runtime_texture_id")
    for i,row in enumerate(result.get("part_layouts",{}).get("roof_warning",{}).get("placement_checks",[])):
        if not row.get("visibility",{}).get("scene"):missing.append(f"roof placement[{i}].visibility.scene and recomputed receipt")
        if "contains_text" not in row:missing.append(f"roof placement[{i}].contains_text and bound core text region when applicable")
    for i,_ in enumerate(result.get("sensitive_equipment",[])):
        missing.append(f"sensitive_equipment[{i}]: verify classification model/unit/source faces")
    result["migration"]={"source_schema":data["schema_version"],"status":"requires_evidence","missing":missing}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("manifest",type=Path);p.add_argument("--out",type=Path)
    a=p.parse_args();result=migrate(read_json(a.manifest))
    if a.out:
        with a.out.open("x",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result["migration"],ensure_ascii=False,indent=2))
if __name__=="__main__":main()
