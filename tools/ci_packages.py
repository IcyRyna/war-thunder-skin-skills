#!/usr/bin/env python3
"""CI-only release asset retrieval followed by strict local candidate checks.

Requires gh authenticated with read access. Downloads existing releases only;
all builds remain ignored local candidates. repository.py itself never networks.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

import repository


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        packages = repository.read_catalog(root)
        raw = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        repo_name = raw.get("repository")
        if not isinstance(repo_name, str) or not repo_name or repo_name.startswith("-"):
            raise repository.RepositoryError("Catalog requires repository owner/name for release retrieval")
        archives: list[Path] = []
        downloaded: set[str] = set()
        # Keep external binary inputs out of source and Git history.
        with tempfile.TemporaryDirectory(prefix="skill-release-assets-") as temporary:
            asset_root = Path(temporary)
            for package in packages:
                if not package.get("supplements"):
                    continue
                baseline = package.get("baseline") or {}
                checksum = baseline.get("package_sha256")
                if checksum in downloaded:
                    continue
                url = baseline.get("package_url", "")
                filename = Path(urlsplit(url).path).name
                repository.portable_path(filename)
                directory = asset_root / package["id"]
                directory.mkdir()
                subprocess.run([
                    "gh", "release", "download", baseline["tag"],
                    "--repo", repo_name, "--pattern", filename, "--dir", str(directory),
                ], check=True, cwd=root)
                archive = directory / filename
                if repository.file_digest(archive) != checksum:
                    raise repository.RepositoryError(f"Downloaded baseline digest mismatch: {package['id']}")
                archives.append(archive)
                downloaded.add(checksum)
            index = repository.archive_index(archives)
            for package in packages:
                tree = repository.assemble(root, package, index)
                if tree.missing_assets:
                    raise repository.RepositoryError(f"Missing release assets: {package['id']}")
                result = repository.build(tree, repository.output_directory(root, "dist"))
                print(f"PASS {package['id']}: {result['files']} files, SHA-256 {result['sha256']}")
        return 0
    except (repository.RepositoryError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
