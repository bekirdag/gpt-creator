import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import document_index  # noqa: E402
from log_blocked_quota import log_blocked_quota  # noqa: E402


def _build_minimal_db(db_path: Path, story_slug: str, description: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE stories (
            story_id TEXT,
            story_title TEXT,
            epic_key TEXT,
            epic_title TEXT,
            sequence INTEGER,
            story_slug TEXT
        );
        CREATE TABLE tasks (
            task_id TEXT,
            title TEXT,
            description TEXT,
            estimate INTEGER,
            assignees_json TEXT,
            tags_json TEXT,
            acceptance_json TEXT,
            dependencies_json TEXT,
            tags_text TEXT,
            story_points INTEGER,
            dependencies_text TEXT,
            assignee_text TEXT,
            document_reference TEXT,
            idempotency TEXT,
            rate_limits TEXT,
            rbac TEXT,
            messaging_workflows TEXT,
            performance_targets TEXT,
            observability TEXT,
            acceptance_text TEXT,
            endpoints TEXT,
            sample_create_request TEXT,
            sample_create_response TEXT,
            user_story_ref_id TEXT,
            epic_ref_id TEXT,
            status TEXT,
            last_progress_at TEXT,
            last_progress_run TEXT,
            last_log_path TEXT,
            last_output_path TEXT,
            last_prompt_path TEXT,
            last_notes_json TEXT,
            last_commands_json TEXT,
            last_apply_status TEXT,
            last_changes_applied INTEGER,
            last_tokens_total INTEGER,
            last_duration_seconds INTEGER,
            story_slug TEXT,
            position INTEGER
        );
        """
    )
    conn.execute(
        """
        INSERT INTO stories (story_id, story_title, epic_key, epic_title, sequence, story_slug)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("STORY-1", "Sample Story", "EPIC-1", "Sample Epic", 1, story_slug),
    )
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, title, description, estimate, assignees_json, tags_json, acceptance_json, dependencies_json,
            tags_text, story_points, dependencies_text, assignee_text, document_reference, idempotency, rate_limits,
            rbac, messaging_workflows, performance_targets, observability, acceptance_text, endpoints,
            sample_create_request, sample_create_response, user_story_ref_id, epic_ref_id, status,
            last_progress_at, last_progress_run, last_log_path, last_output_path, last_prompt_path,
            last_notes_json, last_commands_json, last_apply_status, last_changes_applied, last_tokens_total,
            last_duration_seconds, story_slug, position
        )
        VALUES (
            ?, ?, ?, 1, '[]', '[]', '[]', '[]', '', 1, '', '', '',
            '', '', '', '', '', '', '', '', '', '', '', '', 'pending',
            '', '', '', '', '', '', '', '', 0, 0, 0, ?, 0
        )
        """,
        ("TASK-1", "Investigate prompt budgets", description, story_slug),
    )
    conn.commit()
    conn.close()


def test_doc_catalog_segments_keep_nested_bullets():
    section = {
        "heading": "Documentation Catalog",
        "lines": [
            "## Documentation Catalog",
            "- DOC-AAA11111 — docs/a.md",
            "- nested list item describing the doc",
            "  continuation line",
            "- DOC-BBB22222 — docs/b.md",
            "  - nested bullet is retained",
        ],
    }

    segments = document_index._build_doc_catalog_segments(section)

    assert len(segments) == 3
    first_entry = segments[1]["full_text"].splitlines()
    assert "- nested list item describing the doc" in first_entry
    assert "  continuation line" in first_entry


def test_apply_pruning_records_metrics():
    segments = [
        {
            "id": "doc-catalog-entry:00",
            "type": "doc-catalog-entry",
            "score": 55,
            "must_keep": False,
            "full_text": "- DOC-AAA — docs/a.md\n  - detail line one\n  - detail line two",
            "fallback_text": "- DOC-AAA — docs/a.md",
            "path": "docs/a.md",
            "doc_id": "DOC-AAA",
            "order": 0,
        },
        {
            "id": "task:01",
            "type": "task",
            "score": 94,
            "must_keep": False,
            "full_text": "Large generic segment\n" + ("x" * 120),
            "fallback_text": "Large generic segment",
            "path": None,
            "doc_id": None,
            "order": 1,
        },
    ]

    total, pruned_items, pruned_bytes = document_index._apply_pruning(segments, soft_limit=1, hard_limit=200, margin=1.0)

    assert total > 0
    assert pruned_bytes > 0
    assert pruned_items["doc_snippets_elided"] == 1
    assert pruned_items["segments_elided"] == 1
    assert pruned_items["artefacts_elided"] == 2


@pytest.mark.parametrize(
    "stop_override,expected_status,expected_stop",
    [
        ("true", "blocked-quota", True),
        ("false", "ok", False),
    ],
)
def test_document_index_meta_respects_overrides(tmp_path: Path, stop_override: str, expected_status: str, expected_stop: bool):
    project_root = tmp_path / "project"
    staging_dir = project_root / ".gpt-creator" / "staging"
    project_root.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    db_path = staging_dir / "tasks.db"
    description = ("heavy input " * 4000) if stop_override == "true" else "lightweight description"
    story_slug = "story-alpha"
    _build_minimal_db(db_path, story_slug, description)

    prompt_path = staging_dir / "prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    context_tail = staging_dir / "context.txt"
    context_tail.write_text("recent activity\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "GC_PER_TASK_HARD_LIMIT_OVERRIDE": "200" if stop_override == "true" else "8000",
            "GC_PER_TASK_MIN_OUTPUT_OVERRIDE": "0",
            "GC_PER_TASK_SOFT_RATIO_OVERRIDE": "0.5",
            "GC_STOP_ON_OVERBUDGET_OVERRIDE": stop_override,
            "PYTHONPATH": str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )

    command = [
        sys.executable,
        str(SCRIPTS_DIR / "document_index.py"),
        str(db_path),
        story_slug,
        "0",
        str(prompt_path),
        str(context_tail),
        "gpt-4.1-coder",
        str(project_root),
        str(staging_dir),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    assert "TASK-1" in result.stdout

    meta_path = Path(f"{prompt_path}.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == expected_status
    assert bool(meta["stop_on_overbudget"]) is expected_stop
    if expected_status == "blocked-quota":
        assert meta["pruned"]["applied"] is True
        assert meta["token_budget_hard_source"] == "env-override"


def test_log_blocked_quota_appends_row(tmp_path: Path):
    meta_path = tmp_path / "prompt.meta.json"
    meta_payload = {
        "status": "blocked-quota",
        "token_budget_soft": 1000,
        "token_budget_hard": 1200,
        "token_estimate_final": 1500,
        "reserved_output": 1024,
        "pruned": {
            "items": {"artefacts_elided": 3, "segments_dropped": 1},
            "bytes": 2048,
        },
    }
    meta_path.write_text(json.dumps(meta_payload), encoding="utf-8")
    log_path = tmp_path / "logs" / "blocked.ndjson"

    log_blocked_quota(
        meta_path,
        task_id="TASK-99",
        story_slug="story-omega",
        run_id="run-123",
        model="gpt-4.1-coder",
        log_path=log_path,
    )

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["blocked_quota"] is True
    assert row["task_id"] == "TASK-99"
    assert row["story_slug"] == "story-omega"
    assert row["run_id"] == "run-123"
    assert row["model"] == "gpt-4.1-coder"
    assert row["pruned_items"]["artefacts_elided"] == 3
    assert row["pruned_bytes"] == 2048

    # Status other than blocked should not append additional rows.
    meta_path.write_text(json.dumps({**meta_payload, "status": "ok"}), encoding="utf-8")
    log_blocked_quota(
        meta_path,
        task_id="TASK-99",
        story_slug="story-omega",
        run_id="run-123",
        model="gpt-4.1-coder",
        log_path=log_path,
    )
    lines_after = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1
