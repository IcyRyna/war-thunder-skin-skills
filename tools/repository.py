#!/usr/bin/env python3
"""Inspect and reconstruct independent Skill candidates using only the standard library.

No command publishes, installs, or assigns an official version. Local Markdown
links are checked against the assembled package, including injected shared files.
Historical ZIP metadata is not reproduced: a candidate is a content reconstruction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import unicodedata
from urllib.parse import unquote, urlsplit
import zipfile

SCHEMA_VERSION = 1
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PACKAGE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
CACHE_NAMES = {".git", "__pycache__", ".numba-cache", ".cache", ".pytest_cache"}
CACHE_SUFFIXES = {".pyc", ".pyo", ".nbi", ".nbc"}
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
}


class RepositoryError(ValueError):
    """An unsafe path, inconsistent manifest, or invalid package."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def portable_path(value: object, *, empty: bool = False) -> PurePosixPath:
    """Accept a literal portable relative path, never normalize away traversal."""
    if not isinstance(value, str) or (not value and not empty):
        raise RepositoryError(f"Expected a nonempty relative path: {value!r}")
    if value == "" and empty:
        return PurePosixPath(".")
    if "\\" in value or value.startswith("/") or any(ord(char) < 32 for char in value):
        raise RepositoryError(f"Non-portable or absolute path: {value!r}")
    parts = value.split("/")
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((" ", ".")) or any(char in part for char in ':*?"<>|'):
            raise RepositoryError(f"Unsafe path component in {value!r}")
        if part.split(".")[0].casefold() in WINDOWS_RESERVED:
            raise RepositoryError(f"Reserved Windows path in {value!r}")
    return PurePosixPath(value)


