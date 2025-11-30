import re
import sqlite3
import sys
import time
from pathlib import Path


def clean(value: str) -> str:
    return (value or "").strip()


def norm(value: str) -> str:
    return clean(value).lower()


def slug_norm(value: str) -> str:
    text = norm(value)
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def locate_by_story_and_position(cur: sqlite3.Cursor, story, position_text: str):
    try:
        position_input = int(position_text)
    except ValueError:
        print(
            f"Invalid task position '{position_text}'. Use a positive integer (1-based).",
            file=sys.stderr,
        )
        sys.exit(1)
    if position_input <= 0:
        print(f"Task position must be at least 1 (got {position_input}).", file=sys.stderr)
        sys.exit(1)
    index = position_input - 1
    row = cur.execute(
        """
        SELECT t.story_slug, t.position, t.task_id, t.title, s.story_title
          FROM tasks t
          LEFT JOIN stories s ON s.story_slug = t.story_slug
         WHERE LOWER(COALESCE(t.story_slug, '')) = ?
           AND t.position = ?
        """,
        (norm(story["story_slug"]), index),
    ).fetchone()
    if row is None:
        print(
            f"No task found for story '{story['story_slug']}' at position {position_input}.",
            file=sys.stderr,
        )
        sys.exit(1)
    return row


def locate_by_task_id(cur: sqlite3.Cursor, task_id: str):
    token = norm(task_id)
    if not token:
        return None
    return cur.execute(
        """
        SELECT t.story_slug, t.position, t.task_id, t.title, s.story_title, s.sequence
          FROM tasks t
          LEFT JOIN stories s ON s.story_slug = t.story_slug
         WHERE LOWER(COALESCE(t.task_id, '')) = ?
         ORDER BY s.sequence ASC, t.position ASC
         LIMIT 1
        """,
        (token,),
    ).fetchone()


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print("Task reference required.", file=sys.stderr)
        return 1

    db_path = args[0]
    task_ref = clean(args[1])
    story_hint = args[2] if len(args) > 2 else ""
    if not task_ref:
        print("Task reference required.", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    stories = cur.execute(
        "SELECT story_slug, story_key, story_id, story_title, sequence FROM stories ORDER BY sequence ASC, story_slug ASC"
    ).fetchall()

    if not stories:
        print("No stories available in backlog.", file=sys.stderr)
        conn.close()
        return 1

    story_by_keys = {}
    story_order = []
    for story in stories:
        slug = clean(story["story_slug"])
        if not slug:
            continue
        story_order.append(story)
        keys = {
            norm(story["story_key"]),
            norm(story["story_id"]),
            norm(slug),
            slug_norm(story["story_key"]),
            slug_norm(story["story_id"]),
            slug_norm(slug),
        }
        for key in keys:
            if key and key not in story_by_keys:
                story_by_keys[key] = story

    def resolve_story(token: str):
        token_norm = norm(token)
        if token_norm in story_by_keys:
            return story_by_keys[token_norm]
        token_slug = slug_norm(token)
        if token_slug and token_slug in story_by_keys:
            return story_by_keys[token_slug]
        return None

    target_row = None

    if ":" in task_ref:
        story_part, position_part = task_ref.split(":", 1)
        story_part = story_part.strip()
        position_part = position_part.strip()
        if not story_part or not position_part:
            print(
                "Invalid task reference. Expected format STORY:POSITION (e.g. auth-login:3).",
                file=sys.stderr,
            )
            conn.close()
            return 1
        story = resolve_story(story_part)
        if story is None:
            print(f"Story not found for reference '{story_part}'.", file=sys.stderr)
            conn.close()
            return 1
        target_row = locate_by_story_and_position(cur, story, position_part)
    else:
        target_row = locate_by_task_id(cur, task_ref)
        if target_row is None:
            print(
                "Task reference not found. Use a task id (e.g. TASK-123) or story-slug:position.",
                file=sys.stderr,
            )
            conn.close()
            return 1

    target_story_slug = clean(target_row["story_slug"])
    target_position = int(target_row["position"] or 0)
    target_task_id = clean(target_row["task_id"])
    target_title = clean(target_row["title"]) or "(untitled task)"
    target_story_title = clean(target_row["story_title"])

    story_hint_clean = clean(story_hint)
    if story_hint_clean:
        hint_story = resolve_story(story_hint_clean)
        if hint_story is None:
            print(
                f"Story reference '{story_hint}' not found; expected story '{target_story_slug}'.",
                file=sys.stderr,
            )
            conn.close()
            return 1
        hint_slug = clean(hint_story["story_slug"])
        if norm(hint_slug) != norm(target_story_slug):
            print(
                f"Story reference '{story_hint}' resolves to '{hint_slug}', which does not match task story '{target_story_slug}'.",
                file=sys.stderr,
            )
            conn.close()
            return 1

    ordered_slugs = [clean(story["story_slug"]) for story in story_order if clean(story["story_slug"])]
    try:
        story_index = ordered_slugs.index(target_story_slug)
    except ValueError:
        print(f"Story slug '{target_story_slug}' missing from ordered backlog.", file=sys.stderr)
        conn.close()
        return 1

    affected_slugs = ordered_slugs[story_index:]
    if not affected_slugs:
        print(f"No stories found from '{target_story_slug}'.", file=sys.stderr)
        conn.close()
        return 1

    cur.execute(
        """
        UPDATE tasks
           SET status = 'pending',
               started_at = NULL,
               completed_at = NULL,
               last_run = NULL,
               updated_at = ?
         WHERE story_slug = ?
           AND position >= ?
        """,
        (timestamp, target_story_slug, target_position),
    )

    if len(affected_slugs) > 1:
        placeholders = ",".join("?" * (len(affected_slugs) - 1))
        cur.execute(
            f"""
            UPDATE tasks
               SET status = 'pending',
                   started_at = NULL,
                   completed_at = NULL,
                   last_run = NULL,
                   updated_at = ?
             WHERE story_slug IN ({placeholders})
            """,
            (timestamp, *affected_slugs[1:]),
        )

    placeholders = ",".join("?" * len(affected_slugs))
    cur.execute(
        f"""
        UPDATE stories
           SET status = 'pending',
               last_run = NULL,
               updated_at = ?
         WHERE story_slug IN ({placeholders})
        """,
        (timestamp, *affected_slugs),
    )

    conn.commit()
    conn.close()

    print(
        "\t".join(
            [
                target_story_slug,
                target_story_title or target_story_slug,
                str(target_position + 1),
                target_task_id,
                target_title.replace("\t", " ").replace("\n", " "),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
