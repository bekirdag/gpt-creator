import sqlite3
import sys
from pathlib import Path


def fetch_story_task_counts(db_path: Path, story_slug: str) -> str:
    slug = (story_slug or "").strip()
    if not slug:
        return "0\t0"

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    slug_lower = slug.lower()
    row = cur.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN LOWER(COALESCE(status, '')) IN ('complete', 'completed-no-changes') THEN 1 ELSE 0 END) AS complete_count
          FROM tasks
         WHERE LOWER(COALESCE(story_slug, '')) = ?
        """,
        (slug_lower,),
    ).fetchone()
    conn.close()

    total = int(row[0] or 0)
    completed = int(row[1] or 0)
    return f"{total}\t{completed}"


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    db_path = Path(sys.argv[1])
    story_slug = sys.argv[2]
    result = fetch_story_task_counts(db_path, story_slug)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
