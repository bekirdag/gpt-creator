#!/usr/bin/env python3
import json
import os
import sys
import unicodedata
from pathlib import Path

ALLOWED = {"plan", "focus", "changes", "commands", "notes"}


def main(path: str) -> int:
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover - defensive guard
        sys.stderr.write(f"E: invalid JSON: {exc}\n")
        return 2
    if not isinstance(data, dict):
        sys.stderr.write("E: top-level must be an object\n")
        return 2

    canonical = {k: v for k, v in data.items() if k in ALLOWED and v is not None}

    meta_path = os.environ.get("GC_WOT_META_OUTPUT") or ""
    meta_payload = {
        "plan_has_items": False,
        "focus_has_items": False,
        "notes_contains_no_changes": False,
        "notes_contains_already_satisfied": False,
    }

    plan_items = canonical.get("plan") or []
    if isinstance(plan_items, list) and plan_items:
        meta_payload["plan_has_items"] = True

    focus_items = canonical.get("focus") or []
    if isinstance(focus_items, list) and focus_items:
        meta_payload["focus_has_items"] = True

    changes = canonical.get("changes", [])
    if changes is None:
        changes = []
    if not isinstance(changes, list):
        sys.stderr.write("E: 'changes' must be a list\n")
        return 2
    for idx, change in enumerate(changes, 1):
        valid = False
        if isinstance(change, str):
            if change.startswith("--- "):
                valid = True
            elif change.startswith("diff --git "):
                valid = True
        elif isinstance(change, dict):
            if "path" in change and "contents" in change:
                valid = True
            elif "path" in change and "contents_path" in change:
                valid = True
            elif change.get("type") == "patch" and "patch_path" in change:
                valid = True
        if not valid:
            sys.stderr.write(f"E: invalid change at index {idx}\n")
            return 2

    notes = canonical.get("notes") or []
    if isinstance(notes, list):
        lowered_notes = " ".join(note.lower() for note in notes)
        if "no changes needed" in lowered_notes:
            meta_payload["notes_contains_no_changes"] = True
        if "already satisfies" in lowered_notes or "already satisfied" in lowered_notes:
            meta_payload["notes_contains_already_satisfied"] = True

    if (meta_payload["plan_has_items"] or meta_payload["focus_has_items"]) and not changes and not notes:
        sys.stderr.write("E: plan/focus supplied but both 'changes' and 'notes' are empty\n")
        if meta_path:
            try:
                Path(meta_path).write_text(json.dumps(meta_payload), encoding="utf-8")
            except Exception:
                pass
        return 3

    serialized = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"))
    try:
        serialized.encode("ascii")
    except UnicodeEncodeError:
        serialized = (
            unicodedata.normalize("NFKD", serialized)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    p.write_text(serialized, encoding="ascii")

    if meta_path:
        try:
            Path(meta_path).write_text(json.dumps(meta_payload), encoding="utf-8")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
