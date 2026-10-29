"""Locate the independent material pack without putting image assets in the Skill."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

PACK_ID = 'wt-charcoal-industrial-assets'
SKILL_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_KEY = 'WT_CHARCOAL_ASSETS'

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def inside(root,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Asset pack member must be a relative POSIX path')
    name=PurePosixPath(relative)
    if name.is_absolute() or any(x in ('','..','.') for x in relative.split('/')):
        raise ValueError('Asset pack member escapes its package')
    path=(root/relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Asset pack member escapes its package or is not a file')
    return path

def metadata(root,skill_root=SKILL_ROOT):
    root=Path(root).expanduser().resolve(strict=True)
    with (root/'ASSET_PACK.json').open(encoding='utf-8-sig') as stream:record=json.load(stream)
    if record.get('schema_version')!=1 or record.get('asset_pack_id')!=PACK_ID:
        raise ValueError('This is not the charcoal industrial asset pack')
    identity=json.loads((Path(skill_root)/'VERSION.json').read_text(encoding='utf-8-sig'))
    if identity['version'] not in record.get('compatible_skill_versions',[]):
        raise ValueError('Asset pack does not declare compatibility with Skill '+identity['version'])
    if record.get('skill_id')!=identity['skill_id']:
        raise ValueError('Asset pack belongs to another Skill')
    catalog=inside(root,record['catalog']['file'])
    if digest(catalog)!=record['catalog']['sha256']:
        raise ValueError('Independent asset catalog hash mismatch')
    return root,record

def locate(path=None,*,skill_root=SKILL_ROOT):
    explicit=path if path is not None else os.environ.get(ENVIRONMENT_KEY)
    if explicit:
        return metadata(explicit,skill_root)
    candidates=[Path(skill_root).resolve().parent/PACK_ID,Path.cwd()/PACK_ID]
    found=[]
    for candidate in candidates:
        if (candidate/'ASSET_PACK.json').is_file():
            candidate=candidate.resolve()
            if candidate not in found:found.append(candidate)
    if not found:
        raise FileNotFoundError('Independent asset pack is missing. Extract '+PACK_ID+
            ' beside the Skill, or set '+ENVIRONMENT_KEY+' to its directory. The Skill does not bundle production images.')
    if len(found)>1:
        raise ValueError('Multiple independent asset packs found; choose one with '+ENVIRONMENT_KEY)
    return metadata(found[0],skill_root)

def reference(value,*,pack=None,skill_root=SKILL_ROOT):
    if not isinstance(value,str) or not value.startswith('asset-pack:'):
        raise ValueError('Expected an asset-pack: reference')
    root,_=locate(pack,skill_root=skill_root)
    return inside(root,value.removeprefix('asset-pack:'))

def catalog_file(path=None,*,skill_root=SKILL_ROOT):
    root,record=locate(path,skill_root=skill_root)
    return inside(root,record['catalog']['file'])

def verify(path=None,*,skill_root=SKILL_ROOT):
    root,record=locate(path,skill_root=skill_root)
    rows=record.get('files')
    if not isinstance(rows,list) or not rows:raise ValueError('Asset pack has no frozen file list')
    names=[r['file'] for r in rows]
    if len(set(n.casefold() for n in names))!=len(names):raise ValueError('Duplicate asset pack members')
    actual=set()
    for file in root.rglob('*'):
        if file.is_symlink() or getattr(file.stat(),'st_file_attributes',0)&0x400:
            raise ValueError('Asset pack contains a link/reparse point')
        if file.is_file() and file.name!='ASSET_PACK.json':actual.add(file.relative_to(root).as_posix())
    if actual!=set(names):raise ValueError('Asset pack file set differs from its manifest')
    for row in rows:
        file=inside(root,row['file'])
        if file.stat().st_size!=row['bytes'] or digest(file)!=row['sha256']:
            raise ValueError('Asset pack content changed: '+row['file'])
    return {'passed':True,'asset_pack_id':PACK_ID,'version':record['version'],
            'files_checked':len(rows),'catalog':str(inside(root,record['catalog']['file']))}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['locate','verify'])
    parser.add_argument('--assets',type=Path)
    args=parser.parse_args()
    if args.command=='verify':result=verify(args.assets)
    else:
        root,data=locate(args.assets)
        result={'asset_pack_id':PACK_ID,'version':data['version'],'root':str(root),'catalog':str(inside(root,data['catalog']['file']))}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
