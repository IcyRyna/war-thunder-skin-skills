"""Verify the Skill independently; optionally verify its separate asset pack."""
from pathlib import Path
import argparse,hashlib,json

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def verify(root):
    root=Path(root).resolve(strict=True)
    lock=json.loads((root/'FILE_LOCK.json').read_text('utf8'))
    identity=json.loads((root/'VERSION.json').read_text('utf8'))
    if lock.get('skill_id')!=identity['skill_id'] or lock.get('version')!=identity['version']:
        raise ValueError('Skill release identity mismatch')
    entries=lock.get('files',[]);names=[r['file'] for r in entries]
    if not entries or len({n.casefold() for n in names})!=len(names):raise ValueError('Invalid frozen Skill file list')
    actual={}
    for path in root.rglob('*'):
        if path.is_symlink() or getattr(path.stat(),'st_file_attributes',0)&0x400:raise ValueError('Unexpected Skill link/reparse point')
        if path.is_file() and path.name!='FILE_LOCK.json':actual[path.relative_to(root).as_posix()]=path
    if set(actual)!=set(names):raise ValueError('Skill file set differs from frozen release')
    for row in entries:
        path=actual[row['file']]
        if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise ValueError('Skill file changed: '+row['file'])
    media={'.png','.jpg','.jpeg','.webp','.dds','.tga','.psd','.cmps','.blend'}
    if any(p.suffix.lower() in media for p in actual.values()) or (root/'assets').exists():
        raise ValueError('Production/research media belongs in the separate asset pack, not the Skill')
    return {'passed':True,'skill_id':identity['skill_id'],'version':identity['version'],'files_checked':len(entries),'material_assets_embedded':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--assets',type=Path)
    args=parser.parse_args();result={'skill':verify(Path(__file__).resolve().parents[1])}
    if args.assets:
        from asset_pack import verify as verify_assets
        result['assets']=verify_assets(args.assets)
    else:result['assets']={'status':'separate; not requested'}
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
