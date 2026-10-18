"""Revision 12: adopt reviewed candidates of both Skills and stage release packages.

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
sys.path.insert(0, str(TASK / 'tools'))
import publish_revision as base  # noqa: E402  (link checks, packaging, atomic writes)

PROJECT = TASK.parents[2]
base.CANDIDATES = HERE / 'candidate'
SKILLS = (base.BASE, base.STYLE)
sys.path.insert(0, str(TASK / 'tools'))
import standalone_style  # noqa: E402  (bundled scripts/ and references/core/ of the style Skill)


def standalone_gate(payloads) -> None:
    """The style package must be self-contained: generated part in sync, no links or names leaving it."""
    wanted = standalone_style.generate(base.CANDIDATES / base.BASE)
    have = {n: b for n, b in payloads[base.STYLE].items() if n.startswith(standalone_style.GENERATED)}
    if wanted != have:
        raise ValueError('style Skill bundled files differ from the base Skill; rerun tools/standalone_style.py --write')
    for skill, other in ((base.STYLE, base.BASE), (base.BASE, base.STYLE)):
        for rel, data in payloads[skill].items():
            if rel.endswith(('.md', '.yaml', '.py')) and other in data.decode('utf-8'):
                raise ValueError(f'{skill}/{rel} names {other}')


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
            raise ValueError(f'{name}: revision 12 removes nothing')
        base.frontmatter(payloads[name]['SKILL.md'], name)
        changed = sorted(n for n in payloads[name] if n in current and payloads[name][n] != current[n])
        added = sorted(n for n in payloads[name] if n not in current)
        plans[name] = (source, installed, current, changed, added)
    links = {name: base.validate_links(name, payloads) for name in SKILLS}
    standalone_gate(payloads)
    if any(link['skill'] != base.STYLE for link in links[base.STYLE]):
        raise ValueError('style Skill links leave its own package')
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
                           revision=12, effective_files=len(payloads[name]),
                           files={n: base.sha(b) for n, b in sorted(payloads[name].items())},
                           package_sha256=base.sha(packages[name].read_bytes()), package_bytes=packages[name].stat().st_size,
                           source_installed_staged_zip_equal=True, local_links=links[name], changed=changed, added=added, removed=[],
                           code_changed=any(n.endswith('.py') for n in changed + added),
                           trigger='User in-game review of Laevatain J-10C v3 next to Akamywek F-2A: finish looked different, lines dirty and rough; asked for an editor-based analysis, then to learn the F-2A_M4_SOPMOD_II_NA livery first and its basic layout before any character art. Diagnosis (1:1 crops in Composa): traced panel hairlines were broken, stair-stepped and traced stains; the wing art kept a light background and faded into a grey haze. Added the F-2A base layout reference (measured on the author map applied to the decoded F-2A model), a two-stage order (base layout, then art), detail_sheet.py for full-size checks, a quality gate in panel_lines.py (apply refuses failed traces), the sequence exemption in design_lint, clean cut-out art rules, and corrected the stab/fin mix-up. Evidence: evidence/rev12-f2a-base-layout/evidence.json and assignments/j10c-laevatain-akamywek-20261018/evidence/v3-ingame-review/diagnosis.json.',
                           validation_scope='Frontmatter, local links/anchors, exact source/installed/ZIP sync; unit tests run separately (197 each, 4 skipped for missing texconv). detail_sheet.py was run on the v3 colour map against the F-2A map; the panel_lines quality gate rejects the v3 J-10C trace (median 112 px, 55% short, 4.6 kinks per 1000 px). No new livery was built; delivered skins untouched.')
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