def reject_link(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise RepositoryError(f"Symlink or reparse point is not allowed: {path}")


def local_path(root: Path, relative: object, *, must_exist: bool = True) -> Path:
    parts = portable_path(relative).parts
    result = root
    for part in parts:
        result = result / part
        if result.exists() or result.is_symlink():
            reject_link(result)
        elif must_exist:
            raise RepositoryError(f"Missing repository path: {relative}")
    if not result.resolve().is_relative_to(root.resolve()):
        raise RepositoryError(f"Path escapes repository: {relative}")
    return result


def require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RepositoryError(f"{label} must be a lowercase SHA-256 digest")
    return value


def read_catalog(root: Path, catalog: str = "catalog.json") -> list[dict]:
    path = local_path(root, catalog)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RepositoryError(f"Invalid catalog: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise RepositoryError(f"Catalog schema_version must be {SCHEMA_VERSION}")
    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RepositoryError("Catalog packages must be a nonempty array")
    seen: set[str] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise RepositoryError("Each package must be an object")
        identifier = package.get("id")
        if not isinstance(identifier, str) or not PACKAGE_ID.fullmatch(identifier) or identifier in seen:
            raise RepositoryError(f"Invalid or duplicate package id: {identifier!r}")
        seen.add(identifier)
        portable_path(package.get("source"))
        for field in ("kind", "status"):
            if not isinstance(package.get(field), str) or not package[field].strip():
                raise RepositoryError(f"{identifier}: missing {field}")
        for field in ("includes", "supplements"):
            if not isinstance(package.get(field, []), list):
                raise RepositoryError(f"{identifier}: {field} must be an array")
        for include in package.get("includes", []):
            if not isinstance(include, dict):
                raise RepositoryError(f"{identifier}: each include must be an object")
            portable_path(include.get("source"))
            portable_path(include.get("target"), empty=True)
        for supplement in package.get("supplements", []):
            if not isinstance(supplement, dict):
                raise RepositoryError(f"{identifier}: each supplement must be an object")
            for field in ("archive_sha256", "sha256"):
                require_hash(supplement.get(field), f"{identifier} supplement.{field}")
            for field in ("archive_member", "target"):
                portable_path(supplement.get(field))
            if type(supplement.get("bytes")) is not int or supplement["bytes"] < 0:
                raise RepositoryError(f"{identifier}: supplement.bytes must be a nonnegative integer")
        baseline = package.get("baseline")
        if baseline is not None:
            if not isinstance(baseline, dict):
                raise RepositoryError(f"{identifier}: baseline must be an object or null")
            for field in ("version", "tag"):
                if not isinstance(baseline.get(field), str) or not baseline[field]:
                    raise RepositoryError(f"{identifier}: baseline missing {field}")
            require_hash(baseline.get("package_sha256"), f"{identifier} baseline.package_sha256")
    return packages


def is_cache(path: PurePosixPath) -> bool:
    return any(part.casefold() in CACHE_NAMES for part in path.parts) or path.suffix.casefold() in CACHE_SUFFIXES


class PackageTree:
    def __init__(self, root: Path, package: dict):
        self.root = root
        self.package = package
        self.files: dict[str, dict] = {}
        self._case_paths: dict[str, str] = {}
        self._case_dirs: dict[str, str] = {}
        self.missing_assets: list[dict] = []

    def add(self, target: str, *, data: bytes | None, source: dict,
            expected_hash: str | None = None, expected_bytes: int | None = None) -> None:
        parsed = portable_path(target)
        if is_cache(parsed):
            raise RepositoryError(f"{self.package['id']}: cache or repository metadata in package: {target}")
        folded = unicodedata.normalize("NFC", target).casefold()
        if folded in self._case_paths:
            raise RepositoryError(f"Output collision: {target} and {self._case_paths[folded]}")
        for other_folded, other in self._case_paths.items():
            if folded.startswith(other_folded + "/") or other_folded.startswith(folded + "/"):
                raise RepositoryError(f"File/directory collision: {target} and {other}")
        for parent in parsed.parents:
            name = str(parent)
            if name == ".":
                continue
            key = unicodedata.normalize("NFC", name).casefold()
            if key in self._case_dirs and self._case_dirs[key] != name:
                raise RepositoryError(f"Directory case collision: {name} and {self._case_dirs[key]}")
            self._case_dirs[key] = name
        self._case_paths[folded] = target
        self.files[target] = {
            "data": data, "sha256": digest(data) if data is not None else expected_hash,
            "bytes": len(data) if data is not None else expected_bytes, "source": source,
        }

    def add_source(self, source: str, target: str) -> None:
        path = local_path(self.root, source)
        portable_path(target, empty=True)
        if path.is_file():
            if not target:
                raise RepositoryError(f"File include requires an explicit target: {source}")
            self.add(target, data=path.read_bytes(), source={"repository_path": source})
            return
        if not path.is_dir():
            raise RepositoryError(f"Source is not a regular file or directory: {source}")
        def fail_walk(error: OSError) -> None:
            raise RepositoryError(f"Cannot enumerate source directory: {error}") from error

        for current, dirs, names in os.walk(path, followlinks=False, onerror=fail_walk):
            current_path = Path(current)
            for name in sorted(dirs):
                directory = current_path / name
                reject_link(directory)
                if is_cache(PurePosixPath(directory.relative_to(path).as_posix())):
                    raise RepositoryError(f"Cache or repository metadata in source: {directory}")
            for name in sorted(names):
                entry = current_path / name
                reject_link(entry)
                if not entry.is_file():
                    raise RepositoryError(f"Non-regular file in source: {entry}")
                suffix = entry.relative_to(path).as_posix()
                output = f"{target}/{suffix}" if target else suffix
                self.add(output, data=entry.read_bytes(),
                         source={"repository_path": entry.relative_to(self.root).as_posix()})

    def snapshot(self) -> list[dict]:
        return [
            {"path": name, "sha256": value["sha256"], "bytes": value["bytes"], "source": value["source"]}
            for name, value in sorted(self.files.items())
        ]


def archive_index(paths: list[Path]) -> dict[str, Path]:
    result = {}
    for path in paths:
        if not path.is_file():
            raise RepositoryError(f"Asset archive is not a file: {path}")
        reject_link(path)
        checksum = file_digest(path)
        if checksum in result:
            continue
        result[checksum] = path
    return result


def archive_member(path: Path, member: str, expected_bytes: int) -> bytes:
    """Read only a declared member after validating the entire archive namespace."""
    try:
        with zipfile.ZipFile(path) as archive:
            names: set[str] = set()
            for info in archive.infolist():
                name = info.filename.rstrip("/") if info.is_dir() else info.filename
                portable_path(name)
                key = unicodedata.normalize("NFC", name).casefold()
                if key in names:
                    raise RepositoryError(f"Duplicate archive member: {info.filename}")
                names.add(key)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise RepositoryError(f"Archive contains a symlink: {info.filename}")
            try:
                info = archive.getinfo(member)
            except KeyError as exc:
                raise RepositoryError(f"Missing asset archive member: {member}") from exc
            if info.is_dir() or info.file_size != expected_bytes:
                raise RepositoryError(f"Asset size mismatch: {member}")
            return archive.read(info)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise RepositoryError(f"Cannot read asset archive {path.name}: {exc}") from exc


def assemble(root: Path, package: dict, archives: dict[str, Path] | None = None) -> PackageTree:
    tree = PackageTree(root, package)
    tree.add_source(package["source"], "")
    for include in package.get("includes", []):
        if not isinstance(include, dict) or "target" not in include:
            raise RepositoryError(f"{package['id']}: invalid include")
        tree.add_source(include.get("source"), include["target"])
    for supplement in package.get("supplements", []):
        if not isinstance(supplement, dict):
            raise RepositoryError(f"{package['id']}: invalid supplement")
        archive_hash = require_hash(supplement.get("archive_sha256"), "supplement.archive_sha256")
        content_hash = require_hash(supplement.get("sha256"), "supplement.sha256")
        member = str(portable_path(supplement.get("archive_member")))
        target = str(portable_path(supplement.get("target")))
        size = supplement.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RepositoryError(f"Invalid supplement bytes: {target}")
        archive = (archives or {}).get(archive_hash)
        data = archive_member(archive, member, size) if archive else None
        if data is not None and digest(data) != content_hash:
            raise RepositoryError(f"Asset SHA-256 mismatch: {target}")
        if data is None:
            tree.missing_assets.append({"target": target, "archive_sha256": archive_hash, "archive_member": member})
        tree.add(target, data=data, expected_hash=content_hash, expected_bytes=size,
                 source={"archive_sha256": archive_hash, "archive_member": member})
    validate_frontmatter(tree)
    validate_links(tree)
    return tree


def validate_frontmatter(tree: PackageTree) -> None:
    record = tree.files.get("SKILL.md")
    if record is None or record["data"] is None:
        raise RepositoryError(f"{tree.package['id']}: missing source SKILL.md")
    try:
        text = record["data"].decode("utf-8-sig")
    except UnicodeError as exc:
        raise RepositoryError("SKILL.md must be UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise RepositoryError("SKILL.md must start with frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise RepositoryError("Unterminated SKILL.md frontmatter") from exc
    values: dict[str, str] = {}
    for index, line in enumerate(lines[1:end], 1):
        match = re.match(r"^([a-zA-Z_][\w-]*):\s*(.*)$", line)
        if not match:
            continue
        name, value = match.groups()
        if name in values:
            raise RepositoryError(f"Duplicate frontmatter field: {name}")
        if value in {"|", ">", "|-", ">-", "|+", ">+"}:
            continuation = []
            for following in lines[index + 1:end]:
                if following and not following[0].isspace():
                    break
                continuation.append(following.strip())
            value = " ".join(continuation)
        values[name] = value.strip().strip("'\"")
    if values.get("name") != tree.package["id"]:
        raise RepositoryError(f"Frontmatter name must match {tree.package['id']}")
    if not values.get("description") or values["description"].lower() in {"null", "~", "[]", "{}"}:
        raise RepositoryError("Frontmatter description must be nonempty")


def markdown_destination(text: str, start: int) -> str:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    angle = index < len(text) and text[index] == "<"
    if angle:
        index += 1
    result = []
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] in r"()<>\\ ":
            result.append(text[index + 1])
            index += 2
            continue
        if angle:
            if char in ">\n":
                break
        else:
            if char.isspace():
                break
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
        result.append(char)
        index += 1
    return "".join(result)


def markdown_links(text: str) -> list[str]:
    # Validate authored Markdown links, not prose, code examples, or guessed paths.
    lines = []
    fence_char, fence_length = "", 0
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_char:
            if marker and marker[1][0] == fence_char and len(marker[1]) >= fence_length and not marker[2].strip():
                fence_char, fence_length = "", 0
            continue
        if marker:
            fence_char, fence_length = marker[1][0], len(marker[1])
            continue
        lines.append(line)
    text = re.sub(r"`+[^`]*`+", "", "\n".join(lines))
    result = []
    for match in re.finditer(r"!?\[[^\]\n]*\]\(", text):
        result.append(markdown_destination(text, match.end()))
    for match in re.finditer(r"(?m)^ {0,3}\[[^\]\n]+\]:", text):
        result.append(markdown_destination(text, match.end()))
    return result


def validate_links(tree: PackageTree) -> None:
    files = set(tree.files)
    directories = {str(parent) for name in files for parent in PurePosixPath(name).parents}
    for name, entry in tree.files.items():
        if not name.endswith(".md") or entry["data"] is None:
            continue
        try:
            text = entry["data"].decode("utf-8-sig")
        except UnicodeError as exc:
            raise RepositoryError(f"Markdown file is not UTF-8: {name}") from exc
        for link in markdown_links(text):
            if re.match(r"^[a-zA-Z]:[/\\]", link) or link.lower().startswith("file:"):
                raise RepositoryError(f"Non-portable package link in {name}: {link}")
            try:
                parsed = urlsplit(link)
            except ValueError as exc:
                raise RepositoryError(f"Malformed Markdown link in {name}: {link}") from exc
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            decoded = unquote(parsed.path)
            if decoded.startswith("/") or "\\" in decoded:
                raise RepositoryError(f"Non-portable package link in {name}: {link}")
            parts = list(PurePosixPath(name).parent.parts)
            for part in decoded.split("/"):
                if part in {"", "."}:
                    continue
                if part == "..":
                    if not parts:
                        raise RepositoryError(f"Link escapes package in {name}: {link}")
                    parts.pop()
                else:
                    portable_path(part)
                    parts.append(part)
            target = "/".join(parts) or "."
            if target not in files and target not in directories:
                raise RepositoryError(f"Missing package link in {name}: {link} -> {target}")


def write_zip(tree: PackageTree, path: Path) -> None:
    if tree.missing_assets:
        raise RepositoryError(f"{tree.package['id']}: {len(tree.missing_assets)} external assets required; use --asset-archive")
    # ZIP_STORED avoids zlib-version differences; file bytes and metadata are fixed.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name, entry in sorted(tree.files.items()):
            info = zipfile.ZipInfo(f"{tree.package['id']}/{name}", date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, entry["data"])


def output_directory(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise RepositoryError("Build output must be inside repository dist/") from exc
    else:
        relative = value
    parsed = portable_path(relative)
    if parsed.parts[0] != "dist":
        raise RepositoryError("Build output must be inside ignored dist/")
    result = local_path(root, relative, must_exist=False)
    result.mkdir(parents=True, exist_ok=True)
    return result


def publish_file(temporary: Path, target: Path, checksum: str, *, force: bool) -> None:
    if force:
        os.replace(temporary, target)
        return
    try:
        # A same-filesystem hard link makes the complete file visible atomically
        # and refuses an existing name even if another builder raced this one.
        os.link(temporary, target)
    except FileExistsError:
        reject_link(target)
        if not target.is_file() or file_digest(target) != checksum:
            raise RepositoryError(f"Refusing to overwrite different output: {target}; use --force")


def build(tree: PackageTree, output: Path, *, force: bool = False) -> dict:
    if tree.missing_assets:
        raise RepositoryError(f"{tree.package['id']}: {len(tree.missing_assets)} external assets required; use --asset-archive")
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{tree.package['id']}-candidate.zip"
    receipt_path = target.with_suffix(".receipt.json")
    for path in (target, receipt_path):
        if path.exists() or path.is_symlink():
            reject_link(path)
            if not path.is_file():
                raise RepositoryError(f"Output is not a regular file: {path}")
    handle, temporary = tempfile.mkstemp(prefix=".package-", suffix=".zip", dir=output)
    os.close(handle)
    temporary_path = Path(temporary)
    receipt_temp: Path | None = None
    try:
        write_zip(tree, temporary_path)
        checksum = file_digest(temporary_path)
        snapshot = tree.snapshot()
        receipt = {
            "schema_version": 1, "package_id": tree.package["id"],
            "kind": tree.package["kind"], "status": tree.package["status"],
            "artifact_type": "reconstructed-candidate",
            "official_version_assigned": False,
            "baseline": tree.package.get("baseline"),
            "baseline_archive_bytes_reproduced": bool(
                tree.package.get("baseline") and tree.package["baseline"]["package_sha256"] == checksum
            ),
            "archive": {"name": target.name, "sha256": checksum, "bytes": temporary_path.stat().st_size,
                        "compression": "stored", "timestamp": "1980-01-01T00:00:00"},
            "file_count": len(snapshot), "files": snapshot,
            "content_snapshot_sha256": digest(json_bytes([
                {key: value[key] for key in ("path", "bytes", "sha256")} for value in snapshot
            ])),
        }
        receipt_data = json_bytes(receipt)
        if not force:
            if target.exists() and file_digest(target) != checksum:
                raise RepositoryError(f"Refusing to overwrite different candidate: {target}; use --force")
            if receipt_path.exists() and receipt_path.read_bytes() != receipt_data:
                raise RepositoryError(f"Refusing to overwrite different receipt: {receipt_path}; use --force")
        handle, receipt_name = tempfile.mkstemp(prefix=".receipt-", suffix=".json", dir=output)
        receipt_temp = Path(receipt_name)
        with os.fdopen(handle, "wb") as stream:
            stream.write(receipt_data)
            stream.flush()
            os.fsync(stream.fileno())
        # Each published file is atomic. A crash between replacements is detectable
        # by comparing the receipt's archive digest; no partial ZIP is ever visible.
        publish_file(temporary_path, target, checksum, force=force)
        publish_file(receipt_temp, receipt_path, digest(receipt_data), force=force)
        return {"archive": str(target), "receipt": str(receipt_path), "sha256": checksum,
                "content_snapshot_sha256": receipt["content_snapshot_sha256"], "files": len(snapshot)}
    finally:
        temporary_path.unlink(missing_ok=True)
        if receipt_temp is not None:
            receipt_temp.unlink(missing_ok=True)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", default="catalog.json", help="repository-relative catalog path")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list declared packages and baseline versions")
    listing.add_argument("--json", action="store_true")
    checking = commands.add_parser("check", help="validate assembled package contents")
    checking.add_argument("ids", nargs="*")
    checking.add_argument("--require-assets", action="store_true")
    checking.add_argument("--asset-archive", action="append", type=Path, default=[])
    checking.add_argument("--json", action="store_true")
    building = commands.add_parser("build", help="build a standalone candidate ZIP and receipt")
    building.add_argument("id")
    building.add_argument("--asset-archive", action="append", type=Path, default=[])
    building.add_argument("--output-dir", default="dist")
    building.add_argument("--force", action="store_true", help="replace an existing mismatching candidate or receipt")
    building.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        root = args.root.absolute()
        reject_link(root)
        root = root.resolve()
        packages = read_catalog(root, args.catalog)
        if args.command == "list":
            result = [{"id": item["id"], "kind": item["kind"], "status": item["status"],
                       "source": item["source"], "baseline": item.get("baseline"),
                       "external_asset_count": len(item.get("supplements", []))} for item in packages]
            if args.json:
                print(json_bytes(result).decode("utf-8"), end="")
            else:
                for item in result:
                    version = (item["baseline"] or {}).get("version", "none")
                    print(f"{item['id']}\t{item['kind']}\t{item['status']}\tbaseline={version}\texternal_assets={item['external_asset_count']}")
            return 0
        chosen = args.ids if args.command == "check" else [args.id]
        if chosen:
            unknown = set(chosen) - {package["id"] for package in packages}
            if unknown:
                raise RepositoryError(f"Unknown package(s): {', '.join(sorted(unknown))}")
            packages = [package for package in packages if package["id"] in chosen]
        archives = archive_index(args.asset_archive)
        declared_archives = {item["archive_sha256"] for package in packages for item in package.get("supplements", [])}
        unused = set(archives) - declared_archives
        if unused:
            raise RepositoryError(f"Asset archive SHA-256 not declared for selected packages: {', '.join(sorted(unused))}")
        if args.command == "build":
            tree = assemble(root, packages[0], archives)
            result = build(tree, output_directory(root, args.output_dir), force=args.force)
            if args.json:
                print(json_bytes(result).decode("utf-8"), end="")
            else:
                print(f"Built reconstructed candidate: {result['archive']}")
                print(f"SHA-256: {result['sha256']}")
                print(f"Receipt: {result['receipt']}")
            return 0
        results = []
        failed = False
        for package in packages:
            try:
                tree = assemble(root, package, archives)
                status = "needs-assets" if tree.missing_assets else "pass"
                if tree.missing_assets and args.require_assets:
                    failed = True
                results.append({"id": package["id"], "status": status, "files": len(tree.files),
                                "missing_assets": tree.missing_assets})
            except (RepositoryError, OSError) as exc:
                failed = True
                results.append({"id": package["id"], "status": "error", "error": str(exc)})
        if args.json:
            print(json_bytes(results).decode("utf-8"), end="")
        else:
            for result in results:
                if result["status"] == "error":
                    print(f"ERROR {result['id']}: {result['error']}")
                elif result["status"] == "needs-assets":
                    print(f"NEEDS-ASSETS {result['id']}: {result['files']} declared files; "
                          f"{len(result['missing_assets'])} external assets pending (--asset-archive)")
                else:
                    print(f"PASS {result['id']}: {result['files']} files")
        return 1 if failed else 0
    except (RepositoryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
