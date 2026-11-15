"""Check the ZIP actually being delivered and, optionally, its installed files (read only).

One UserSkins folder, one vehicle BLK, and exactly its literal DDS/TGA targets.
Inspect in a temporary directory so stale files next to a build cannot mask a missing ZIP member.
"""
import argparse
import json
from pathlib import Path, PureWindowsPath
import shutil
import stat
import tempfile
import zipfile

from inspect_skins import inventory, sha256


def member_parts(name):
    clean = name.removesuffix("/")
    parts = clean.split("/")
    for p in parts:
        w = PureWindowsPath(p)
        if (not p or p in {".", ".."} or p[-1] in " ." or w.is_reserved()
                or any(ord(c) < 32 or c in '<>:"\\|?*' for c in p)):
            raise ValueError(f"Invalid package member: {name!r}")
    return parts


def verify(archive, user_skins=None):
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory(prefix="akamywek-skin-check-") as tmp:
        entries = z.infolist()
        if len(entries) > 1024 or sum(i.file_size for i in entries) > 8 * 1024**3:
            raise ValueError("Not a supported single-skin ZIP (limit 1024 entries / 8 GiB)")
        roots, names, paths, seen = set(), {}, {}, set()
        for i in entries:
            parts = member_parts(i.filename)
            key = "/".join(parts).casefold()
            if key in seen:
                raise ValueError(f"Duplicate ZIP name: {i.filename}")
            seen.add(key)
            if stat.S_ISLNK(i.external_attr >> 16):
                raise ValueError(f"Link in game ZIP: {i.filename}")
            roots.add(parts[0])
            if i.is_dir():
                continue
            if len(parts) < 2 or Path(parts[-1]).suffix.lower() not in {".blk", ".dds", ".tga"}:
                raise ValueError(f"Unexpected game ZIP member: {i.filename}")
            paths[i.filename] = Path(tmp).joinpath(*parts)
            names[i.filename] = i
        if len(roots) != 1 or not paths:
            raise ValueError("Expected exactly one nonempty top-level skin folder")
        folder = roots.pop()
        skin = Path(tmp) / folder
        for name, dest in paths.items():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(names[name]) as src, dest.open("xb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
        report = inventory(skin, hashes=True)
        if len(report["configs"]) != 1 or "/" in report["configs"][0]["file"]:
            raise ValueError("Expected one vehicle BLK at the root of the skin folder")
        # These warnings are acceptable in research inventories but unresolved in a final package.
        unresolved = {"wildcard_target", "duplicate_mapping", "conflicting_mapping", "case_mismatch",
                      "unhandled_block", "unreferenced_texture"}
        failures = [f"{v['file']}: {v['code']} ({v['message']})" for v in report["issues"]
                    if v["level"] == "error" or v["code"] in unresolved]
        if failures:
            raise ValueError("; ".join(failures))
        files = {}
        install = (user_skins / folder) if user_skins is not None else None
        for p in sorted(paths.values()):
            name = p.relative_to(skin).as_posix()
            digest = report["textures"].get(name, {}).get("sha256") or sha256(p)
            row = {"zip_sha256": digest, "bytes": p.stat().st_size}
            if install is not None:
                actual = install / name
                if not actual.is_file():
                    raise ValueError(f"Missing installed file: {actual}")
                row["installed_sha256"] = sha256(actual)
                if row["installed_sha256"] != digest:
                    raise ValueError(f"Installed file differs from ZIP: {actual}")
            files[name] = row
        return {"skin_folder": folder, "vehicle": report["configs"][0]["vehicle_id"],
                "zip_sha256": sha256(archive), "files": files,
                "formats": report["summary"]["formats"], "issues": report["issues"],
                "checked_install": str(install.resolve()) if install is not None else None,
                "limits": "Package structure and bytes only; no runtime, shader, or artwork verdict."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--user-skins", type=Path, help="Existing game UserSkins directory; hash package members only")
    args = p.parse_args()
    try:
        print(json.dumps(verify(args.archive, args.user_skins), ensure_ascii=True, indent=2))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        p.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
