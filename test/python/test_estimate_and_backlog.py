import contextlib
import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import estimate_remaining_work


def _init_project_db(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "proj"
    db_dir = project_root / ".gpt-creator" / "staging" / "plan"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "tasks.db"
    runs_dir = project_root / ".gpt-creator" / "staging" / "plan" / "work" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return project_root, db_path


def _create_estimate_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_slug TEXT NOT NULL,
            position INTEGER NOT NULL,
            story_points TEXT,
            status TEXT NOT NULL,
            task_id TEXT,
            last_story_points TEXT,
            progress_state TEXT,
            last_apply_status TEXT,
            last_verify_status TEXT,
            locked_by_migration INTEGER DEFAULT 0,
            reopened_by_migration INTEGER DEFAULT 0,
            reopened_by_migration_at TEXT,
            last_run TEXT,
            updated_at TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE task_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            story_slug TEXT,
            task_position INTEGER,
            status TEXT,
            run_stamp TEXT,
            occurred_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE metric_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT,
            story_slug TEXT,
            task_position INTEGER,
            task_id TEXT,
            sp_delivered REAL,
            tokens_total REAL,
            duration_seconds REAL,
            occurred_at REAL,
            final_status TEXT,
            project_root TEXT
        );
        """
    )
    conn.commit()


def _insert_task(conn: sqlite3.Connection, slug: str, position: int, task_id: str, status: str) -> None:
    conn.execute(
        "INSERT INTO tasks (story_slug, position, story_points, status, task_id) VALUES (?,?,?,?,?)",
        (slug, position, "5", status, task_id),
    )


def _insert_progress(
    conn: sqlite3.Connection,
    task_id: str,
    slug: str,
    position: int,
    status: str,
    stamp: str = "run-1",
    occurred: str = "2025-01-01T00:00:00Z",
) -> None:
    conn.execute(
        "INSERT INTO task_progress (task_id, story_slug, task_position, status, run_stamp, occurred_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (task_id, slug, position, status, stamp, occurred, occurred),
    )


def _insert_metric_sample(
    conn: sqlite3.Connection,
    slug: str,
    position: int,
    sp: float,
    duration: float,
    tokens: float,
    status: str,
    project_root: Path,
) -> None:
    conn.execute(
        "INSERT INTO metric_samples (task_key, story_slug, task_position, task_id, sp_delivered, tokens_total, duration_seconds, occurred_at, final_status, project_root) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (f"{slug}:{position}", slug, position, f"{slug}-{position}", sp, tokens, duration, 0.0, status, str(project_root)),
    )


def _init_backlog_db(tmp_path: Path) -> Path:
    project_root = tmp_path / "proj"
    db_dir = project_root / ".gpt-creator" / "staging" / "plan"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "tasks.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE epics (
            epic_key TEXT PRIMARY KEY,
            epic_id TEXT,
            title TEXT,
            slug TEXT
        );
        CREATE TABLE stories (
            story_slug TEXT PRIMARY KEY,
            story_id TEXT,
            story_title TEXT,
            epic_key TEXT,
            epic_title TEXT,
            sequence INTEGER,
            status TEXT,
            completed_tasks INTEGER,
            total_tasks INTEGER
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_slug TEXT,
            position INTEGER,
            task_id TEXT,
            title TEXT,
            status TEXT
        );
        CREATE TABLE task_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            story_slug TEXT,
            task_position INTEGER,
            status TEXT,
            run_stamp TEXT,
            occurred_at TEXT,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO epics (epic_key, epic_id, title, slug) VALUES ('epic-1', 'EPIC-1', 'Test Epic', 'epic-1')"
    )
    conn.execute(
        "INSERT INTO stories (story_slug, story_id, story_title, epic_key, epic_title, sequence, status, completed_tasks, total_tasks) "
        "VALUES ('story-1', 'STORY-1', 'Story One', 'epic-1', 'Test Epic', 1, 'pending', 0, 82)"
    )
    for idx in range(82):
        conn.execute(
            "INSERT INTO tasks (story_slug, position, task_id, title, status) VALUES (?,?,?,?,?)",
            ("story-1", idx, f"TASK-{idx}", f"Task {idx}", "pending"),
        )
        if idx < 16:
            conn.execute(
                "INSERT INTO task_progress (task_id, story_slug, task_position, status, run_stamp, occurred_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"TASK-{idx}", "story-1", idx, "complete", "run", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
    conn.commit()
    conn.close()
    return db_path


class EstimateBacklogTests(unittest.TestCase):
    def test_estimate_detects_and_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project_root, db_path = _init_project_db(tmp_path)
            conn = sqlite3.connect(db_path)
            _create_estimate_schema(conn)
            _insert_task(conn, "story-1", 0, "TASK-1", "pending")
            _insert_task(conn, "story-1", 1, "TASK-2", "pending")
            _insert_progress(conn, "TASK-1", "story-1", 0, "complete")
            _insert_metric_sample(conn, "story-1", 0, 5.0, 3600.0, 1000.0, "complete", project_root)
            conn.commit()
            conn.close()

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                estimate_remaining_work.estimate(db_path, recent_task_limit=10, scope="project")
            output = buffer.getvalue()
            self.assertIn("Completed tasks (canonical)  0", output)
            self.assertIn("Completed tasks (effective)  1", output)
            self.assertIn("Detections pending apply     1", output)

            with contextlib.redirect_stdout(io.StringIO()):
                estimate_remaining_work.estimate(
                    db_path,
                    recent_task_limit=10,
                    scope="project",
                    apply_detections=True,
                )
            conn = sqlite3.connect(db_path)
            status = conn.execute("SELECT status FROM tasks WHERE task_id='TASK-1'").fetchone()[0]
            conn.close()
            self.assertEqual(status, "complete")

    def test_estimate_throughput_scope_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project_root, db_path = _init_project_db(tmp_path)
            conn = sqlite3.connect(db_path)
            _create_estimate_schema(conn)
            _insert_task(conn, "story-1", 0, "TASK-1", "pending")
            other_root = Path("/tmp/other-project")
            for idx in range(3):
                _insert_metric_sample(conn, "other", idx, 1.0, 1200.0, 500.0, "complete", other_root)
            conn.commit()
            conn.close()

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                estimate_remaining_work.estimate(db_path, recent_task_limit=3, scope="project")
            output = buffer.getvalue()
            self.assertIn("Throughput window", output)
            self.assertIn("project 0, out-of-scope 3", output)
            self.assertIn("Window contamination", output)

    def test_backlog_progress_uses_task_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = _init_backlog_db(tmp_path)
            cmd = [
                "python3",
                str(REPO_ROOT / "scripts" / "python" / "fetch_stories.py"),
                str(db_path),
                "",
                "",
                "1",
                "",
                "",
            ]
            completed_line = None
            detections_line = None
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if "Completed tasks (effective)" in line:
                    completed_line = line
                if "Detections pending apply" in line:
                    detections_line = line
            self.assertIsNotNone(completed_line)
            self.assertIsNotNone(detections_line)
            assert completed_line is not None
            assert detections_line is not None
            self.assertIn("16", completed_line)
            self.assertIn("19.5%", completed_line)
            self.assertIn("16", detections_line)


if __name__ == "__main__":
    unittest.main()
