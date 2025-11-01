#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

CANONICAL_KEYS = ("plan", "focus", "changes", "commands", "notes")


def _ensure_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _normalize_focus(items: List[Any]) -> List[str]:
    normalized: List[str] = []
    for entry in items:
        if isinstance(entry, str):
            candidate = entry.strip()
            if candidate:
                normalized.append(candidate)
    return normalized


def _sanitize_changes(changes: List[Any]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for index, entry in enumerate(changes, 1):
        if isinstance(entry, str):
            text = entry.strip()
            if not text:
                continue
            if not (text.startswith("--- ") or text.startswith("diff --git ")):
                raise ValueError(f"invalid change at index {index}")
            sanitized.append({"type": "patch", "diff": text})
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"invalid change at index {index}")
        normalized = dict(entry)
        ctype = normalized.get("type")
        if isinstance(ctype, str):
            ctype = ctype.strip().lower()
        else:
            ctype = ""
        if not ctype:
            if "diff" in normalized or "patch" in normalized:
                ctype = "patch"
            elif "contents" in normalized or "contents_path" in normalized:
                ctype = "file"
        if ctype not in {"patch", "file"}:
            raise ValueError(f"invalid change type at index {index}")
        normalized["type"] = ctype
        if ctype == "patch":
            if "diff" not in normalized and "patch_path" not in normalized and "diff_path" not in normalized:
                raise ValueError(f"patch change missing diff at index {index}")
        else:
            if "path" not in normalized:
                raise ValueError(f"file change missing path at index {index}")
            if "contents" not in normalized and "contents_path" not in normalized:
                raise ValueError(f"file change missing contents at index {index}")
        sanitized.append(normalized)
    return sanitized


def main(path: str) -> int:
    payload_path = Path(path)
    raw = payload_path.read_text(encoding="utf-8", errors="ignore")
    try:
        envelope = json.loads(raw)
    except Exception as exc:  # pragma: no cover - defensive guard
        sys.stderr.write(f"E: invalid JSON: {exc}\n")
        return 2
    if not isinstance(envelope, dict):
        sys.stderr.write("E: top-level must be an object\n")
        return 2

    canonical: Dict[str, Any] = {}
    for key in CANONICAL_KEYS:
        canonical[key] = envelope.get(key)

    plan_items = _ensure_list(canonical.get("plan"))
    focus_items = _normalize_focus(_ensure_list(canonical.get("focus")))
    command_items = _ensure_list(canonical.get("commands"))
    notes_items = _ensure_list(canonical.get("notes"))
    change_items = canonical.get("changes") or []
    if not isinstance(change_items, list):
        sys.stderr.write("E: 'changes' must be a list\n")
        return 2

    meta_path = os.environ.get("GC_WOT_META_OUTPUT") or ""
    meta_payload = {
        "plan_has_items": bool(plan_items),
        "focus_has_items": bool(focus_items),
        "notes_contains_no_changes": False,
        "notes_contains_already_satisfied": False,
    }

    try:
        sanitized_changes = _sanitize_changes(change_items)
    except ValueError as exc:
        sys.stderr.write(f"E: {exc}\n")
        return 2

    lowered_notes = " ".join(str(note).lower() for note in notes_items if isinstance(note, str))
    if "no changes needed" in lowered_notes or "no repository edits required" in lowered_notes:
        meta_payload["notes_contains_no_changes"] = True
    if "already satisfies" in lowered_notes or "already satisfied" in lowered_notes:
        meta_payload["notes_contains_already_satisfied"] = True

    if (meta_payload["plan_has_items"] or meta_payload["focus_has_items"]) and not sanitized_changes and not notes_items:
        sys.stderr.write("E: plan/focus supplied but both 'changes' and 'notes' are empty\n")
        if meta_path:
            try:
                Path(meta_path).write_text(json.dumps(meta_payload), encoding="utf-8")
            except Exception:
                pass
        return 3

    canonical["plan"] = plan_items
    canonical["focus"] = focus_items
    canonical["commands"] = command_items
    canonical["notes"] = notes_items
    canonical["changes"] = sanitized_changes

    trimmed = {key: canonical.get(key, []) for key in CANONICAL_KEYS}

    serialized = json.dumps(trimmed, ensure_ascii=True, separators=(",", ":"))
    try:
        serialized.encode("ascii")
    except UnicodeEncodeError:
        serialized = (
            unicodedata.normalize("NFKD", serialized)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    payload_path.write_text(serialized, encoding="ascii")

    if meta_path:
        try:
            Path(meta_path).write_text(json.dumps(meta_payload), encoding="utf-8")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
