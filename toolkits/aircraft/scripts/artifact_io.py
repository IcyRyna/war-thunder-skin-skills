"""Non-overwriting, recoverable file-set commits using only the standard library.

Declare every output before entering the transaction.  Files with the same final
parent share a private staging directory, so relative BLK/texture references can
be validated there.  This is a recoverable multi-file commit, not a filesystem
snapshot: readers must wait for the caller's success receipt before consuming a
whole set.  Existing files and concurrent replacements are never overwritten.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Iterable
import uuid


class ArtifactError(RuntimeError):
    """An unsafe destination or incomplete artifact transaction."""


def _key(path: Path) -> str:
    # The package targets Windows.  Apply its case-insensitive destination
    # policy on other hosts too, so portable validation cannot miss an alias.
    return os.path.normcase(str(path)).casefold()


def _exists(path: Path) -> bool:
    return os.path.lexists(path)


def _within(path: Path, parent: Path) -> bool:
    return _key(path) == _key(parent) or _key(parent) in {
        _key(item) for item in path.parents
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Path) -> tuple[int, int]:
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino


class ArtifactTransaction:
    """Stage a declared file set and publish it without replacing any target.

    Preflight errors intentionally produce no files.  Errors after staging starts
    leave a unique JSON failure receipt.  ``commit`` is explicit; leaving a clean
    context without it is an error.  A committed set stays committed if unrelated
    work subsequently raises inside the context.
    """

    def __init__(
        self,
        outputs: Iterable[Path],
        inputs: Iterable[Path] = (),
        *,
        label: str = "artifact",
        failure_directory: Path | None = None,
    ) -> None:
        self.label = str(label)
        self.transaction_id = uuid.uuid4().hex
        self._declared = [Path(item).absolute() for item in outputs]
        if not self._declared:
            raise ArtifactError("At least one output file must be declared")
        self._input_declared = [Path(item).absolute() for item in inputs]
        self.outputs = tuple(item.resolve() for item in self._declared)
        self.inputs = tuple(item.resolve(strict=True) for item in self._input_declared)
        self.failure_directory = (
            Path(failure_directory).absolute().resolve()
            if failure_directory is not None
            else self.outputs[0].parent / ".artifact-failures"
        )
        self.failure_receipt: Path | None = None
        self.failure_record: dict | None = None
        self._by_key = {_key(item): item for item in self.outputs}
        self._roots: dict[Path, tuple[Path, tuple[int, int]]] = {}
        self._staged: dict[Path, Path] = {}
        self._created_dirs: list[tuple[Path, tuple[int, int]]] = []
        self._published: list[dict] = []
        self._cleanup_warnings: list[str] = []
        self._state = "new"
        self._started = False
        self._preflight()

    def _preflight(self) -> None:
        if len(self._by_key) != len(self.outputs):
            raise ArtifactError("Duplicate or aliased output paths")
        for raw, output in zip(self._declared, self.outputs):
            if raw.resolve() != output:
                raise ArtifactError(f"Output path resolution changed: {raw}")
            if _exists(raw) or _exists(output):
                raise FileExistsError(f"Output already exists: {raw}")
            for source in self.inputs:
                if _key(output) == _key(source):
                    raise ArtifactError(f"Output aliases an input: {raw}")
                if source.is_dir() and _within(output, source):
                    raise ArtifactError(f"Output is inside a read-only input directory: {raw}")
            for other in self.outputs:
                if other != output and _within(output, other):
                    raise ArtifactError(f"Output file is another output's parent: {other}")
        # Hard links are existing files, so the existence check above also
        # rejects links whose names have no resemblance to their input name.
        for source in self.inputs:
            if source.is_dir() and _within(self.failure_directory, source):
                raise ArtifactError("Failure receipts cannot be written inside an input directory")
            if _key(source) == _key(self.failure_directory):
                raise ArtifactError("Failure receipt directory aliases an input")
        for output in self.outputs:
            if _within(self.failure_directory, output):
                raise ArtifactError("Failure receipt directory is inside a declared output file")
        existing_parent = self.failure_directory
        while not _exists(existing_parent):
            existing_parent = existing_parent.parent
        if not existing_parent.is_dir():
            raise ArtifactError(f"Failure receipt parent is not a directory: {existing_parent}")

    def __enter__(self) -> "ArtifactTransaction":
        if self._state != "new":
            raise ArtifactError("An artifact transaction cannot be entered twice")
        self._preflight()
        self._state = "active"
        self._started = True
        return self

    def _mkdirs(self, parent: Path) -> None:
        missing = []
        cursor = parent
        while not _exists(cursor):
            missing.append(cursor)
            cursor = cursor.parent
        if not cursor.is_dir():
            raise NotADirectoryError(str(cursor))
        for directory in reversed(missing):
            try:
                directory.mkdir()
            except FileExistsError:
                if not directory.is_dir():
                    raise
            else:
                self._created_dirs.append((directory, _identity(directory)))

    def _destination(self, value: Path) -> Path:
        key = _key(Path(value).absolute().resolve())
        try:
            return self._by_key[key]
        except KeyError as error:
            raise ArtifactError(f"Undeclared output: {value}") from error

    def stage(self, final_path: Path) -> Path:
        """Return a private path with the final basename and suffix."""
        if self._state != "active":
            raise ArtifactError("stage() requires an active, uncommitted transaction")
        output = self._destination(final_path)
        if output in self._staged:
            return self._staged[output]
        self._started = True
        # Recheck before creating directories in case an ancestor was replaced.
        raw = self._declared[self.outputs.index(output)]
        if raw.resolve() != output or output.parent.resolve() != output.parent:
            raise ArtifactError(f"Destination ancestry changed: {raw}")
        if _exists(output):
            raise FileExistsError(f"Output appeared after preflight: {output}")
        self._mkdirs(output.parent)
        if output.parent not in self._roots:
            root = Path(tempfile.mkdtemp(prefix=f".artifact-{self.transaction_id}-", dir=output.parent))
            self._roots[output.parent] = (root, _identity(root))
        root, _ = self._roots[output.parent]
        temporary = root / output.name
        self._staged[output] = temporary
        return temporary

    def _check_stages(self) -> dict[Path, str]:
        hashes = {}
        for raw, output in zip(self._declared, self.outputs):
            if raw.resolve() != output or output.parent.resolve() != output.parent:
                raise ArtifactError(f"Destination ancestry changed: {raw}")
            if _exists(output):
                raise FileExistsError(f"Output appeared before commit: {output}")
            staged = self._staged.get(output)
            if staged is None:
                raise ArtifactError(f"No staged file for declared output: {output}")
            root, root_identity = self._roots[output.parent]
            self._check_root(root, root_identity, output.parent)
            if staged.parent != root or staged.resolve() != staged:
                raise ArtifactError(f"Staged file escaped its private directory: {staged}")
            if not staged.is_file() or staged.is_symlink():
                raise ArtifactError(f"Staged output is missing or not a regular file: {staged}")
            for source in self.inputs:
                if source.is_file() and os.path.samefile(staged, source):
                    raise ArtifactError(f"Staged output is hard-linked to an input: {staged}")
            hashes[output] = _sha256(staged)
        return hashes

    def _publish(self, staged: Path, output: Path, digest: str) -> None:
        # link() is an atomic, non-overwriting install on NTFS and POSIX local
        # filesystems.  The O_EXCL fallback supports filesystems without links.
        try:
            os.link(staged, output)
        except OSError as error:
            fallback_errors = {
                errno.EXDEV, errno.EPERM, errno.ENOSYS, errno.EACCES,
                getattr(errno, "ENOTSUP", errno.EPERM),
                getattr(errno, "EOPNOTSUPP", errno.EPERM),
            }
            if error.errno not in fallback_errors:
                raise
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            published = {"path": output, "identity": _identity(output), "sha256": None}
            self._published.append(published)
            try:
                with os.fdopen(descriptor, "wb") as destination, staged.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        destination.write(block)
                    destination.flush()
                    os.fsync(destination.fileno())
                published["sha256"] = _sha256(output)
            except BaseException:
                # Record the partial bytes that we own before rollback.  A
                # later concurrent edit will differ and therefore be retained.
                if _exists(output) and _identity(output) == published["identity"]:
                    published["sha256"] = _sha256(output)
                raise
        else:
            self._published.append({"path": output, "identity": _identity(output), "sha256": digest})
        if self._published[-1]["sha256"] != digest:
            raise ArtifactError(f"Published bytes changed during commit: {output}")

    def commit(self) -> None:
        if self._state != "active":
            raise ArtifactError("commit() requires an active transaction")
        self._started = True
        try:
            hashes = self._check_stages()
            for output in self.outputs:
                self._publish(self._staged[output], output, hashes[output])
            # Catch replacement or in-place mutation while another file in the
            # set was being published, before reporting a successful set.
            for published in self._published:
                output = published["path"]
                if (not _exists(output) or _identity(output) != published["identity"]
                        or _sha256(output) != published["sha256"]):
                    raise ArtifactError(f"Published output was changed concurrently: {output}")
        except BaseException as error:
            self._fail(error)
            raise
        self._state = "committed"
        self._cleanup_roots()

    @staticmethod
    def _check_root(root: Path, identity: tuple[int, int], parent: Path) -> None:
        if (root.is_symlink() or root.resolve() != root or root.parent != parent
                or parent.resolve() != parent or _identity(root) != identity):
            raise ArtifactError(f"Private staging directory identity changed; retained: {root}")

    def _cleanup_roots(self) -> None:
        for parent, (root, identity) in reversed(tuple(self._roots.items())):
            if not _exists(root):
                continue
            try:
                self._check_root(root, identity, parent)
                shutil.rmtree(root)
            except OSError as error:
                self._cleanup_warnings.append(f"Retained staging directory {root}: {error}")
            except ArtifactError as error:
                self._cleanup_warnings.append(str(error))

    def _rollback(self) -> None:
        for published in reversed(self._published):
            path = published["path"]
            try:
                if not _exists(path):
                    continue
                if (path.is_symlink() or path.resolve() != path
                        or _identity(path) != published["identity"]
                        or published["sha256"] is None
                        or _sha256(path) != published["sha256"]):
                    self._cleanup_warnings.append(f"Retained concurrently changed output: {path}")
                    continue
                path.unlink()
            except OSError as error:
                self._cleanup_warnings.append(f"Could not remove owned output {path}: {error}")

    def _write_failure(self, error: BaseException) -> None:
        payload = {
            "schema_version": 1,
            "transaction_id": self.transaction_id,
            "label": self.label,
            "state": "failed",
            "utc": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "error": str(error),
            "outputs": [str(item) for item in self.outputs],
            "inputs": [str(item) for item in self.inputs],
            "published_before_rollback": [str(item["path"]) for item in self._published],
            "cleanup_warnings": self._cleanup_warnings,
        }
        self.failure_record = payload
        try:
            # A changed receipt directory must not redirect writes into a new
            # location or into an input tree.
            if self.failure_directory.resolve() != self.failure_directory:
                raise ArtifactError("Failure receipt directory ancestry changed")
            self._mkdirs(self.failure_directory)
            target = self.failure_directory / f"{self.transaction_id}.failure.json"
            with target.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            self.failure_receipt = target
        except BaseException as receipt_error:
            # Never mask the real I/O failure.  Keep the inability to record it
            # visible on both the exception and transaction object.
            message = f"Failure receipt could not be saved: {receipt_error}"
            self._cleanup_warnings.append(message)
            if hasattr(error, "add_note"):
                error.add_note(message)

    def _cleanup_empty_dirs(self) -> None:
        for directory, identity in reversed(self._created_dirs):
            try:
                if (directory.is_symlink() or directory.resolve() != directory
                        or _identity(directory) != identity):
                    continue
                directory.rmdir()
            except (OSError, FileNotFoundError):
                pass  # Nonempty directories can contain concurrent user files.

    def _fail(self, error: BaseException) -> None:
        if self._state == "failed":
            return
        self._state = "failed"
        self._rollback()
        self._cleanup_roots()
        if self._started:
            self._write_failure(error)
        self._cleanup_empty_dirs()

    def __exit__(self, error_type, error, traceback) -> bool:
        if self._state == "committed":
            return False
        if error is not None:
            self._fail(error)
            return False
        if self._state == "failed":
            return False
        missing_commit = ArtifactError("Artifact transaction exited without commit()")
        self._fail(missing_commit)
        raise missing_commit
