import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "python"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import task_binder


def test_prepare_and_load_binder(tmp_path: Path):
    project_root = tmp_path
    problem = "Implement feature X"
    invariants = ["Must not break Y"]
    acceptance = ["Scenario A", "Scenario B"]
    doc_refs = [
        {"doc_id": "DOC-1", "rel_path": "docs/a.md", "snippet": "foo", "method": "fts"}
    ]
    files_section = {"primary": ["src/app.ts"], "related": [], "deps": []}
    evidence = {"notes": ["Initial run"]}
    last_tokens = {"prompt": 1234}

    prompt_snapshot = "Line 1\nLine 2\nLine 3"
    binder_path, payload = task_binder.prepare_binder_payload(
        project_root=project_root,
        epic_slug="epic-alpha",
        story_slug="story-001",
        task_id="TASK-1",
        task_title="Feature",
        problem=problem,
        invariants=invariants,
        acceptance=acceptance,
        doc_refs=doc_refs,
        git_head="",
        files_section=files_section,
        evidence=evidence,
        last_tokens=last_tokens,
        previous=None,
        binder_status="miss",
        prompt_snapshot=prompt_snapshot,
    )
    task_binder.write_binder(binder_path, payload, max_bytes=task_binder.DEFAULT_MAX_BYTES)

    result = task_binder.load_for_prompt(
        project_root,
        epic_slug="epic-alpha",
        story_slug="story-001",
        task_id="TASK-1",
        ttl_seconds=task_binder.DEFAULT_TTL_SECONDS,
        max_bytes=task_binder.DEFAULT_MAX_BYTES,
    )

    assert result.status == "hit"
    assert result.binder["problem"] == problem
    assert result.binder["doc_refs"][0]["doc_id"] == "DOC-1"
    digest = result.binder.get("prompt_digest")
    assert isinstance(digest, dict)
    assert digest["sha256"]
    context_excerpt = task_binder.export_prior_task_context(result.binder)
    assert "prior_task_digest" in context_excerpt
    assert context_excerpt["prior_task_digest"]["preview"]


def test_binder_stale_when_ttl_expires(tmp_path: Path):
    project_root = tmp_path
    binder_path, payload = task_binder.prepare_binder_payload(
        project_root=project_root,
        epic_slug="epic-beta",
        story_slug="story-xyz",
        task_id="TASK-9",
        task_title="",
        problem="",
        invariants=[],
        acceptance=[],
        doc_refs=[],
        git_head="",
        files_section=None,
        evidence=None,
        last_tokens=None,
        previous=None,
        binder_status="miss",
    )
    payload["meta"]["updated_at"] = "0"
    task_binder.write_binder(binder_path, payload, max_bytes=task_binder.DEFAULT_MAX_BYTES)

    result = task_binder.load_for_prompt(
        project_root,
        epic_slug="epic-beta",
        story_slug="story-xyz",
        task_id="TASK-9",
        ttl_seconds=1,
        max_bytes=task_binder.DEFAULT_MAX_BYTES,
    )

    assert result.status == "stale"
