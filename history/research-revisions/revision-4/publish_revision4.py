"""Revision 4: adopt reviewed candidates of both Skills and stage release packages.

Source and installed copies must still equal the saved baseline manifest.  Only
changed or added files are written; nothing is removed.  Official ZIPs and
receipts are adopted afterwards one file at a time with release-add.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / 'revision-1'))
import publish_revision as base  # noqa: E402  (link checks, packaging, atomic writes)

PROJECT = TASK.parents[2]
base.CANDIDATES = HERE / 'candidate'
SKILLS = (base.BASE, base.STYLE)


def main() -> None:
    manifest = json.loads((HERE / 'baseline/manifest.json').read_text(encoding='utf-8'))
    payloads = {name: base.files(base.CANDIDATES / name) for name in SKILLS}
    plans = {}
    for name in SKILLS:
        source, installed = PROJECT / 'skills' / name, base.INSTALL_ROOT / name
        current = base.files(source)
        if current != base.files(installed) or {n: base.sha(b) for n, b in current.items()} != manifest[name]:
            raise ValueError(f'{name}: source or installed copy changed after the saved baseline')
        if set(current) - set(payloads[name]):
            raise ValueError(f'{name}: revision 4 removes nothing')
        base.frontmatter(payloads[name]['SKILL.md'], name)
        changed = sorted(n for n in payloads[name] if n in current and payloads[name][n] != current[n])
        added = sorted(n for n in payloads[name] if n not in current)
        plans[name] = (source, installed, current, changed, added)
    links = {name: base.validate_links(name, payloads) for name in SKILLS}
    out = HERE / 'publication'
    out.mkdir(exist_ok=False)
    now = datetime.now(timezone.utc)
    packages = {name: base.package(name, payloads[name], out, now) for name in SKILLS}
    applied = []
    try:
        for name, (source, installed, current, changed, added) in plans.items():
            for root in (source, installed):
                for rel in changed + added:
                    path = (root / rel).resolve()
                    if not path.is_relative_to(root.resolve()):
                        raise ValueError(f'Target outside Skill: {path}')
                    previous = path.read_bytes() if path.is_file() else None
                    if previous != current.get(rel):
                        raise ValueError(f'Target changed during adoption: {path}')
                    base.atomic_write(path, payloads[name][rel])
                    applied.append((path, previous, payloads[name][rel]))
            if base.files(source) != payloads[name] or base.files(installed) != payloads[name]:
                raise ValueError(f'{name}: adopted bytes differ')
        for name, (_, _, current, changed, added) in plans.items():
            receipt = dict(schema_version=1, checked_at_utc=now.isoformat(), state='validated_skill_revision', skill=name,
                           revision=4, effective_files=len(payloads[name]),
                           files={n: base.sha(b) for n, b in sorted(payloads[name].items())},
                           package_sha256=base.sha(packages[name].read_bytes()), package_bytes=packages[name].stat().st_size,
                           source_installed_staged_zip_equal=True, local_links=links[name], changed=changed, added=added, removed=[],
                           code_changed=any(n.endswith('.py') for n in changed + added),
                           trigger='User request: distil the J-16 Chen v5-v9 lessons into the Skills (shared-UV chart order, up-facing chart threshold, flat-zone placement, inner-fin wedge) and add surface_map.py.',
                           validation_scope='Frontmatter, local links/anchors, exact source/installed/ZIP sync; unit tests run separately. No new art acceptance.')
            base.atomic_write(out / f'{name}.skill.validation.json', (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    except Exception as error:
        conflicts = []
        for path, previous, ours in reversed(applied):
            actual = path.read_bytes() if path.is_file() else None
            if actual != ours:
                conflicts.append(str(path))
            elif previous is None:
                path.unlink()
            else:
                base.atomic_write(path, previous)
        (out / 'failure.json').write_text(json.dumps({'error': str(error), 'rollback_conflicts_preserved': conflicts}, indent=2), encoding='utf-8')
        raise
    for name, (_, _, _, changed, added) in plans.items():
        print(name, 'changed', changed, 'added', added, base.sha(packages[name].read_bytes())[:12])


if __name__ == '__main__':
    main()
