"""Enforce the charcoal skin delivery budget without extracting the archive.

MB is decimal: ZIP < 100,000,000 bytes and expanded files < 200,000,000.
The default check streams every member to verify size and CRC. Metadata-only
mode is for inventory, never for final delivery. This tool never deletes files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
import zipfile

ZIP_LIMIT = 100_000_000
EXPANDED_LIMIT = 200_000_000


def inspect_package(archive: Path, *, verify_payload: bool = True) -> dict:
    archive = Path(archive).resolve(strict=True)
    if not archive.is_file():
        raise ValueError("Expected a ZIP file")
    initial = archive.stat()
    errors: list[str] = []
    if initial.st_size >= ZIP_LIMIT:
        errors.append(f"ZIP must be < {ZIP_LIMIT} bytes; got {initial.st_size}")
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        names: set[str] = set()
        files = []
        for item in members:
            name = item.filename.replace("\\", "/")
            windows = PureWindowsPath(name)
            relative = PurePosixPath(name)
            parts = name.rstrip("/").split("/")
            if (windows.drive or windows.root or relative.is_absolute()
                    or any(p in {"", ".", ".."} or ":" in p
                           or p.endswith((" ", ".")) for p in parts)
                    or any(ord(c) < 32 for c in name)):
                errors.append(f"Unsafe member path: {item.filename}")
            key = name.rstrip("/").casefold()
            if key in names:
                errors.append(f"Duplicate member path: {item.filename}")
            names.add(key)
            mode = item.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                errors.append(f"Unsupported link/special member: {item.filename}")
            if item.flag_bits & 1:
                errors.append(f"Encrypted member: {item.filename}")
            if item.is_dir():
                if item.file_size:
                    errors.append(f"Directory carries data: {item.filename}")
            else:
                files.append(item)
        if not files:
            errors.append("Empty skin archive")
        expanded = sum(item.file_size for item in files)
        if expanded >= EXPANDED_LIMIT:
            errors.append(f"Expanded files must be < {EXPANDED_LIMIT} bytes; got {expanded}")
        payload_verified = False
        if verify_payload and not errors:
            for item in files:
                actual = 0
                with zipped.open(item) as stream:
                    while chunk := stream.read(1024 * 1024):
                        actual += len(chunk)
                        if actual > item.file_size:
                            raise ValueError(f"Member exceeds declared size: {item.filename}")
                if actual != item.file_size:
                    raise ValueError(f"Member size mismatch: {item.filename}")
            payload_verified = True
    final = archive.stat()
    if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
        raise ValueError("Archive changed during verification")
    return {
        "archive": str(archive), "passed": not errors,
        "zip_bytes": initial.st_size, "expanded_bytes": expanded,
        "zip_limit_exclusive": ZIP_LIMIT, "expanded_limit_exclusive": EXPANDED_LIMIT,
        "unit": "decimal MB (1 MB = 1,000,000 bytes)",
        "file_count": len(files), "payload_verified": payload_verified,
        "largest_files": [{"file": i.filename, "bytes": i.file_size}
                          for i in sorted(files, key=lambda i: i.file_size, reverse=True)[:10]],
        "errors": errors,
    }


def require_budget(archive: Path) -> dict:
    report = inspect_package(archive)
    if not report["passed"]:
        raise ValueError("Skin package budget failed: " + "; ".join(report["errors"]))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--metadata-only", action="store_true",
                        help="Inventory only; does not verify member payload/CRC")
    args = parser.parse_args()
    try:
        report = inspect_package(args.archive, verify_payload=not args.metadata_only)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile,
            NotImplementedError, EOFError) as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
