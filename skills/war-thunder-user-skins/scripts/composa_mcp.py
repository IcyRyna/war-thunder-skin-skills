#!/usr/bin/env python3
"""Call the installed Composa STDIO MCP bridge without changing Codex config.

List live tool schemas by default. --calls reads a JSON array of objects with
name and arguments, runs them sequentially, and stops at the first tool error.
Rendered MCP images are saved to --out, never printed as base64. This client
respects Composa's Help > Allow AI Control gate and does not enable it itself.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

MAX_MESSAGE = 64 * 1024 * 1024


def resolve_executable(explicit: Path | None = None) -> Path:
    """Resolve a configured executable before checking common install locations."""
    configured = explicit or os.environ.get("COMPOSA_EXE")
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_file():
            raise ValueError(f"Composa executable not found: {candidate}")
        return candidate.resolve()
    located = shutil.which("composa")
    if located:
        return Path(located).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        install_root = Path(local_app_data) / "Programs" / "Composa"
        candidates = sorted(install_root.glob("**/composa.exe"))
        if len(candidates) == 1:
            return candidates[0].resolve()
        if len(candidates) > 1:
            raise ValueError("Multiple Composa installations found; use --exe or COMPOSA_EXE")
    raise ValueError("Composa executable not found; use --exe or COMPOSA_EXE")


class McpError(RuntimeError):
    pass


class StdioMcp:
    def __init__(self, executable: Path, launch: bool, timeout: float, stderr_path: Path):
        self.timeout = timeout
        self.identifier = 0
        self.stopping = threading.Event()
        self.responses: queue.Queue = queue.Queue(maxsize=200)
        self.stderr = stderr_path.open("wb")
        command = [str(executable), "--mcp"] + (["--launch"] if launch else [])
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.stderr,
                                            bufsize=0,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except BaseException:
            self.stderr.close()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        try:
            assert self.process.stdout is not None
            pending = bytearray()
            while not self.stopping.is_set():
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    self.responses.put(McpError("Composa bridge closed its STDIO stream"), timeout=1)
                    return
                pending.extend(chunk)
                if len(pending) > MAX_MESSAGE:
                    raise McpError("MCP message exceeds 64 MiB")
                while True:
                    end = pending.find(b"\n")
                    if end < 0:
                        break
                    line = bytes(pending[:end])
                    del pending[:end + 1]
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise McpError("MCP message is not an object")
                    self.responses.put(value, timeout=1)
        except (OSError, ValueError, McpError, queue.Full) as exc:
            if self.stopping.is_set():
                return
            try:
                self.responses.put(exc, timeout=1)
            except queue.Full:
                return

    def send(self, value: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self.process.stdin.write(encoded)
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> Any:
        self.identifier += 1
        identifier = self.identifier
        self.send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError(f"Timed out after {self.timeout:g}s waiting for {method}")
            try:
                message = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise McpError(f"Timed out waiting for {method}") from exc
            if isinstance(message, BaseException):
                raise McpError(str(message)) from message
            if "method" in message:
                if "id" in message:
                    if message["method"] == "ping":
                        self.send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                    else:
                        self.send({"jsonrpc": "2.0", "id": message["id"],
                                   "error": {"code": -32601, "message": "Client capability not implemented"}})
                continue
            if message.get("id") != identifier:
                raise McpError("Received a response for an unexpected request ID")
            if "error" in message:
                raise McpError(json.dumps(message["error"], ensure_ascii=False))
            if "result" not in message:
                raise McpError("JSON-RPC response has no result")
            return message["result"]

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                             "clientInfo": {"name": "war-thunder-skin-workshop", "version": "1.0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def close(self) -> None:
        self.stopping.set()
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=0.25)
        if self.reader.is_alive() and os.name == "nt" and self.reader.native_id is not None:
            # A GUI launched by the bridge can inherit a pipe handle. Cancel our
            # own blocking reader before closing the CRT file descriptor.
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenThread.restype = wintypes.HANDLE
            kernel.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
            kernel.CancelSynchronousIo.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.OpenThread(0x0001, False, self.reader.native_id)
            if handle:
                try:
                    kernel.CancelSynchronousIo(handle)
                finally:
                    kernel.CloseHandle(handle)
            self.reader.join(timeout=2)
        if self.process.stdout and not self.reader.is_alive():
            self.process.stdout.close()
        self.stderr.close()


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def materialize_images(value: Any, out: Path, prefix: str) -> Any:
    counter = 0

    def visit(item: Any):
        nonlocal counter
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, dict):
            return item
        if item.get("type") == "image" and isinstance(item.get("data"), str):
            counter += 1
            mime = item.get("mimeType", "application/octet-stream")
            suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".bin")
            path = out / f"{prefix}-image-{counter:02d}{suffix}"
            pixels = base64.b64decode(item["data"], validate=True)
            if len(pixels) > MAX_MESSAGE:
                raise McpError("Rendered image exceeds 64 MiB")
            path.write_bytes(pixels)
            return {key: val for key, val in item.items() if key != "data"} | {"saved_path": str(path)}
        return {key: visit(child) for key, child in item.items()}

    return visit(value)


def validate_required_arguments(tool: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Preflight required fields; the server remains authoritative for full schema validation."""
    required = tool.get("inputSchema", {}).get("required", [])
    missing = [key for key in required if key not in arguments]
    if missing:
        raise McpError(f"Tool {tool['name']} is missing required argument(s): {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="Composa executable; defaults to COMPOSA_EXE or discovery")
    parser.add_argument("--launch", action="store_true", help="Use Composa's own --launch option")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--calls", type=Path, help="JSON array of tool calls; omitted to list live tools")
    parser.add_argument("--timeout", type=float, default=30, help="Seconds per request (1-60)")
    args = parser.parse_args()
    client = None
    try:
        if not 1 <= args.timeout <= 60:
            raise ValueError("--timeout must be between 1 and 60 seconds")
        args.exe = resolve_executable(args.exe)
        calls = json.loads(args.calls.read_text(encoding="utf-8-sig")) if args.calls else []
        if not isinstance(calls, list) or len(calls) > 100:
            raise ValueError("--calls must contain a JSON array with at most 100 calls")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("arguments", {}), dict):
                raise ValueError("Each call must have name and an arguments object")
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=True)
        client = StdioMcp(args.exe.resolve(), args.launch, args.timeout, out / "bridge-stderr.log")
        initialized = client.initialize()
        save_json(out / "server.json", initialized)
        if args.launch:
            # The bridge launches/connects asynchronously; allow the UI process
            # to start before accepting its initial empty tool list as final.
            time.sleep(3)
        live_tools, cursor = [], None
        while True:
            page = client.request("tools/list", {"cursor": cursor} if cursor else {})
            live_tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor")
            if not cursor:
                break
        save_json(out / "tools.json", {"tools": live_tools})
        print(json.dumps({"server": initialized.get("serverInfo"), "tool_count": len(live_tools),
                          "tool_names": [t["name"] for t in live_tools], "output": str(out)}, ensure_ascii=False), flush=True)
        if not live_tools:
            raise McpError("No tools: open Composa and enable Help > Allow AI Control, then reconnect")
        known = {t["name"]: t for t in live_tools}
        # Validate the whole batch before any edit; a late missing parameter
        # should not leave an otherwise avoidable partially applied design.
        for call in calls:
            if call["name"] not in known:
                raise McpError(f"Tool is not in the live schema: {call['name']}")
            validate_required_arguments(known[call["name"]], call.get("arguments", {}))
        for index, call in enumerate(calls, 1):
            if call["name"] not in known:
                raise McpError(f"Tool is not in the live schema: {call['name']}")
            validate_required_arguments(known[call["name"]], call.get("arguments", {}))
            result = client.request("tools/call", {"name": call["name"], "arguments": call.get("arguments", {})})
            saved = materialize_images(result, out, f"{index:02d}-{call['name']}")
            save_json(out / f"{index:02d}-{call['name']}.json", saved)
            texts = [part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"]
            print(json.dumps({"step": index, "name": call["name"], "isError": bool(result.get("isError")),
                              "text": "\n".join(texts)[:1800]}, ensure_ascii=False), flush=True)
            if result.get("isError"):
                raise McpError(f"Tool {call['name']} returned an error; batch stopped, see saved result")
        return 0
    except (OSError, ValueError, McpError, subprocess.SubprocessError) as exc:
        print(f"Composa MCP failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
