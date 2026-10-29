"""Identify the selected livery by active BLK targets, never by cached DDS presence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
from ground_dds import _lex, _string, _relative, rewrite_blk
from skill_contract import sha


def _mappings(text):
    tokens=_lex(text);targets={}
    for i,token in enumerate(tokens):
        if token=="to:t":
            if tokens[i+1:i+2]!=["="] or i+2>=len(tokens):raise ValueError("Malformed actual BLK target")
            relative=_relative(_string(tokens[i+2]),"actual BLK target")
            targets[relative.as_posix().casefold()]={"file":relative,"output":relative,"role":"unclassified"}
    _,mappings=rewrite_blk(text,targets)
    return mappings


def _finish(blk_hash,mappings,targets,source):
    resources={}
    for mapping in mappings:
        key=mapping["resource"].rstrip("*").casefold()
        if key in resources:raise ValueError("Conflicting logical resource identity")
        resources[key]={"target":mapping["target"],**targets[mapping["target"].casefold()]}
    frozen={"blk_sha256":blk_hash,"resources":resources}
    fingerprint=hashlib.sha256(json.dumps(frozen,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"source":source,**frozen,"active_target_count":len(targets),
            "active_resource_count":len(resources),"snapshot_sha256":fingerprint}


def snapshot_folder(blk_path):
    blk=Path(blk_path).resolve(strict=True);root=blk.parent
    mappings=_mappings(blk.read_text(encoding="utf-8-sig"))
    targets={}
    for mapping in mappings:
        relative=_relative(mapping["target"],"active runtime target");path=(root/relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():raise ValueError("Actual BLK target escapes skin folder")
        targets[relative.as_posix().casefold()]={"sha256":sha(path),"bytes":path.stat().st_size}
    report=_finish(sha(blk),mappings,targets,str(blk))
    all_files=[p for p in root.rglob("*.dds") if p.is_file()]
    report["unbound_dds_files"]=sum(p.relative_to(root).as_posix().casefold() not in targets for p in all_files)
    return report


def snapshot_zip(archive,blk_member=None):
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(n.casefold() for n in names)):raise ValueError("Duplicate/case-colliding archive members")
        blks=[name for name in names if name.lower().endswith(".blk")]
        if blk_member is None:
            if len(blks)!=1:raise ValueError("Explicit vehicle BLK member required")
            blk_member=blks[0]
        if blk_member not in blks:raise ValueError("Vehicle BLK absent from archive")
        raw=z.read(blk_member);mappings=_mappings(raw.decode("utf-8-sig"));base=PurePosixPath(blk_member).parent
        targets={}
        for mapping in mappings:
            relative=_relative(mapping["target"],"archive active target").as_posix()
            member=(base/relative).as_posix()
            if member not in names:raise ValueError("Mapped archive texture is missing")
            digest=hashlib.sha256()
            with z.open(member) as stream:
                for chunk in iter(lambda:stream.read(1048576),b""):digest.update(chunk)
            targets[relative.casefold()]={"sha256":digest.hexdigest(),"bytes":z.getinfo(member).file_size}
        return _finish(hashlib.sha256(raw).hexdigest(),mappings,targets,str(archive)+"::"+blk_member)


def compare_snapshots(left,right):
    a,b=left["resources"],right["resources"]
    changed=[key for key in sorted(set(a)&set(b)) if a[key]["sha256"]!=b[key]["sha256"]]
    added=sorted(set(b)-set(a));removed=sorted(set(a)-set(b))
    return {"same_active_content":not(changed or added or removed),
            "same_blk_bytes":left["blk_sha256"]==right["blk_sha256"],
            "changed_resources":changed,"added_resources":added,"removed_resources":removed,
            "left_targets":left["active_target_count"],"right_targets":right["active_target_count"],
            "rule":"same-named obsolete files in a folder are not evidence of the active version"}



def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    folder=sub.add_parser("folder");folder.add_argument("blk",type=Path);folder.add_argument("--out",type=Path)
    archive=sub.add_parser("archive");archive.add_argument("zip",type=Path);archive.add_argument("--blk-member");archive.add_argument("--out",type=Path)
    compare=sub.add_parser("compare");compare.add_argument("left",type=Path);compare.add_argument("right",type=Path);compare.add_argument("--out",type=Path)
    args=parser.parse_args()
    if args.command=="folder":report=snapshot_folder(args.blk)
    elif args.command=="archive":report=snapshot_zip(args.zip,args.blk_member)
    else:
        report=compare_snapshots(json.loads(args.left.read_text(encoding="utf-8-sig")),json.loads(args.right.read_text(encoding="utf-8-sig")))
    if args.out:
        with args.out.open("x",encoding="utf-8") as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
