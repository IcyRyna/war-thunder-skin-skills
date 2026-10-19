"""Adopt tested revision 15 candidates; stage independently versioned packages (user-skins 3.12, style 1.12)."""
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
TASK=HERE.parent;PROJECT=TASK.parents[2]
sys.path.insert(0,str(TASK/'tools'))
import publish_revision as base
import standalone_style

base.CANDIDATES=HERE/'candidate'
VERSIONS={base.BASE:'3.12',base.STYLE:'1.12'}
REVIEW=TASK/'evidence/rev15-j10c/review.json'


def main():
    manifest=json.loads((HERE/'baseline/manifest.json').read_text(encoding='utf-8'))
    study=json.loads(REVIEW.read_text(encoding='utf-8'))
    if study.get('state')!='new_airframe_application_reviewed':
        raise ValueError('Review the J-10C application (renders, 1:1 crops, lint, area shares) before adoption')
    tests={}
    for name,label in [(base.BASE,'base'),(base.STYLE,'style')]:
        log=(HERE/f'verification/unit-{label}-final.txt').read_text(encoding='utf-8-sig')
        count=re.search(r'Ran (\d+) tests in .*?\n\s*\nOK \(skipped=(\d+)\)',log,re.S)
        if not count or int(count[1])<210 or int(count[2])!=4:
            raise ValueError(f'{name}: missing successful full test run')
        tests[name]=dict(tests=int(count[1]),skipped=int(count[2]),log_sha256=base.sha((HERE/f'verification/unit-{label}-final.txt').read_bytes()))
    payloads={n:base.files(base.CANDIDATES/n) for n in VERSIONS}
    generated=standalone_style.generate(base.CANDIDATES/base.BASE)
    bundled={p:b for p,b in payloads[base.STYLE].items() if p.startswith(standalone_style.GENERATED)}
    if generated!=bundled: raise ValueError('Standalone style files are out of sync')
    for name,other in [(base.BASE,base.STYLE),(base.STYLE,base.BASE)]:
        for rel,data in payloads[name].items():
            if rel.endswith(('.md','.py','.yaml')) and other in data.decode('utf-8'):
                raise ValueError(f'{name}/{rel}: cross-package dependency/name')
    plans={}
    links={}
    for name in VERSIONS:
        source=PROJECT/'skills'/name;installed=base.INSTALL_ROOT/name
        current=base.files(source)
        if current!=base.files(installed) or {p:base.sha(b) for p,b in current.items()}!=manifest[name]:
            raise ValueError(f'{name}: published source/installed copy changed after baseline')
        if set(current)-set(payloads[name]): raise ValueError('Revision 15 removes no published resources')
        base.frontmatter(payloads[name]['SKILL.md'],name)
        links[name]=base.validate_links(name,payloads)
        changes=sorted(p for p,b in payloads[name].items() if current.get(p)!=b)
        plans[name]=(source,installed,current,changes)
    out=HERE/'publication';out.mkdir(exist_ok=False)
    now=datetime.now(timezone.utc)
    packages={n:base.package(n,payloads[n],out,now) for n in VERSIONS}
    applied=[]
    try:
        for name,(source,installed,current,changes) in plans.items():
            for root in [source,installed]:
                for rel in changes:
                    path=(root/rel).resolve()
                    if not path.is_relative_to(root.resolve()): raise ValueError('Target outside Skill')
                    previous=path.read_bytes() if path.is_file() else None
                    if previous!=current.get(rel): raise ValueError(f'Third-party change: {path}')
                    base.atomic_write(path,payloads[name][rel]);applied.append((path,previous,payloads[name][rel]))
            if base.files(source)!=payloads[name] or base.files(installed)!=payloads[name]:
                raise ValueError(f'{name}: adoption verification failed')
        for name,(_,_,current,changes) in plans.items():
            receipt=dict(schema_version=1,revision=15,version=VERSIONS[name],skill=name,
                checked_at_utc=now.isoformat(),state='validated_skill_revision',effective_files=len(payloads[name]),
                files={p:base.sha(b) for p,b in sorted(payloads[name].items())},
                changed=[p for p in changes if p in current],added=[p for p in changes if p not in current],removed=[],
                source_installed_staged_zip_equal=True,package_sha256=base.sha(packages[name].read_bytes()),
                package_bytes=packages[name].stat().st_size,local_links=links[name],tests=tests[name],
                study_review_sha256=base.sha(REVIEW.read_bytes()),
                trigger='User asked for an Akamywek-style Laevatain J-10C built on the rev 14 Skill from scratch (no v1-v3 material, base layout only, no character art), to record the process and put the lessons into the Skill as a reproducible workflow.',
                validation_scope='Applied to the J-10C: skin colour map selection (--texture), helper boxes with whole-atlas UVs dropped from used texels, bleed and chart assignment (they had made the first chart repaint the whole atlas), airframe_setup.py (island map and per-texel coordinates, metre frame per UV-connected island with outlier-trimmed fit, per-island clean base and mechanical mask, render area shares), replica_check plan with directly written mosaic and provenance, no foreshortening warning on frame charts; new reference new-airframe.md and the style base-layout J-10C section. Each change has a test; the J-10C design was checked with renders, design_lint, area shares and Composa 1:1 against the F-2A map. No in-game validation or user art acceptance inferred.',
                user_art_review='pending',existing_livery_products_modified=False)
            base.atomic_write(out/f'{name}.skill.validation.json',(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    except Exception as error:
        conflicts=[]
        for path,previous,ours in reversed(applied):
            actual=path.read_bytes() if path.is_file() else None
            if actual!=ours: conflicts.append(str(path))
            elif previous is None: path.unlink()
            else: base.atomic_write(path,previous)
        (out/'failure.json').write_text(json.dumps(dict(error=str(error),rollback_conflicts_preserved=conflicts),indent=2),encoding='utf-8')
        raise
    for name in VERSIONS: print(name,VERSIONS[name],base.sha(packages[name].read_bytes()))


if __name__=='__main__': main()
