"""Verified, application-local dependency setup; no pip, git or system install."""
from __future__ import annotations
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            result.update(block)
    return result.hexdigest()


def download(row, destination):
    if not row['url'].startswith('https://'):
        raise ValueError('依赖下载必须使用 HTTPS')
    last_error = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(row['url'], headers={'User-Agent': 'WT-Paint-Workbench/1.0'})
            with urllib.request.urlopen(request, timeout=60) as source, destination.open('wb') as target:
                size = 0
                for block in iter(lambda: source.read(1048576), b''):
                    size += len(block)
                    if size > row['bytes']:
                        raise ValueError('依赖大小超过已固定的值')
                    target.write(block)
            if size != row['bytes'] or sha256(destination) != row['sha256']:
                raise ValueError('依赖校验失败，未安装；请重试或更换网络')
            return
        except (OSError, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(f"无法下载 {row['name']}：{last_error}。检查网络后重新双击启动，已完成的安装会保留。")


def unpack(archive, destination, prefix=''):
    """Extract only bounded regular files; reject traversal and archive links."""
    total = 0
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            name = info.filename
            part = PurePosixPath(name)
            if '\\' in name or part.is_absolute() or '..' in part.parts or ':' in name:
                raise ValueError('依赖压缩包含不安全路径')
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('依赖压缩包不允许符号链接')
            total += info.file_size
            if total > 1024 * 1024 * 1024:
                raise ValueError('依赖解压大小超过限制')
            if prefix and not name.startswith(prefix):
                continue
            relative = name[len(prefix):] if prefix else name
            if not relative or info.is_dir():
                continue
            # A wheel's importable files live at its root. These fixed wheels
            # contain no scripts/data relocation that requires pip installation.
            target = destination.joinpath(*PurePosixPath(relative).parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('依赖解压越界')
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as stream, target.open('wb') as output:
                shutil.copyfileobj(stream, output)


def ensure_dependencies(root=ROOT):
    lock_path = root / 'portable-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    fingerprint = sha256(lock_path)
    marker = root / 'runtime/dependencies-ready.json'
    if marker.is_file():
        try:
            if json.loads(marker.read_text(encoding='utf-8')).get('lock_sha256') == fingerprint:
                check_dependencies()
                return
        except (OSError, ValueError, ImportError, RuntimeError):
            pass
    packages = root / 'runtime/packages'
    vendor = root / 'extractor/vendor/dagor-asset-explorer'
    root.joinpath('runtime').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wt-preview-deps-') as scratch:
        scratch = Path(scratch)
        staged = scratch / 'packages'
        staged.mkdir()
        for index, row in enumerate(lock['wheels'], 1):
            print(f"首次准备 {index}/{len(lock['wheels']) + 1}：{row['name']} {row['version']}（仅本工具使用）", flush=True)
            archive = scratch / 'dependency.zip'
            download(row, archive)
            unpack(archive, staged)
        row = lock['decoder']
        print(f"首次准备 {len(lock['wheels']) + 1}/{len(lock['wheels']) + 1}：固定版模型解码器", flush=True)
        archive = scratch / 'decoder.zip'
        download(row, archive)
        staged_vendor = scratch / 'decoder'
        for folder in ('src/', 'lib/'):
            unpack(archive, staged_vendor / folder, row['prefix'] + folder)
        for filename in ('readme.md', 'requirements.txt'):
            with zipfile.ZipFile(archive) as source:
                staged_vendor.joinpath(filename).write_bytes(source.read(row['prefix'] + filename))
        # Move the verified contents only after every dependency was obtained.
        # Existing files belong to this tool; never remove a user's project.
        packages.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, packages, dirs_exist_ok=True)
        shutil.copytree(staged_vendor, vendor, dirs_exist_ok=True)
    importlib.invalidate_caches()
    check_dependencies()
    marker.write_text(json.dumps({'lock_sha256': fingerprint}, indent=2), encoding='utf-8')


def check_dependencies():
    for folder in (ROOT / 'runtime/packages', ROOT / 'extractor'):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    import PIL.Image
    import zstandard
    from PyQt5 import QtCore, QtWidgets
    from extractor import dae_backend
    dae_backend.backend()
    return {'pillow': PIL.__version__, 'zstandard': zstandard.__version__,
            'pyqt': QtCore.PYQT_VERSION_STR, 'decoder': dae_backend.PINNED_DAE}
