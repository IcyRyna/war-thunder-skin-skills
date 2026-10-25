"""Build the Windows x64 one-click ZIP from tracked source + pinned Python."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portable import download, unpack


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--python-zip', type=Path)
    args = parser.parse_args()
    lock = json.loads((ROOT / 'portable-lock.json').read_text(encoding='utf-8'))
    files = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '.']).decode('utf-8').split('\0')
    with tempfile.TemporaryDirectory(prefix='wt-workbench-build-') as scratch:
        scratch = Path(scratch)
        package = scratch / 'WT-Paint-Workbench'
        package.mkdir()
        for name in files:
            if not name or name.startswith(('tests/', 'runtime/', 'extractor/vendor/', 'extractor/.venv/')):
                continue
            source = ROOT / name
            if source.suffix in ('.pyc', '.pyo') or '__pycache__' in source.parts:
                continue
            if source.is_file() and not source.is_symlink():
                target = package / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        shutil.copyfile(ROOT.parents[1] / 'LICENSE', package / 'LICENSE')
        archive = scratch / 'python.zip'
        if args.python_zip:
            from portable import sha256
            if sha256(args.python_zip) != lock['python']['sha256']:
                raise ValueError('Python 运行时校验失败')
            shutil.copyfile(args.python_zip, archive)
        else:
            download(lock['python'], archive)
        unpack(archive, package / 'runtime')
        # Isolated embedded Python does not add a script's parent automatically.
        # List every first-party CLI module directory for extraction subprocesses.
        (package / 'runtime/python312._pth').write_text('python312.zip\n.\n..\n../extractor\n../tools\npackages\n', encoding='ascii')
        for name, extra in [('启动工作台.cmd', ''), ('选择战雷目录.cmd', '--choose-game'), ('检查运行环境.cmd', '--check')]:
            text = '@echo off\r\nchcp 65001 >nul\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
            text += 'if not exist "%~dp0runtime\\python.exe" (\r\n  echo 请先完整解压 ZIP，再双击启动。\r\n  pause\r\n  exit /b 1\r\n)\r\n'
            text += f'"%~dp0runtime\\python.exe" -B -X utf8 "%~dp0launcher.py" {extra} %*\r\n'
            text += 'if errorlevel 1 (\r\n  echo 启动失败，详情见上方提示。\r\n  pause\r\n  exit /b 1\r\n)\r\n'
            if extra == '--check':
                text += 'pause\r\n'
            (package / name).write_bytes(text.encode('utf-8'))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            raise FileExistsError('输出已存在，请使用新的包路径')
        with zipfile.ZipFile(args.out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for file in sorted(package.rglob('*')):
                if file.is_file():
                    output.write(file, 'WT-Paint-Workbench/' + file.relative_to(package).as_posix())
        print(json.dumps({'ok': True, 'zip': str(args.out.resolve()), 'bytes': args.out.stat().st_size}))


if __name__ == '__main__':
    main()
