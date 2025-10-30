import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import progress_migration
import record_task_progress
import update_task_state


def _init_tasks_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_slug TEXT NOT NULL,
            position INTEGER NOT NULL,
            task_id TEXT,
            title TEXT,
            status TEXT,
            locked_by_migration INTEGER DEFAULT 0,
            migration_epoch INTEGER DEFAULT 0,
            uid TEXT,
            status_reason TEXT,
            last_verified_commit TEXT,
            UNIQUE(story_slug, position)
        );
        CREATE TABLE IF NOT EXISTS stories (
            story_slug TEXT PRIMARY KEY,
            story_id TEXT,
            story_title TEXT,
            epic_key TEXT,
            epic_title TEXT,
            sequence INTEGER
        );
        CREATE TABLE IF NOT EXISTS task_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            story_slug TEXT NOT NULL,
            task_position INTEGER NOT NULL,
            run_stamp TEXT,
            status TEXT,
            apply_status TEXT,
            changes_applied INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    conn.commit()
    return conn


def test_progress_migration_plan_apply(tmp_path):
    db_path = tmp_path / "tasks.db"
    conn = _init_tasks_db(db_path)
    conn.execute(
        "INSERT INTO tasks (story_slug, position, task_id, title, status) VALUES (?,?,?,?,?)",
        ("story-alpha", 0, "TASK-1", "Initial Task", "complete"),
    )
    conn.execute(
        "INSERT INTO tasks (story_slug, position, task_id, title, status) VALUES (?,?,?,?,?)",
        ("story-alpha", 1, "TASK-2", "Second Task", "pending"),
    )
    conn.commit()
    conn.close()

    plan_path = tmp_path / "plan.json"
    plan = progress_migration.plan_only(db_path, plan_path)
    assert plan["tasks_total"] == 2

    map_path = tmp_path / "map.ndjson"
    stats = progress_migration.apply_plan(db_path, plan, map_path)
    assert stats["tasks_updated"] == 2
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT uid, locked_by_migration, locked_by FROM tasks WHERE task_id='TASK-1'"
    ).fetchone()
    assert row[0]
    assert row[1] == 1
    assert row[2] == "migration"
    journal_row = conn.execute(
        "SELECT tasks_updated, states_locked FROM progress_migration_journal ORDER BY applied_at DESC LIMIT 1"
    ).fetchone()
    assert journal_row == (2, 1)
    audit_count = conn.execute("SELECT COUNT(*) FROM progress_migration_audit").fetchone()[0]
    snapshot_count = conn.execute("SELECT COUNT(*) FROM progress_migration_snapshots").fetchone()[0]
    assert audit_count == 2
    assert snapshot_count == 2
    conn.close()


def test_progress_migration_idempotent_second_run(tmp_path):
    db_path = tmp_path / "tasks.db"
    conn = _init_tasks_db(db_path)
    conn.execute(
        "INSERT INTO tasks (story_slug, position, task_id, title, status) VALUES (?,?,?,?,?)",
        ("story-alpha", 0, "TASK-1", "Initial Task", "complete"),
    )
    conn.execute(
        "INSERT INTO tasks (story_slug, position, task_id, title, status) VALUES (?,?,?,?,?)",
        ("story-alpha", 1, "TASK-2", "Second Task", "pending"),
    )
    conn.commit()
    conn.close()

    plan_path = tmp_path / "plan.json"
    map_path = tmp_path / "map.ndjson"

    plan = progress_migration.plan_only(db_path, plan_path)
    progress_migration.apply_plan(db_path, plan, map_path)

    conn = sqlite3.connect(db_path)
    baseline_rows = conn.execute(
        "SELECT uid, locked_by_migration, locked_by FROM tasks ORDER BY task_id"
    ).fetchall()
    conn.close()

    plan_second = progress_migration.plan_only(db_path, plan_path)
    assert plan_second["tasks_needing_update"] == 0
    stats_second = progress_migration.apply_plan(db_path, plan_second, map_path)
    assert stats_second["tasks_updated"] == 0

    conn = sqlite3.connect(db_path)
    after_rows = conn.execute(
        "SELECT uid, locked_by_migration, locked_by FROM tasks ORDER BY task_id"
    ).fetchall()
    assert baseline_rows == after_rows
    journal_rows = conn.execute(
        "SELECT tasks_updated FROM progress_migration_journal ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert journal_rows == (0,)
    audit_count = conn.execute("SELECT COUNT(*) FROM progress_migration_audit").fetchone()[0]
    assert audit_count == 2
    conn.close()


def test_update_task_state_respects_locked(tmp_path):
    db_path = tmp_path / "state.db"
    conn = _init_tasks_db(db_path)
    conn.execute(
        "INSERT INTO tasks (story_slug, position, task_id, title, status, locked_by_migration) VALUES (?,?,?,?,?,1)",
        ("story-alpha", 0, "TASK-1", "Locked Task", "complete"),
    )
    conn.commit()
    conn.close()

    update_task_state.update_task_state(db_path, "story-alpha", "0", "pending", "run-1")

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, locked_by_migration FROM tasks WHERE task_id='TASK-1'").fetchone()
    assert row[0] == "complete"
    assert row[1] == 1
    conn.close()


def test_record_task_progress_preserves_locked_status(tmp_path):
    db_path = tmp_path / "progress.db"
    conn = _init_tasks_db(db_path)
    conn.execute(
        "INSERT INTO tasks (story_slug, position, task_id, title, status, locked_by_migration) VALUES (?,?,?,?,?,1)",
        ("story-alpha", 0, "TASK-99", "Locked", "complete"),
    )
    conn.commit()
    conn.close()

    record_task_progress.record_task_progress(
        db_path=db_path,
        story_slug="story-alpha",
        position="0",
        run_stamp="run-123",
        status="skipped-no-changes",
        log_path="",
        prompt_path="",
        output_path="",
        attempts="1",
        tokens_total="0",
        duration_seconds="0",
        apply_status="empty-apply",
        changes_applied="false",
        notes_text="",
        written_text="",
        patched_text="",
        commands_text="",
        observation_hash="",
        occurred_at="2025-01-01T00:00:00Z",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status FROM task_progress WHERE task_position=0").fetchone()
    assert row[0] == "complete"
    conn.close()
