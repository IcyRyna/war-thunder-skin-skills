"""Resolve indexed pixels and provenance with explicit path bases and intent."""
from pathlib import Path
import json,hashlib
from style_quality import authorize

def resolve_asset(catalog_file,asset_id,kind,intent='style_transfer',target_profile=None):
 if catalog_file is None:
  from asset_pack import catalog_file as find_catalog
  catalog_file=find_catalog()
 catalog_file=Path(catalog_file).resolve();catalog=json.loads(catalog_file.read_bytes());root=catalog_file.parent.parent if catalog.get('asset_path_base','skill_root')=='skill_root' else catalog_file.parent
 rows=[r for r in catalog['assets'] if r['id']==asset_id]
 if len(rows)!=1:raise ValueError('Asset identity must be unique')
 r=rows[0]
 if r['kind']!=kind:raise ValueError('Requested purpose differs from the indexed asset kind')
 p=(root/r['file']).resolve()
 if not p.is_relative_to(root) or not p.is_file():raise ValueError('Indexed asset escapes its package or is missing')
 with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 if digest!=r['sha256']:raise ValueError('Indexed asset bytes changed')
 evidence_root=root if catalog.get('evidence_path_base')=='skill_root' else catalog_file.parent
 authorize(r,intent,evidence_root,target_profile)
 return p,r
