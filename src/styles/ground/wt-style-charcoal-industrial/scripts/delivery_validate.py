"""Verify a game ZIP against the final reviewed runtime, not just a byte budget."""
import argparse
import json
from pathlib import Path
from skill_contract import read_json
from vehicle_review import validate_manifest
from runtime_validation import audit_delivery
from production_tools import audit_tools


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--zip",type=Path,required=True)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    final=validate_manifest(args.manifest,"final")
    data=read_json(args.manifest)
    execution=audit_tools(args.manifest.resolve().parent,data)
    report=audit_delivery(args.manifest.resolve().parent,data,args.zip)
    report["production_tools"]=execution
    report["manifest_sha256"]=final["manifest_sha256"]
    report["visual_approval"]="not inferred"
    if args.out:
        with args.out.open("x",encoding="utf-8") as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
