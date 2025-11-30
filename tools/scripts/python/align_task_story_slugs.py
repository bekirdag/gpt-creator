import difflib
import re
import sqlite3
import sys
import time
from pathlib import Path


def normalize(value: str) -> str:
    return (value or "").strip()


def slug_norm(value: str) -> str:
    value = normalize(value).lower()
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def align_task_story_slugs(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    story_norm_map = {}
    story_norm_keys = []
    for story in cur.execute("SELECT story_slug, story_key, story_id, story_title FROM stories"):
        slug = normalize(story["story_slug"])
        if not slug:
            continue
        canonical = slug
        for candidate in {
            story["story_slug"],
            story["story_key"],
            story["story_id"],
            story["story_title"],
        }:
            norm = slug_norm(candidate)
            if norm and norm not in story_norm_map:
                story_norm_map[norm] = canonical
        lower_slug = canonical.lower()
        if lower_slug not in story_norm_map:
            story_norm_map[lower_slug] = canonical

    story_norm_keys = list(story_norm_map.keys())

    updates = []
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for task in cur.execute("SELECT id, story_slug, story_id, story_title FROM tasks"):
        current_slug = normalize(task["story_slug"])
        story_id = normalize(task["story_id"])
        story_title = normalize(task["story_title"])

        target_slug = None
        candidates = [
            story_id,
            current_slug,
            story_title,
        ]

        for candidate in candidates:
            norm = slug_norm(candidate)
            if norm and norm in story_norm_map:
                target_slug = story_norm_map[norm]
                break

        if not target_slug:
            combined = slug_norm(f"{story_id}-{story_title}") or slug_norm(current_slug)
            if combined:
                match = difflib.get_close_matches(combined, story_norm_keys, n=1, cutoff=0.84)
                if match:
                    target_slug = story_norm_map[match[0]]

        if target_slug and target_slug != current_slug:
            updates.append((target_slug, timestamp, task["id"]))

    if updates:
        cur.executemany("UPDATE tasks SET story_slug = ?, updated_at = ? WHERE id = ?", updates)
        conn.commit()

    conn.close()


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    align_task_story_slugs(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
