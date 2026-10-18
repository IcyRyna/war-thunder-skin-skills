"""Adopt this task's reviewed Skill candidates and stage their release packages.

Base Skill: candidate replaces the source and installed copies, which must still
equal the saved baseline.  Style Skill: new; its source and installed folders
must not exist yet.  Official ZIPs and receipts are adopted afterwards through
release-add so the registry's hash refresh stays transactional.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import zipfile
from urllib.parse import unquote

# Revision 1 lives in revision-1/ (moved 2026-10-18); its baseline, candidate and publication sit beside it.
TASK = Path(__file__).resolve().parent
PROJECT = TASK.parents[3]
CANDIDATES = TASK / "candidate"
INSTALL_ROOT = Path.home() / ".codex/skills"
BASE, STYLE = "war-thunder-user-skins", "war-thunder-style-akamywek"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".pyo", ".nbc", ".nbi"}}


def anchors(text: str) -> set[str]:
    result, counts = set(), {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        base = re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def validate_links(name: str, payloads: dict[str, dict[str, bytes]]) -> list[dict]:
    """Local links must resolve inside this Skill or the sibling base Skill."""
    root = (CANDIDATES / name).resolve()
    allowed = {CANDIDATES / BASE: BASE, CANDIDATES / STYLE: STYLE}
    links = []
    for rel, payload in payloads[name].items():
        if not rel.endswith(".md"):
            continue
        for url in re.findall(r"\[[^\]]*\]\(([^)]+)\)", payload.decode("utf-8-sig")):
            if "://" in url or url.startswith("mailto:"):
                continue
            filename, _, fragment = url.partition("#")
            target = ((root / rel).parent / filename if filename else root / rel).resolve()
            owner = next((skill for base, skill in allowed.items() if target.is_relative_to(base.resolve())), None)
            if owner is None or not target.is_file():
                raise ValueError(f"Broken local link: {name}/{rel}: {url}")
            if owner != name and owner != BASE:
                raise ValueError(f"Link leaves the allowed Skills: {name}/{rel}: {url}")
            target_rel = target.relative_to((CANDIDATES / owner).resolve()).as_posix()
            if fragment and unquote(fragment) not in anchors(payloads[owner][target_rel].decode("utf-8-sig")):
                raise ValueError(f"Broken local anchor: {name}/{rel}: {url}")
            links.append({"source": rel, "link": url, "skill": owner})
    return links


def frontmatter(payload: bytes, name: str) -> None:
    text = payload.decode("utf-8-sig")
    match = re.match(r"---\r?\nname: (.+?)\r?\ndescription: (.+?)\r?\n---\r?\n", text)
    if not match or match.group(1).strip() != name or len(match.group(2)) > 1024:
        raise ValueError(f"{name}: SKILL.md frontmatter must carry this name and a description under 1024 characters")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def package(name: str, payload: dict[str, bytes], out: Path, now: datetime) -> Path:
    target = out / f"{name}.skill.zip"
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel, data in sorted(payload.items()):
            info = zipfile.ZipInfo(f"{name}/{rel}", now.timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None or archive.namelist() != [f"{name}/{r}" for r in sorted(payload)]:
            raise ValueError(f"{name}: staged ZIP CRC or inventory failed")
        if any(archive.read(f"{name}/{r}") != d for r, d in payload.items()):
            raise ValueError(f"{name}: staged ZIP differs from reviewed files")
    return target


def main() -> None:
    baseline = json.loads((TASK / "baseline/manifest.json").read_text(encoding="utf-8"))
    base_source, base_installed = PROJECT / "skills" / BASE, INSTALL_ROOT / BASE
    style_source, style_installed = PROJECT / "skills" / STYLE, INSTALL_ROOT / STYLE
    current = files(base_source)
    if current != files(base_installed) or {n: sha(b) for n, b in current.items()} != {
            n: v["sha256"] for n, v in baseline["files"].items()}:
        raise ValueError("Base source or installed Skill changed after the saved baseline")
    if sha((TASK / "baseline/previous.skill.zip").read_bytes()) != baseline["package_sha256"]:
        raise ValueError("Saved release baseline changed")
    if style_source.exists() or style_installed.exists():
        raise ValueError("Style Skill destination already exists")
    payloads = {BASE: files(CANDIDATES / BASE), STYLE: files(CANDIDATES / STYLE)}
    for name, payload in payloads.items():
        frontmatter(payload["SKILL.md"], name)
    removed = sorted(set(current) - set(payloads[BASE]))
    if removed:
        raise ValueError(f"This revision removes nothing; unexpected removals: {removed}")
    changed = sorted(n for n in payloads[BASE] if n in current and payloads[BASE][n] != current[n])
    added = sorted(n for n in payloads[BASE] if n not in current)
    links = {name: validate_links(name, payloads) for name in payloads}
    out = TASK / "publication"
    out.mkdir(exist_ok=False)
    now = datetime.now(timezone.utc)
    packages = {name: package(name, payload, out, now) for name, payload in payloads.items()}
    receipts = {}
    for name, payload in payloads.items():
        receipts[name] = {
            "schema_version": 1, "checked_at_utc": now.isoformat(), "state": "validated_skill_revision",
            "skill": name, "effective_files": len(payload), "files": {n: sha(b) for n, b in sorted(payload.items())},
            "package_sha256": sha(packages[name].read_bytes()), "package_bytes": packages[name].stat().st_size,
            "source_installed_staged_zip_equal": True, "local_links": links[name],
            "markdown_chars": sum(len(b.decode("utf-8-sig")) for n, b in payload.items() if n.endswith(".md")),
            "validation_scope": "Frontmatter, local links and anchors, exact source/installed/ZIP synchronisation; code tests run separately (see task verification). Tool demonstrations on J-16 geometry only; no new user art acceptance.",
            "official_release_adoption": "Copied into releases/ and refreshed with release-add."}
    receipts[BASE].update(changed=changed, added=added, removed=[], code_changed=any(n.endswith(".py") for n in changed + added),
                          markdown_chars_before=baseline["markdown_chars"], previous_package_sha256=baseline["package_sha256"])
    receipts[STYLE].update(new_skill=True, depends_on=BASE)
    applied: list[tuple[Path, bytes | None, bytes]] = []
    try:
        for root in (base_source, base_installed):
            for rel in changed + added:
                path = (root / rel).resolve()
                if not path.is_relative_to(root.resolve()):
                    raise ValueError(f"Target resolves outside Skill: {path}")
                previous = path.read_bytes() if path.is_file() else None
                if previous != current.get(rel):
                    raise ValueError(f"Target changed during adoption: {path}")
                atomic_write(path, payloads[BASE][rel])
                applied.append((path, previous, payloads[BASE][rel]))
        for root in (style_source, style_installed):
            for rel, data in sorted(payloads[STYLE].items()):
                path = (root / rel).resolve()
                if path.exists():
                    raise ValueError(f"Style target appeared during adoption: {path}")
                atomic_write(path, data)
                applied.append((path, None, data))
        if files(base_source) != payloads[BASE] or files(base_installed) != payloads[BASE]:
            raise ValueError("Adopted base source/installed bytes differ")
        if files(style_source) != payloads[STYLE] or files(style_installed) != payloads[STYLE]:
            raise ValueError("Adopted style source/installed bytes differ")
        for name, receipt in receipts.items():
            atomic_write(out / f"{name}.skill.validation.json", (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except Exception as error:
        conflicts = []
        for path, previous, ours in reversed(applied):
            actual = path.read_bytes() if path.is_file() else None
            if actual != ours:
                conflicts.append(str(path))
            elif previous is None:
                path.unlink()
            else:
                atomic_write(path, previous)
        (out / "failure.json").write_text(json.dumps({"error": str(error), "rollback_conflicts_preserved": conflicts},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    print(json.dumps({name: {"files": len(p), "package": str(packages[name]), "sha256": receipts[name]["package_sha256"]}
                      for name, p in payloads.items()}, ensure_ascii=False, indent=1))
    print("base changed:", changed)
    print("base added:", added)


if __name__ == "__main__":
    main()
