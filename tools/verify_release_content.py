"""Verify that reorganized baseline packages preserve official Release file bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify_archive(archive: Path, package: dict) -> dict:
    expected = {item["path"]: item for item in package["files"]}
    if len(expected) != len(package["files"]):
        raise ValueError("Duplicate path in content lock")
    actual = {}
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 5000:
            raise ValueError("Package has too many entries")
        for item in members:
            name = item.filename
            raw = name[:-1] if name.endswith("/") else name
            path = PurePosixPath(raw)
            if ("\\" in name or path.is_absolute() or ":" in name
                    or any(part in {"", ".", ".."} for part in raw.split("/"))
                    or any(ord(char) < 32 for char in name)):
                raise ValueError(f"Unsafe archive path: {name}")
            file_type = stat.S_IFMT(item.external_attr >> 16)
            allowed_types = {0, stat.S_IFDIR} if item.is_dir() else {0, stat.S_IFREG}
            if file_type not in allowed_types:
                raise ValueError(f"Non-regular or mismatched archive entry: {name}")
            if not path.parts or path.parts[0] != package["id"]:
                raise ValueError(f"Unexpected package root: {name}")
            if item.is_dir():
                continue
            relative = "/".join(path.parts[1:])
            if not relative or relative in actual:
                raise ValueError(f"Duplicate or invalid archive member: {name}")
            if item.file_size > 200 * 1024 * 1024:
                raise ValueError(f"Member too large: {name}")
            h = hashlib.sha256()
            with bundle.open(item) as stream:
                while block := stream.read(1024 * 1024):
                    h.update(block)
            actual[relative] = {"path": relative, "bytes": item.file_size, "sha256": h.hexdigest()}
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(path for path in expected.keys() & actual.keys()
                     if expected[path]["sha256"] != actual[path]["sha256"]
                     or expected[path]["bytes"] != actual[path]["bytes"])
    return {"id": package["id"], "baseline_tag": package["tag"],
            "files": len(actual), "missing": missing, "extra": extra, "changed": changed,
            "ok": not (missing or extra or changed)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--lock", type=Path, default=ROOT / "releases/content-lock.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        if lock.get("schema_version") != 1 or not lock.get("packages"):
            raise ValueError("Expected version-1 nonempty baseline content lock")
        results = []
        for package in lock["packages"]:
            ident = package["id"]
            if not isinstance(ident, str) or not ident or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in ident):
                raise ValueError("Invalid package id in lock")
            results.append(verify_archive(args.dist / f"{ident}-candidate.zip", package))
        ok = all(item["ok"] for item in results)
        report = {"ok": ok, "packages": results,
                  "scope": "Inner file bytes match official baselines; ZIP container bytes may differ. No new release or artwork acceptance is implied."}
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        report, ok = {"ok": False, "error": str(exc)}, False
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif "error" in report:
        print(report["error"], file=sys.stderr)
    else:
        for item in report["packages"]:
            print(f"{'PASS' if item['ok'] else 'FAIL'} {item['id']}: {item['files']} files against {item['baseline_tag']}")
            for key in ("missing", "extra", "changed"):
                if item[key]:
                    print(f"  {key}: {', '.join(item[key])}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
