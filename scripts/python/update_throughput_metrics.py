import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional


def parse_points(raw) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return 0.0
    normalized = text.lower().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def meta_float(cur: sqlite3.Cursor, key: str, default: float = 0.0) -> float:
    row = cur.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    if not row or row["value"] is None:
        return default
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return default


def meta_int(cur: sqlite3.Cursor, key: str, default: int = 0) -> int:
    row = cur.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    if not row or row["value"] is None:
        return default
    try:
        return int(float(row["value"]))
    except (TypeError, ValueError):
        return default


def set_meta(cur: sqlite3.Cursor, key: str, value: str) -> None:
    cur.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", (key, value))


def update_throughput_metrics(db_path: Path, action: str, story_slug: str, position: str) -> Optional[str]:
    action = (action or "").strip().lower()
    story_slug = (story_slug or "").strip()
    position = (position or "").strip()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )

    now_ts = time.time()
    window_started_at = meta_float(cur, "throughput.window_started_at", now_ts)
    if window_started_at <= 0 or window_started_at > now_ts + 315360000:
        window_started_at = now_ts
    window_points = meta_float(cur, "throughput.window_points", 0.0)
    total_points = meta_float(cur, "throughput.total_points", 0.0)
    total_seconds = meta_float(cur, "throughput.total_seconds", 0.0)
    samples = meta_int(cur, "throughput.samples", 0)
    rate = meta_float(cur, "throughput.rate_sp_per_hour", 0.0)

    points_increment = 0.0
    if action == "task-complete" and story_slug and position:
        try:
            idx = int(position)
        except ValueError:
            idx = None
        if idx is not None:
            row = cur.execute(
                "SELECT story_points, estimate, status FROM tasks WHERE story_slug = ? AND position = ?",
                (story_slug, idx),
            ).fetchone()
            if row is not None:
                status = (row["status"] or "").strip().lower()
                if status == "complete":
                    points_increment = parse_points(row["story_points"])
                    if points_increment <= 0:
                        points_increment = parse_points(row["estimate"])
                    if points_increment < 0:
                        points_increment = 0.0

    if points_increment > 0:
        window_points += points_increment

    elapsed = max(0.0, now_ts - window_started_at)
    threshold = 3600.0
    should_flush = False
    if action == "flush":
        if elapsed > 0 or window_points > 0:
            should_flush = True
    elif elapsed >= threshold:
        should_flush = True

    updated = False
    window_points_before = window_points
    elapsed_before = elapsed

    if should_flush and (elapsed > 0 or window_points > 0):
        total_points += window_points
        total_seconds += elapsed
        samples += 1
        if total_points <= 0 or total_seconds <= 0:
            rate = 0.0
        else:
            rate = (total_points / total_seconds) * 3600.0
        set_meta(cur, "throughput.rate_sp_per_hour", f"{rate:.6f}")
        set_meta(cur, "throughput.last_window_points", f"{window_points:.6f}")
        set_meta(cur, "throughput.last_window_seconds", f"{elapsed:.3f}")
        window_points = 0.0
        window_started_at = now_ts
        updated = True

    if action == "init":
        window_started_at = now_ts
        window_points = 0.0

    timestamp_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
    set_meta(cur, "throughput.window_started_at", f"{window_started_at:.3f}")
    set_meta(cur, "throughput.window_points", f"{window_points:.6f}")
    set_meta(cur, "throughput.total_points", f"{total_points:.6f}")
    set_meta(cur, "throughput.total_seconds", f"{total_seconds:.3f}")
    set_meta(cur, "throughput.samples", str(max(samples, 0)))
    set_meta(cur, "throughput.updated_at", timestamp_iso)

    conn.commit()
    conn.close()

    if updated:
        hours = elapsed_before / 3600.0 if elapsed_before > 0 else 0.0
        return f"Throughput updated -> {rate:.2f} SP/hour (window: {hours:.2f}h, points: {window_points_before:.2f}, samples: {samples})"
    return None


def main() -> int:
    if len(sys.argv) < 5:
        return 1

    db_path = Path(sys.argv[1])
    action = sys.argv[2]
    story_slug = sys.argv[3]
    position = sys.argv[4]

    message = update_throughput_metrics(db_path, action, story_slug, position)
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
