"""Bind production delivery to editor sessions, roundtrips and model-tool evidence.

This checks local recorded evidence and artifact identity. It cannot certify
artistic quality or authenticate an independently authored log as a real event.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from skill_contract import checked_file, read_json, require_text, sha


def spec(path):
    path = Path(path).resolve(strict=True)
    return {"file": str(path), "sha256": sha(path)}


def collect_session(folder):
    folder = Path(folder).resolve(strict=True)
    session = read_json(folder / "session.json")
    responses = []
    for call in session.get("calls", []):
        path = (folder / call["response_path"]).resolve(strict=True)
        if not path.is_relative_to(folder):
            raise ValueError("Session response escapes session folder")
        responses.append(spec(path))
    return {"session": spec(folder / "session.json"), "schema": spec(folder / "tools.json"),
            "lifecycle": spec(folder / "lifecycle.json"), "responses": responses}


def editor_calls(root, records):
    if not isinstance(records, list) or not records:
        raise ValueError("Real editor sessions are required for production delivery")
    calls, sessions = [], set()
    for record in records:
        path = checked_file(root, record.get("session"), "editor session")
        if path in sessions:
            raise ValueError("Duplicate editor session")
        sessions.add(path)
        session = read_json(path)
        if session.get("state") != "completed" or session.get("cleanup_error") or session.get("error"):
            raise ValueError("Editor session did not complete cleanly")
        tools = read_json(checked_file(root, record.get("schema"), "live editor schema"))
        known = {t["name"] for t in tools.get("tools", [])}
        responses = {}
        for response in record.get("responses", []):
            file = checked_file(root, response, "original tool response")
            if file in responses:
                raise ValueError("Duplicate original response")
            responses[file] = read_json(file)
        expected = set()
        for call in session.get("calls", []):
            if call.get("state") != "completed" or call.get("server_is_error") is not False or call.get("name") not in known:
                raise ValueError("Editor call is failed, uncertain or absent from live schema")
            raw_path = (path.parent / call["response_path"]).resolve(strict=True)
            if not raw_path.is_relative_to(path.parent) or raw_path not in responses:
                raise ValueError("Editor call lacks its frozen original response")
            raw = responses[raw_path]
            if not isinstance(raw, dict) or raw.get("isError") or "jsonrpc_error" in raw or not isinstance(raw.get("content"), list):
                raise ValueError("Original editor response is an error or malformed")
            expected.add(raw_path)
            calls.append(call)
        if not expected or expected != set(responses):
            raise ValueError("Editor response inventory differs from executed calls")
        lifecycle = read_json(checked_file(root, record.get("lifecycle"), "owned-document lifecycle"))
        if set(lifecycle.get("owned", [])) & set(lifecycle.get("baseline", [])):
            raise ValueError("Baseline document claimed as owned")
        events = lifecycle.get("events", [])
        if not events or any(e.get("state") == "requesting" for e in events):
            raise ValueError("Document lifecycle is incomplete")
        last = events[-1]
        if last.get("state") not in {"completed", "nothing_to_close"}:
            if not (lifecycle.get("keep_open") is True and last.get("reason") == "keep_open"):
                raise ValueError("Owned documents were retained because of an unresolved failure")
    edits = {"place_image", "paint_stroke", "paint_strokes", "fill_layer", "add_text", "add_shape",
             "transform_layer", "adjust_curves", "adjust_hue_saturation", "reorder_layer", "set_layer"}
    if not any(c["name"] in edits for c in calls):
        raise ValueError("Listing tools or opening a flat image is not real layer work")
    return calls


def _call_path(call):
    value = call.get("arguments", {}).get("path")
    return Path(value).resolve() if isinstance(value, str) and value else None


def _pixels(path):
    with Image.open(path) as im:
        if im.mode != "RGBA":
            raise ValueError("Editor comparison exports must be RGBA")
        return np.array(im)


def audit_tools(root, data):
    record = data.get("production_tools")
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("Production delivery requires production_tools schema 1; technical texture checks alone are insufficient")
    editor = record.get("editor", {})
    calls = editor_calls(root, editor.get("sessions"))
    projects = editor.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("Saved native projects and copy-reopen exports are required")
    runtime = {r["id"]: r for r in data["runtime_textures"]}
    covered = set()
    project_reports = []
    for project in projects:
        native = checked_file(root, project.get("project"), "saved native project")
        copy = checked_file(root, project.get("reopened_copy"), "reopened project copy")
        saved = checked_file(root, project.get("saved_export"), "saved editor export")
        reopened = checked_file(root, project.get("reopened_export"), "reopened editor export")
        if native.suffix.lower() not in {".cmps", ".psd", ".psb"} or native.stat().st_size == 0:
            raise ValueError("Actual native editable project required")
        if native == copy or sha(native) != sha(copy) or saved == reopened:
            raise ValueError("Reopen must use a distinct exact project copy and distinct export")
        required = [("save_document", native), ("open_document", copy), ("export_image", saved), ("export_image", reopened)]
        if any(not any(c["name"] == name and _call_path(c) == path for c in calls) for name, path in required):
            raise ValueError("Project/export has no matching successful editor call")
        cursor=-1
        for name,path in [("save_document",native),("export_image",saved),("open_document",copy),("export_image",reopened)]:
            indices=[i for i,c in enumerate(calls) if i>cursor and c["name"]==name and _call_path(c)==path]
            if not indices:raise ValueError("Editor save/export/copy-reopen order is inconsistent")
            cursor=indices[0]
        a, b = _pixels(saved), _pixels(reopened)
        if a.shape != b.shape or not np.array_equal(a, b):
            raise ValueError("Saved and reopened editor pixels differ")
        outputs = project.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError("Editor output must bind actual runtime color canonical files")
        for output in outputs:
            identifier = output.get("runtime_texture_id")
            row = runtime.get(identifier)
            if row is None or row["role"] != "color" or identifier in covered:
                raise ValueError("Unknown, duplicate or non-color editor output")
            canonical = checked_file(root, output.get("canonical"), "editor-linked canonical C")
            actual = checked_file(root, row["canonical"], "runtime canonical C")
            if sha(canonical) != sha(actual):
                raise ValueError("Editor receipt refers to stale runtime canonical")
            final = _pixels(canonical)
            if final.shape != a.shape or not np.array_equal(final, a):
                # Precise native-grid/channel processing is allowed after export,
                # but its script, run log and input/output must be explicit.
                post = output.get("postprocess", {})
                checked_file(root, post.get("script"), "post-export processing script")
                checked_file(root, post.get("run_log"), "post-export run log")
                if post.get("exit_code") != 0 or type(post.get("exit_code")) is not int:
                    raise ValueError("Post-export processing did not succeed")
                if post.get("input_sha256") != sha(saved) or post.get("output_sha256") != sha(actual):
                    raise ValueError("Post-export processing is not bound to actual input/output")
                require_text(post.get("operation"), "post-export operation")
            covered.add(identifier)
        project_reports.append({"project_sha256": sha(native), "roundtrip_pixels_exact": True,
                                "runtime_outputs": [o["runtime_texture_id"] for o in outputs]})
    required_colors = {r["id"] for r in runtime.values() if r["role"] == "color" and r["state"] == "modified"}
    if not required_colors <= covered:
        raise ValueError("Modified color outputs have no actual editor production chain")

    blender = record.get("blender", {})
    if blender.get("status") == "unavailable":
        diagnostic = read_json(checked_file(root, blender.get("diagnostic"), "Blender unavailability diagnostic"))
        require_text(blender.get("reason"), "Blender unavailability reason")
        if diagnostic.get("usable") is not False or not diagnostic.get("attempts"):
            raise ValueError("Blender unavailability needs actual failed discovery/execution evidence")
        if any(a.get("outcome") not in {"not_found", "failed"} or not a.get("entry") for a in diagnostic["attempts"]):
            raise ValueError("A usable Blender attempt cannot be declared unavailable")
        model_report = {"status": "unavailable", "model_tool_validation": "not_run", "reason": blender["reason"]}
    elif blender.get("status") == "checked":
        receipt = read_json(checked_file(root, blender.get("receipt"), "actual Blender run receipt"))
        script = checked_file(root, receipt.get("script"), "executed model check script")
        checked_file(root, receipt.get("run_log"), "model tool run log")
        require_text(receipt.get("executable"), "actual Blender executable")
        require_text(receipt.get("version"), "actual Blender version")
        argv = receipt.get("argv", [])
        if not isinstance(argv, list) or "--background" not in argv or "--python-exit-code" not in argv:
            raise ValueError("Blender execution must record background and error exit handling")
        if argv[argv.index("--python-exit-code") + 1:][:1] != ["1"]:
            raise ValueError("Blender Python failures must return exit code 1")
        if "--python" not in argv or argv[argv.index("--python")+1:][:1] != [str(script)]:
            raise ValueError("Blender command does not invoke the recorded script")
        if receipt.get("exit_code") != 0 or type(receipt.get("exit_code")) is not int:
            raise ValueError("Blender execution failed")
        if receipt.get("model_sha256") != data["model"]["sha256"]:
            raise ValueError("Blender receipt belongs to a different model")
        expected = {r["id"]: r["dds"]["sha256"] for r in runtime.values()}
        if receipt.get("bound_runtime_dds") != expected:
            raise ValueError("Blender receipt does not bind every current final DDS")
        before = receipt.get("geometry_uv_before_sha256")
        if not isinstance(before, str) or len(before) != 64 or before != receipt.get("geometry_uv_after_sha256"):
            raise ValueError("Native geometry/UV identity changed or is missing")
        model_report = {"status": "checked", "version": receipt["version"], "bound_runtime_count": len(expected)}
    else:
        raise ValueError("Record actual Blender execution or concrete unavailability")
    return {"editor_projects": project_reports, "editor_successful_calls": len(calls), "blender": model_report,
            "scope": "recorded tool execution and artifact linkage; artwork/game approval not inferred"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("session"); capture.add_argument("folder", type=Path); capture.add_argument("--out", type=Path, required=True)
    check = sub.add_parser("check"); check.add_argument("manifest", type=Path); check.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists(): raise ValueError("Evidence output must be a new file")
    result = collect_session(args.folder) if args.command == "session" else audit_tools(args.manifest.resolve().parent, read_json(args.manifest))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.out), "recorded": True}, ensure_ascii=False))


if __name__ == "__main__": main()
