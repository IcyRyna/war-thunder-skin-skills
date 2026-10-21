#!/usr/bin/env python3
"""Call the installed Composa STDIO MCP bridge without changing Codex config.

List live tool schemas by default. --calls reads a JSON array of objects with
name and arguments, runs them sequentially, and stops at the first tool error.
Rendered MCP images are saved to --out, never printed as base64. This client
respects Composa's Help > Allow AI Control gate and does not enable it itself.
Each invocation requires a new or empty --out directory. session.json and the
attempts/responses subdirectories preserve recovery evidence; uncertain calls
are never retried automatically.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any
import uuid
import zlib

MAX_MESSAGE = 64 * 1024 * 1024
MAX_PNG_SCANLINES = 256 * 1024 * 1024


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


class McpTimeoutError(McpError):
    """The bridge did not confirm whether a request completed."""


class McpTransportError(McpError):
    """The request or its response could not be transported reliably."""


class McpRpcError(McpError):
    """A JSON-RPC error response was received from the bridge."""

    def __init__(self, error: Any):
        self.error = error
        super().__init__(json.dumps(error, ensure_ascii=False))


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
        try:
            self.send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        except (OSError, ValueError) as exc:
            raise McpTransportError(f"Could not send {method}: {exc}") from exc
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpTimeoutError(f"Timed out after {self.timeout:g}s waiting for {method}")
            try:
                message = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise McpTimeoutError(f"Timed out waiting for {method}") from exc
            if isinstance(message, BaseException):
                raise McpTransportError(str(message)) from message
            if "method" in message:
                if "id" in message:
                    if message["method"] == "ping":
                        self.send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                    else:
                        self.send({"jsonrpc": "2.0", "id": message["id"],
                                   "error": {"code": -32601, "message": "Client capability not implemented"}})
                continue
            if message.get("id") != identifier:
                raise McpTransportError("Received a response for an unexpected request ID")
            if "error" in message:
                raise McpRpcError(message["error"])
            if "result" not in message:
                raise McpTransportError("JSON-RPC response has no result")
            return message["result"]

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                             "clientInfo": {"name": "photoshop-tools", "version": "1.0"}})
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
    """Replace our own receipt atomically, preserving its last complete version."""
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_tool_name(name: str) -> str:
    # Live tool names are not trusted as filesystem paths.
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name).strip(".")[:80] or "tool"


def claim_output_directory(out: Path, session: dict[str, Any]) -> None:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("--out must be a new or empty directory; use a new session directory")
    out.mkdir(parents=True, exist_ok=True)
    # An exclusive receipt also prevents two simultaneous clients from claiming
    # the same empty directory after both performed the preliminary check.
    with (out / "session.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(session, ensure_ascii=False, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def validate_png(pixels: bytes) -> dict[str, int]:
    """Validate static, non-interlaced 8-bit PNG pixel streams without a codec.

    This deliberately narrow profile covers Composa's RGB/RGBA renders as well
    as grayscale with/without alpha. Indexed, interlaced and animated PNGs are
    explicitly unsupported rather than accepted without complete validation.
    """
    if len(pixels) > MAX_MESSAGE:
        raise McpError("Rendered image exceeds 64 MiB")
    if pixels[:8] != b"\x89PNG\r\n\x1a\n":
        raise McpError("Rendered image has an invalid PNG signature")
    offset = 8
    header = None
    compressed = bytearray()
    idat_seen = False
    idat_closed = False
    palette_seen = False
    transparency_seen = False
    ended = False
    channels = 0
    while offset < len(pixels):
        if len(pixels) - offset < 12:
            raise McpError("Truncated PNG chunk")
        length = struct.unpack_from(">I", pixels, offset)[0]
        kind = pixels[offset + 4:offset + 8]
        if length > 0x7fffffff or length > len(pixels) - offset - 12:
            raise McpError("Invalid or truncated PNG chunk length")
        if any(not (65 <= char <= 90 or 97 <= char <= 122) for char in kind) or kind[2] & 0x20:
            raise McpError("Invalid PNG chunk type")
        payload = pixels[offset + 8:offset + 8 + length]
        checksum = struct.unpack_from(">I", pixels, offset + 8 + length)[0]
        if zlib.crc32(payload, zlib.crc32(kind)) & 0xffffffff != checksum:
            raise McpError(f"PNG chunk {kind.decode('ascii')} has an invalid CRC")
        offset += length + 12
        if header is None and kind != b"IHDR":
            raise McpError("PNG IHDR must be the first chunk")
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise McpError("Invalid or duplicate PNG IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not 1 <= width <= 32768 or not 1 <= height <= 32768:
                raise McpError("PNG dimensions must be between 1 and 32768")
            if depth != 8 or color not in {0, 2, 4, 6} or interlace != 0:
                raise McpError("Unsupported PNG profile: require static non-interlaced 8-bit grayscale, RGB, or alpha PNG")
            if compression != 0 or filtering != 0:
                raise McpError("Unsupported PNG compression or filter method")
            channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
            expected = (width * channels + 1) * height
            if expected > MAX_PNG_SCANLINES:
                raise McpError("PNG decompressed scanlines exceed 256 MiB")
            header = {"width": width, "height": height, "bit_depth": depth, "color_type": color}
        elif kind == b"PLTE":
            if palette_seen or idat_seen or header["color_type"] in {0, 4} or not length or length % 3 or length > 768:
                raise McpError("Invalid PNG PLTE")
            palette_seen = True
        elif kind == b"tRNS":
            color = header["color_type"]
            if transparency_seen or idat_seen or color not in {0, 2} or length != {0: 2, 2: 6}.get(color):
                raise McpError("Invalid PNG tRNS")
            if any(value > 255 for value in struct.unpack(">" + "H" * (length // 2), payload)):
                raise McpError("PNG tRNS exceeds 8-bit sample range")
            transparency_seen = True
        elif kind == b"IDAT":
            if idat_closed:
                raise McpError("PNG IDAT chunks must be consecutive")
            idat_seen = True
            compressed.extend(payload)
        elif kind == b"IEND":
            if length or not idat_seen or offset != len(pixels):
                raise McpError("Invalid PNG IEND or trailing bytes")
            ended = True
            break
        elif kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise McpError("Animated PNG is unsupported")
        elif not kind[0] & 0x20:
            raise McpError(f"Unsupported critical PNG chunk: {kind.decode('ascii')}")
        if idat_seen and kind != b"IDAT":
            idat_closed = True
    if header is None or not ended:
        raise McpError("PNG is missing IHDR, IDAT or IEND")
    try:
        decoder = zlib.decompressobj()
        scanlines = decoder.decompress(compressed, expected + 1)
    except zlib.error as exc:
        raise McpError(f"Invalid PNG IDAT zlib stream: {exc}") from exc
    if len(scanlines) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise McpError("PNG IDAT stream is truncated, has trailing data, or has an incorrect scanline length")
    stride = header["width"] * channels + 1
    if any(filter_type > 4 for filter_type in scanlines[::stride]):
        raise McpError("PNG scanline has an invalid filter type")
    return header


def materialize_images(value: Any, out: Path, prefix: str) -> Any:
    counter = 0
    published: list[tuple[Path, tuple[int, int], str]] = []
    staged: list[tuple[Path, Path, tuple[int, int], str]] = []
    staging = None
    if safe_tool_name(prefix) != prefix:
        raise ValueError("Image prefix must be a plain filename component")

    def visit(item: Any):
        nonlocal counter, staging
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, dict):
            return item
        if item.get("type") == "image":
            counter += 1
            if item.get("mimeType") != "image/png" or not isinstance(item.get("data"), str):
                raise McpError("Only base64-encoded image/png responses are supported")
            path = out / f"{prefix}-image-{counter:02d}.png"
            pixels = base64.b64decode(item["data"], validate=True)
            validate_png(pixels)
            if staging is None:
                staging = Path(tempfile.mkdtemp(dir=out, prefix=".mcp-images-"))
            private_path = staging / path.name
            # Validate the entire response in a private directory before making
            # any images public; malformed later images cannot expose partials.
            with private_path.open("xb") as handle:
                identity = (os.fstat(handle.fileno()).st_dev, os.fstat(handle.fileno()).st_ino)
                staged.append((private_path, path, identity, hashlib.sha256(pixels).hexdigest()))
                handle.write(pixels)
                handle.flush()
                os.fsync(handle.fileno())
            return {key: val for key, val in item.items() if key != "data"} | {"saved_path": str(path)}
        return {key: visit(child) for key, child in item.items()}

    try:
        materialized = visit(value)
        for private_path, path, identity, digest in staged:
            # A hard link publishes a complete file atomically and refuses an
            # existing destination on Windows and POSIX alike.
            os.link(private_path, path)
            published.append((path, identity, digest))
        return materialized
    except BaseException:
        for path, identity, digest in published:
            try:
                status = path.lstat()
                if (status.st_dev, status.st_ino) == identity and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                    # Re-check identity after reading, preserving replacements
                    # and in-place third-party edits during publication.
                    current = path.lstat()
                    if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) == (status.st_dev, status.st_ino, status.st_mtime_ns, status.st_size):
                        path.unlink()
            except OSError:
                pass
        raise
    finally:
        # Remove only private paths with the identity we created. Unexpected
        # concurrent files are retained rather than recursively deleted.
        for private_path, _, identity, _ in staged:
            try:
                status = private_path.lstat()
                if (status.st_dev, status.st_ino) == identity:
                    private_path.unlink()
            except OSError:
                pass
        if staging is not None:
            try:
                staging.rmdir()
            except OSError:
                pass


def discover_tools(client, wait_seconds: float = 10.0) -> list[dict[str, Any]]:
    """Wait for asynchronous pipe attachment using read-only discovery requests."""
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        tools, cursor, seen = [], None, set()
        while True:
            page = client.request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(page, dict) or not isinstance(page.get("tools", []), list):
                raise McpError("Invalid tools/list response")
            tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen:
                raise McpError("Invalid or repeated tools/list cursor")
            seen.add(cursor)
        if tools or time.monotonic() >= deadline:
            return tools
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


def validate_required_arguments(tool: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Preflight required fields; the server remains authoritative for full schema validation."""
    schema = tool.get("inputSchema", {})
    if not isinstance(schema, dict):
        raise McpError(f"Tool {tool['name']} has an invalid input schema")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
        raise McpError(f"Tool {tool['name']} has invalid required fields")
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
    out = None
    session = None
    active_attempt = None
    request_started = False
    response_received = False
    exit_code = 1

    def persist_session() -> None:
        assert out is not None and session is not None
        session["updated_at"] = utc_now()
        save_json(out / "session.json", session)

    def persist_failure(exc: BaseException) -> None:
        if session is None or out is None:
            return
        if active_attempt is not None:
            if request_started and not response_received:
                # Even a transport failure during send can occur after a partial
                # write. Only inspecting the editor can resolve that uncertainty.
                active_attempt["state"] = "unknown_applied"
                active_attempt["application_state"] = "unknown_applied"
                active_attempt["automatic_retry_allowed"] = False
                session["state"] = "unknown_applied"
                session["recovery"] = "Inspect current editor document state in a new read-only session before deciding whether to issue another edit. Do not replay this batch."
            elif response_received:
                if active_attempt.get("state") not in {"tool_error_response", "rpc_error_response"}:
                    active_attempt["state"] = "materialization_failed"
                active_attempt["application_state"] = "response_received"
                session["state"] = "failed_after_response"
                session["recovery"] = "The original response was received. Inspect raw responses and current editor state; do not repeat edits to recover output files."
            else:
                active_attempt["state"] = "not_sent"
                active_attempt["application_state"] = "not_sent"
                session["state"] = "failed"
            active_attempt["error"] = {"type": type(exc).__name__, "message": str(exc)}
            active_attempt["finished_at"] = utc_now()
            try:
                save_json(out / active_attempt["attempt_path"], active_attempt)
            except (OSError, ValueError) as receipt_exc:
                print(f"Could not update attempt receipt: {receipt_exc}", file=sys.stderr, flush=True)
        else:
            session["state"] = "failed"
        session["error"] = {"type": type(exc).__name__, "message": str(exc)}
        session["finished_at"] = utc_now()
        try:
            persist_session()
        except (OSError, ValueError) as receipt_exc:
            # A full/unavailable disk may prevent the final update too. The
            # persisted pre-send attempt remains deliberately non-successful.
            print(f"Could not persist final session receipt: {receipt_exc}", file=sys.stderr, flush=True)
            print(json.dumps({"session_id": session["session_id"], "observed_state": session["state"],
                              "step": active_attempt.get("step") if active_attempt else None,
                              "recovery": session.get("recovery")}, ensure_ascii=False), file=sys.stderr, flush=True)

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
        candidate_out = args.out.resolve()
        session_value = {"schema_version": 1, "session_id": str(uuid.uuid4()), "created_at": utc_now(),
                         "state": "starting", "calls_file": str(args.calls.resolve()) if args.calls else None,
                         "planned_call_count": len(calls), "automatic_retry_allowed": False,
                         "calls": []}
        claim_output_directory(candidate_out, session_value)
        out, session = candidate_out, session_value
        (out / "attempts").mkdir()
        (out / "responses").mkdir()
        client = StdioMcp(args.exe.resolve(), args.launch, args.timeout, out / "bridge-stderr.log")
        session["state"] = "initializing"
        persist_session()
        initialized = client.initialize()
        if not isinstance(initialized, dict):
            raise McpError("Invalid initialize response")
        save_json(out / "server.json", initialized)
        if args.launch:
            # The bridge launches/connects asynchronously; allow the UI process
            # to start before accepting its initial empty tool list as final.
            time.sleep(3)
        session["state"] = "listing_tools"
        persist_session()
        live_tools = discover_tools(client, min(args.timeout, 10.0))
        save_json(out / "tools.json", {"tools": live_tools})
        if any(not isinstance(tool, dict) or not isinstance(tool.get("name"), str) for tool in live_tools):
            raise McpError("Invalid live tool schema")
        print(json.dumps({"server": initialized.get("serverInfo"), "tool_count": len(live_tools),
                          "tool_names": [t["name"] for t in live_tools], "output": str(out)}, ensure_ascii=False), flush=True)
        if not live_tools:
            raise McpError("No tools: open Composa and enable Help > Allow AI Control, then reconnect")
        known = {t["name"]: t for t in live_tools}
        session["state"] = "preflight"
        persist_session()
        # Validate the whole batch before any edit; a late missing parameter
        # should not leave an otherwise avoidable partially applied design.
        for call in calls:
            if call["name"] not in known:
                raise McpError(f"Tool is not in the live schema: {call['name']}")
            validate_required_arguments(known[call["name"]], call.get("arguments", {}))
        for index, call in enumerate(calls, 1):
            prefix = f"{index:02d}-{safe_tool_name(call['name'])}"
            request_started, response_received = False, False
            active_attempt = {"schema_version": 1, "session_id": session["session_id"],
                              "step": index, "name": call["name"], "arguments": call.get("arguments", {}),
                              "started_at": utc_now(), "state": "requesting",
                              "application_state": "unknown_until_response", "automatic_retry_allowed": False,
                              "attempt_path": f"attempts/{prefix}.json", "response_path": f"responses/{prefix}.json"}
            session["calls"].append(active_attempt)
            session["state"] = "running"
            # Both records must reach disk before the potentially mutating call.
            save_json(out / active_attempt["attempt_path"], active_attempt)
            persist_session()
            request_started = True
            try:
                result = client.request("tools/call", {"name": call["name"], "arguments": call.get("arguments", {})})
            except McpRpcError as exc:
                response_received = True
                active_attempt["state"] = "rpc_error_response"
                active_attempt["application_state"] = "response_received"
                active_attempt["response_received_at"] = utc_now()
                save_json(out / active_attempt["response_path"], {"jsonrpc_error": exc.error})
                active_attempt["raw_response_saved"] = True
                raise
            response_received = True
            active_attempt["state"] = "response_received"
            active_attempt["application_state"] = "response_received"
            active_attempt["response_received_at"] = utc_now()
            if isinstance(result, dict):
                active_attempt["server_is_error"] = bool(result.get("isError"))
            # Keep the original JSON, including image bytes, before any decoding
            # or image/file materialization can fail.
            save_json(out / active_attempt["response_path"], result)
            active_attempt["raw_response_saved"] = True
            save_json(out / active_attempt["attempt_path"], active_attempt)
            persist_session()
            if not isinstance(result, dict):
                raise McpError("tools/call returned a non-object result; see raw response")
            if result.get("isError"):
                active_attempt["state"] = "tool_error_response"
                active_attempt["server_is_error"] = True
                raise McpError(f"Tool {call['name']} returned an error; batch stopped, see raw response")
            saved = materialize_images(result, out, prefix)
            save_json(out / f"{prefix}.json", saved)
            active_attempt["state"] = "completed"
            active_attempt["server_is_error"] = False
            active_attempt["materialized_result_path"] = f"{prefix}.json"
            active_attempt["finished_at"] = utc_now()
            save_json(out / active_attempt["attempt_path"], active_attempt)
            persist_session()
            content = result.get("content", [])
            texts = [part.get("text", "") for part in content
                     if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text", ""), str)] if isinstance(content, list) else []
            print(json.dumps({"step": index, "name": call["name"], "isError": bool(result.get("isError")),
                              "text": "\n".join(texts)[:1800]}, ensure_ascii=False), flush=True)
            active_attempt = None
            request_started, response_received = False, False
        session["state"] = "completed"
        session["finished_at"] = utc_now()
        persist_session()
        exit_code = 0
    except (OSError, ValueError, McpError, subprocess.SubprocessError, TypeError) as exc:
        persist_failure(exc)
        print(f"Composa MCP failed: {exc}", file=sys.stderr, flush=True)
    finally:
        if client:
            try:
                client.close()
            except (OSError, ValueError, McpError, subprocess.SubprocessError) as exc:
                persist_failure(exc)
                print(f"Composa bridge cleanup failed: {exc}", file=sys.stderr, flush=True)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
