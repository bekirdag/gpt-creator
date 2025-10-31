#!/usr/bin/env python3
import base64
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path


def normalise(path_fragment: str) -> str:
    fragment = path_fragment.strip()
    if fragment.startswith("a/") or fragment.startswith("b/"):
        fragment = fragment[2:]
    if fragment.startswith("./"):
        fragment = fragment[2:]
    return fragment


def patch_text_from_file(project_root: Path, rel_path: str) -> str:
    try:
        patch_file = (project_root / rel_path).resolve()
        return patch_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def blob_size_from_file(project_root: Path, rel_path: str) -> int:
    try:
        blob_file = (project_root / rel_path).resolve()
        return len(blob_file.read_bytes())
    except Exception:
        return 0


def diff_target(diff_text: str) -> str:
    lhs = None
    rhs = None
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            lhs = line[4:].strip()
        elif line.startswith("+++ "):
            rhs = line[4:].strip()
        if lhs is not None and rhs is not None:
            break
    candidate = rhs
    if candidate in {None, "/dev/null", "b/dev/null"}:
        candidate = lhs
    if candidate is None:
        return ""
    return normalise(candidate)


def summarize(envelope_path: Path, project_root: Path) -> str:
    data = json.loads(envelope_path.read_text(encoding="utf-8"))

    changes = data.get("changes") or []
    commands = data.get("commands") or []
    notes = data.get("notes") or []

    written_order: list[str] = []
    written_seen: set[str] = set()
    patched_order: list[str] = []
    patched_seen: set[str] = set()
    change_sizes: "OrderedDict[str, int]" = OrderedDict()

    for change in changes:
        if isinstance(change, str):
            if not change.startswith("--- "):
                continue
            target = diff_target(change)
            if not target:
                continue
            if target not in patched_seen:
                patched_order.append(target)
                patched_seen.add(target)
            size = len(change.encode("utf-8"))
            change_sizes[target] = change_sizes.get(target, 0) + size
            continue

        if not isinstance(change, dict):
            continue

        if change.get("type") == "patch" and "patch_path" in change:
            patch_text = patch_text_from_file(project_root, str(change.get("patch_path", "")).strip())
            target = diff_target(patch_text) or str(change.get("patch_path", "")).strip()
            target = normalise(target)
            if target and target not in patched_seen:
                patched_order.append(target)
                patched_seen.add(target)
            if target:
                size = len(patch_text.encode("utf-8"))
                change_sizes[target] = change_sizes.get(target, 0) + size
            continue

        if "path" in change and "contents" in change:
            target = normalise(str(change.get("path", "")).strip())
            if not target:
                continue
            if target not in written_seen:
                written_order.append(target)
                written_seen.add(target)
            contents = change.get("contents")
            if change.get("encoding") == "base64":
                try:
                    decoded = base64.b64decode(contents)
                except Exception:
                    decoded = b""
                size = len(decoded)
            else:
                if isinstance(contents, str):
                    text_payload = contents
                else:
                    text_payload = json.dumps(contents, ensure_ascii=False)
                size = len(text_payload.encode("utf-8"))
            change_sizes[target] = change_sizes.get(target, 0) + size
            continue

        if "path" in change and "contents_path" in change:
            target = normalise(str(change.get("path", "")).strip())
            if not target:
                continue
            if target not in written_seen:
                written_order.append(target)
                written_seen.add(target)
            size = blob_size_from_file(project_root, str(change.get("contents_path", "")).strip())
            change_sizes[target] = change_sizes.get(target, 0) + size
            continue

    if not isinstance(commands, list):
        commands = []
    if not isinstance(notes, list):
        notes = []

    status = "ok" if (written_order or patched_order) else "noop"
    if os.environ.get("WOT_IDENTICAL") == "1":
        status = "identical-envelope"
        notes = list(notes)
        notes.append("Envelope already applied previously; skipping changes.")

    output_lines = []
    output_lines.append(f"STATUS {status}")
    output_lines.append("APPLIED")
    for path in written_order:
        output_lines.append(f"WRITE {path}")
    for path in patched_order:
        output_lines.append(f"PATCH {path}")
    for path, size in change_sizes.items():
        output_lines.append(f"SIZE {path}\t{size}")
    for cmd in commands:
        cmd_str = str(cmd).strip()
        if cmd_str:
            safe_cmd = cmd_str.replace("\r", " ").replace("\n", " ")
            output_lines.append(f"CMD {safe_cmd}")
    for note in notes:
        note_str = str(note).strip()
        if note_str:
            safe_note = note_str.replace("\r", " ").replace("\n", " ")
            output_lines.append(f"NOTE {safe_note}")

    return "\n".join(output_lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 2
    envelope_path = Path(argv[1])
    project_root = Path(argv[2]) if len(argv) > 2 else envelope_path.parent
    result = summarize(envelope_path, project_root)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
