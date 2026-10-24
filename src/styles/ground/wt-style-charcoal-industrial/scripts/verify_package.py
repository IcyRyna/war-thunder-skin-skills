"""Check the candidate's exact file set and SHA-256 lock from any working directory."""
from pathlib import Path
import hashlib
import json

def main():
    root=Path(__file__).resolve().parents[1]
    lock=json.loads((root/'FILE_LOCK.json').read_text(encoding='utf-8'))
    expected={r['file']:r for r in lock['files']}
    actual={p.relative_to(root).as_posix():p for p in root.rglob('*') if p.is_file() and p!=root/'FILE_LOCK.json'}
    errors=[]
    for name in sorted(set(expected)^set(actual)):errors.append('File set mismatch: '+name)
    for name in sorted(set(expected)&set(actual)):
        path=actual[name]
        if path.is_symlink():errors.append('Unexpected symlink: '+name)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=expected[name]['sha256'] or path.stat().st_size!=expected[name]['bytes']:
            errors.append('Content changed: '+name)
    print(json.dumps({'passed':not errors,'files_checked':len(actual),'errors':errors},ensure_ascii=False,indent=2))
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
