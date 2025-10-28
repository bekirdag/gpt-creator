import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Tuple


def normalize(value: str) -> str:
    return (value or "").strip()


def status_for_counts(total: int, completed: int) -> str:
    if total <= 0:
        return "pending"
    if completed >= total:
        return "complete"
    if completed > 0:
        return "in-progress"
    return "pending"


def sync_story_totals(db_path: Path) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stories = cur.execute("SELECT story_slug, status FROM stories").fetchall()

    updates: List[Tuple[int, int, str, str, str]] = []
    for story in stories:
        slug = normalize(story["story_slug"])
        if not slug:
            continue
        slug_lower = slug.lower()
        row = cur.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'complete' THEN 1 ELSE 0 END) AS complete_count
              FROM tasks
             WHERE LOWER(COALESCE(story_slug, '')) = ?
            """,
            (slug_lower,),
        ).fetchone()
        total = int(row["total_count"] or 0)
        completed = int(row["complete_count"] or 0)
        story_status = status_for_counts(total, completed)
        updates.append((total, completed, story_status, timestamp, slug))

    if updates:
        cur.executemany(
            """
            UPDATE stories
               SET total_tasks = ?,
                   completed_tasks = ?,
                   status = ?,
                   updated_at = ?
             WHERE story_slug = ?
            """,
            updates,
        )
        conn.commit()

    conn.close()


def main() -> int:
    if len(sys.argv) < 2:
        return 1

    db_path = Path(sys.argv[1])
    sync_story_totals(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
