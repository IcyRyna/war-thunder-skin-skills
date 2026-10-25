"""Windows portable entry point and AI-friendly session discovery."""
from __future__ import annotations
import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import sys
import traceback
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'WT-Paint-Workbench'


def choose_folder():
    from ctypes import wintypes
    class BrowseInfo(ctypes.Structure):
        _fields_ = [('owner', wintypes.HWND), ('root', ctypes.c_void_p),
                    ('display', wintypes.LPWSTR), ('title', wintypes.LPCWSTR),
                    ('flags', wintypes.UINT), ('callback', ctypes.c_void_p),
                    ('param', wintypes.LPARAM), ('image', ctypes.c_int)]
    shell = ctypes.windll.shell32
    shell.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
    shell.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ctypes.windll.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ctypes.windll.ole32.CoInitialize(None)
    try:
        display = ctypes.create_unicode_buffer(32768)
        info = BrowseInfo(None, None, ctypes.cast(display, wintypes.LPWSTR),
                          '选择战雷安装目录（包含 content 和 launcher.exe / win64）', 0x41, None, 0, 0)
        item = shell.SHBrowseForFolderW(ctypes.byref(info))
        if not item:
            return None
        try:
            path = ctypes.create_unicode_buffer(32768)
            if not shell.SHGetPathFromIDListW(item, path):
                raise ValueError('请选择本机文件夹')
            return path.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(item)
    finally:
        ctypes.windll.ole32.CoUninitialize()


def game_directory(explicit=None, choose=False, interactive=True):
    from preview import discover_clients
    settings = DATA / 'settings.json'
    selected = explicit
    if not selected and settings.is_file():
        try:
            stored = json.loads(settings.read_text(encoding='utf-8')).get('game_dir')
            if stored and discover_clients(stored):
                selected = stored
        except (OSError, ValueError):
            pass
    candidates = discover_clients(selected)
    if not choose and len(candidates) == 1:
        return candidates[0]
    if not interactive:
        return None
    print('请选择战雷安装文件夹。取消后仍可直接打开 GLB 和已有工程。', flush=True)
    while True:
        selected = choose_folder()
        if not selected:
            return None
        try:
            discover_clients(selected)
        except ValueError as error:
            ctypes.windll.user32.MessageBoxW(None, str(error), '战雷目录未识别', 0x30)
            continue
        settings.write_text(json.dumps({'game_dir': selected}, ensure_ascii=False, indent=2), encoding='utf-8')
        return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description='战雷涂装工作台：双击启动，也可供 AI 命令行调用')
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('--choose-game', action='store_true')
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='准备依赖并完整检查，不启动网页')
    args = parser.parse_args(argv)
    DATA.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('便携包需要 Windows 10/11 x64；其他系统可使用源码的预览功能')
    # Lock the application files while dependencies are being installed or used.
    # A second double click opens the current session instead of another server.
    import msvcrt
    instance = (ROOT / 'runtime/instance.lock').open('a+b')
    instance.seek(0)
    if instance.read(1) == b'':
        instance.write(b'0'); instance.flush()
    instance.seek(0)
    try:
        msvcrt.locking(instance.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print('工作台已经启动；请使用原窗口。正在准备依赖时请稍候。', flush=True)
        session_file = ROOT / 'runtime/session.json'
        if not args.no_browser and session_file.is_file():
            session = json.loads(session_file.read_text(encoding='utf-8'))
            if session.get('url', '').startswith('http://127.0.0.1:'):
                webbrowser.open(session['url'])
        instance.close()
        return 0
    session_file = ROOT / 'runtime/session.json'
    try:
        session_file.unlink(missing_ok=True)
        from portable import ensure_dependencies, check_dependencies
        print('战雷涂装工作台 · 本地版\n首次启动需要联网；依赖准备完成后可离线使用。', flush=True)
        ensure_dependencies()
        checked = check_dependencies()
        if args.check:
            print(json.dumps({'ok': True, 'runtime': sys.executable, 'dependencies': checked}, ensure_ascii=False), flush=True)
            return 0
        from preview import serve
        game = game_directory(args.game_dir, args.choose_game, not args.no_browser)
        print('提醒：制作前先告诉 AI「可以使用本地涂装工作台预览模型和检查涂装」，详见 给AI的说明.md。', flush=True)
        print('保持此窗口打开。结束时按 Ctrl+C；导入工程保存在 ' + str(DATA / 'imports'), flush=True)
        def ready(url):
            session_file.write_text(json.dumps({'url': url, 'pid': os.getpid(), 'game_dir': game}, ensure_ascii=False, indent=2), encoding='utf-8')
            if not args.no_browser:
                webbrowser.open(url)
        serve(args.scene, args.port, DATA / 'imports', game,
              ROOT / 'extractor/wt_assets.py', on_ready=ready)
        return 0
    finally:
        session_file.unlink(missing_ok=True)
        instance.seek(0)
        msvcrt.locking(instance.fileno(), msvcrt.LK_UNLCK, 1)
        instance.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        DATA.mkdir(parents=True, exist_ok=True)
        log = DATA / 'startup-error.log'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        print(f'启动失败：{error}\n诊断日志：{log}\n检查网络，或把整个包解压到可写文件夹后重新双击。', file=sys.stderr, flush=True)
        raise SystemExit(1)
