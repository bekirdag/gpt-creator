#!/usr/bin/env python3
"""Code review helper: review ready-to-review tasks and record findings."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import time


def _prepend_sys_path(path: Path) -> None:
    resolved = str(path)
    if resolved and resolved not in sys.path:
        sys.path.insert(0, resolved)


SCRIPT_DIR = Path(__file__).resolve().parent
_prepend_sys_path(SCRIPT_DIR)
_prepend_sys_path(SCRIPT_DIR.parent)

from llm_client_factory import create_llm_client
from task_comments import ensure_task_comments_schema, insert_task_comment
from update_task_state import update_task_state


def _record_usage(project_root: Path, task_ref: str, model: str, adapter: str, prompt_tokens: int, completion_tokens: int, exit_code: int = 0) -> None:
    log_dir = Path(os.getenv("LOG_DIR") or project_root / ".gpt-creator" / "logs")
    primary = Path(os.getenv("GC_USAGE_FILE") or log_dir / "usage.ndjson")
    legacy = log_dir / "codex-usage.ndjson"
    paths = [primary]
    if legacy != primary:
        paths.append(legacy)
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "run_id": os.getenv("GC_ACTIVE_RUN_STAMP") or os.getenv("GC_BUDGET_RUN_ID") or "manual",
        "task": task_ref,
        "model": model,
        "adapter": adapter,
        "tokens_in": int(prompt_tokens or 0),
        "tokens_out": int(completion_tokens or 0),
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int((prompt_tokens or 0) + (completion_tokens or 0)),
        "exit_code": int(exit_code),
        "usage_captured": True,
        "source": "review",
    }
    telemetry_payload = os.getenv("AGENT_TELEMETRY_PAYLOAD", "").strip()
    if telemetry_payload:
        entry["telemetry_payload"] = telemetry_payload
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except Exception:
            continue


def _normalize_status(value: str) -> str:
    text = (value or "").strip().lower().replace("_", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


READY_STATUSES = {"ready-to-review", "ready_to_review", "ready-to-review-no-changes"}


def _default_db(project_root: Path) -> Path:
    return project_root / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"


def _safe_read(path: Path, limit: int = 4000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
        if limit and len(data) > limit:
            return data[-limit:]
        return data
    except Exception:
        return ""


def _load_adapter_config(cur: sqlite3.Cursor, provider_id: str) -> Tuple[str, Dict[str, Any]]:
    row = cur.execute(
        "SELECT adapter, metadata_json FROM llm_providers WHERE id = ? LIMIT 1",
        (provider_id,),
    ).fetchone()
    if row is None:
        return "codex_cli", {}
    adapter = (row[0] or "codex_cli").strip()
    metadata: Dict[str, Any] = {}
    raw_meta = row[1]
    if raw_meta:
        try:
            metadata = json.loads(raw_meta)
        except Exception:
            metadata = {}
    if "maxContextTokens" not in metadata:
        metadata["maxContextTokens"] = metadata.get("context_window")
    if "maxOutputTokens" not in metadata:
        metadata["maxOutputTokens"] = metadata.get("default_max_tokens")
    return adapter or "codex_cli", metadata


def _load_agent_from_env() -> Optional[Tuple[str, Dict[str, Any], str]]:
    adapter = (os.getenv("GC_ACTIVE_AGENT_ADAPTER") or "").strip()
    model = (
        os.getenv("DEFAULT_LLM")
        or os.getenv("GC_ACTIVE_AGENT_MODEL")
        or os.getenv("CODEX_MODEL")
        or "gpt-5.1-codex"
    )
    if not adapter and not os.getenv("DEFAULT_AGENT"):
        return None
    # If DEFAULT_AGENT is set but adapter is empty, let the caller resolve via DB; here we only supply config/model.
    config: Dict[str, Any] = {}
    agent_file = (os.getenv("GC_ACTIVE_AGENT_FILE") or "").strip()
    if agent_file:
        try:
            data = json.loads(Path(agent_file).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                config = data.get("agent") or data  # type: ignore[assignment]
                if not isinstance(config, dict):
                    config = {}
        except Exception:
            config = {}
    if not config:
        raw_cfg = (os.getenv("GC_AGENT_CONFIG_JSON") or "").strip()
        if raw_cfg:
            try:
                loaded = json.loads(raw_cfg)
                if isinstance(loaded, dict):
                    config = loaded
            except Exception:
                pass
    return adapter, config, model


def _fetch_tasks(cur: sqlite3.Cursor, specific: Optional[str] = None) -> List[sqlite3.Row]:
    params: List[Any] = []
    where_clauses = ["LOWER(REPLACE(status,'_','-')) IN ('ready-to-review','ready-to-review-no-changes')"]
    if specific:
        params.extend([specific, specific])
        where_clauses.append("(task_id = ? OR LOWER(story_slug || ':' || (position+1)) = LOWER(?))")
    sql = f"""
    SELECT id, story_slug, position, task_id, title, description, acceptance_json, acceptance_text,
           status, priority, last_log_path, last_output_path, last_prompt_path, last_notes_json, last_commands_json,
           last_apply_status, last_changes_applied, last_tokens_total, last_duration_seconds,
           last_history_summary_path, last_history_meta_path, doc_refs, status_reason, uid,
           last_written_json, last_patched_json
      FROM tasks
     WHERE {" AND ".join(where_clauses)}
     ORDER BY COALESCE(priority, 1000000) ASC, global_order ASC, position ASC
    """
    cur.execute(sql, params)
    return list(cur.fetchall())


def _fetch_latest_progress(cur: sqlite3.Cursor, task_row_id: int, story_slug: str, position: int) -> Optional[sqlite3.Row]:
    row = cur.execute(
        """
        SELECT status, log_path, prompt_path, output_path, notes_json, commands_json, attempt_signature,
               occurrence_ts, occurred_at, written_json, patched_json
          FROM (
            SELECT status, log_path, prompt_path, output_path, notes_json, commands_json, attempt_signature,
                   occurred_at as occurrence_ts, occurred_at, written_json, patched_json
              FROM task_progress
             WHERE task_id = ?
             ORDER BY id DESC
          ) LIMIT 1
        """,
        (task_row_id,),
    ).fetchone()
    if row:
        return row
    return cur.execute(
        """
        SELECT status, log_path, prompt_path, output_path, notes_json, commands_json, attempt_signature,
               occurred_at as occurrence_ts, occurred_at, written_json, patched_json
          FROM task_progress
         WHERE story_slug = ? AND task_position = ?
         ORDER BY id DESC
         LIMIT 1
        """,
        (story_slug, position),
    ).fetchone()


def _parse_list(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                return _parse_list(loaded)
        except Exception:
            pass
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return []

def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        return default


def _render_task_context(task: sqlite3.Row, project_root: Path, cur: sqlite3.Cursor) -> str:
    pieces: List[str] = []
    task_ref = task["task_id"] or f"{task['story_slug']}:{int(task['position']) + 1}"
    pieces.append(f"Task: {task_ref}")
    pieces.append(f"Title: {task['title'] or '(untitled)'}")
    desc = (task["description"] or "").strip()
    if desc:
        pieces.append("Description:")
        pieces.append(desc)
    acceptance = _parse_list(task["acceptance_json"]) or _parse_list(task["acceptance_text"])
    if acceptance:
        pieces.append("Acceptance criteria:")
        for item in acceptance[:8]:
            pieces.append(f"- {item}")
    if task["doc_refs"]:
        pieces.append(f"Doc refs: {task['doc_refs']}")
    status_reason = (task["status_reason"] or "").strip()
    if status_reason:
        pieces.append(f"Status reason: {status_reason}")

    history_summary_path = (task["last_history_summary_path"] or "").strip()
    history_meta_path = (task["last_history_meta_path"] or "").strip()
    if history_summary_path:
        summary_path = (project_root / history_summary_path).resolve()
        summary_text = _safe_read(summary_path, limit=4000)
        if summary_text:
            pieces.append("Latest plan/focus summary:")
            pieces.append(summary_text)
    if history_meta_path:
        meta_path = (project_root / history_meta_path).resolve()
        meta_text = _safe_read(meta_path, limit=1500)
        if meta_text:
            pieces.append("Plan/focus metadata:")
            pieces.append(meta_text)

    last_notes = _parse_list(task["last_notes_json"])
    if last_notes:
        pieces.append("Task notes:")
        for note in last_notes[:6]:
            pieces.append(f"- {note}")
    last_commands = _parse_list(task["last_commands_json"])
    if last_commands:
        pieces.append("Commands used:")
        for cmd in last_commands[:5]:
            pieces.append(f"- {cmd}")
    command_hints: List[str] = []
    for candidate in (last_commands or []):
        text = candidate.lower()
        if any(token in text for token in ("lint", "eslint", "prettier", "test", "vitest", "jest", "playwright", "cypress")):
            command_hints.append(candidate)

    progress = _fetch_latest_progress(cur, int(task["id"]), task["story_slug"], int(task["position"]))
    if progress:
        pieces.append(f"Latest attempt status: {progress['status'] or '(unknown)'}")
        prog_notes = _parse_list(progress["notes_json"])
        if prog_notes:
            pieces.append("Latest attempt notes:")
            for note in prog_notes[:5]:
                pieces.append(f"- {note}")
        prog_cmds = _parse_list(progress["commands_json"])
        if prog_cmds:
            pieces.append("Latest attempt commands:")
            for cmd in prog_cmds[:4]:
                pieces.append(f"- {cmd}")
            for candidate in prog_cmds:
                text = candidate.lower()
                if any(token in text for token in ("lint", "eslint", "prettier", "test", "vitest", "jest", "playwright", "cypress")):
                    command_hints.append(candidate)
        log_path = (progress["log_path"] or "").strip()
        if log_path:
            log_resolved = (project_root / log_path).resolve()
            log_excerpt = _safe_read(log_resolved, limit=2000)
            if log_excerpt:
                pieces.append("Log excerpt (tail):")
                pieces.append(log_excerpt)
        written_paths = _parse_list(_row_get(progress, "written_json"))
        patched_paths = _parse_list(_row_get(progress, "patched_json"))
        if written_paths or patched_paths:
            pieces.append("Files touched:")
            for entry in (written_paths + patched_paths)[:12]:
                pieces.append(f"- {entry}")

    last_written = _parse_list(_row_get(task, "last_written_json"))
    last_patched = _parse_list(_row_get(task, "last_patched_json"))
    if last_written or last_patched:
        pieces.append("Files changed (latest task snapshot):")
        for entry in (last_written + last_patched)[:12]:
            pieces.append(f"- {entry}")

    output_path = (_row_get(task, "last_output_path") or "").strip()
    if output_path:
        output_tail = _safe_read((project_root / output_path).resolve(), limit=4000)
        if output_tail:
            pieces.append("Latest patch/output excerpt:")
            pieces.append(output_tail)
    if command_hints:
        pieces.append("Tests/Lint commands observed:")
        for cmd in command_hints[:6]:
            pieces.append(f"- {cmd}")
    return "\n".join(pieces)


def _build_prompt(task_context: str) -> Tuple[str, List[str]]:
    system = (
        "You are a senior code review agent. Review the work for the task below.\n"
        "- Do NOT write or edit code.\n"
        "- Identify correctness, security, accessibility, and UX issues.\n"
        "- Consider acceptance criteria and previous notes.\n"
        "- Be concise; prefer bullets.\n"
        "Output JSON with fields: verdict ('pass' or 'fail'), summary (short), "
        "issues (list of {severity: 'blocking'|'warning', title, details})."
    )
    user = f"Task context:\n{task_context}\n\nReturn the JSON only."
    return system, [user]


def _parse_review_response(text: str) -> Dict[str, Any]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= 0:
            trimmed = text[start : end + 1]
            return json.loads(trimmed)
    except Exception:
        pass
    return {"verdict": "fail", "summary": "Unparseable review output", "issues": [{"severity": "blocking", "title": "parser", "details": text[:500]}]}


def review_tasks(
    *,
    db_path: Path,
    project_root: Path,
    agent_name: Optional[str],
    client_override: Optional[str],
    model_override: Optional[str],
    max_issues: int,
    max_output_chars: int,
    dry_run: bool,
    task_ref: Optional[str],
) -> int:
    if not db_path.exists():
        print(f"Tasks database not found at {db_path}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ensure_task_comments_schema(cur)

    adapter = "codex_cli"
    config: Dict[str, Any] = {}
    model = (
        model_override
        or os.getenv("DEFAULT_LLM")
        or os.getenv("CODEX_MODEL")
        or "gpt-5.1-codex"
    )

    # Highest precedence: active agent environment (registry).
    env_agent = _load_agent_from_env()
    if env_agent:
        adapter, config, env_model = env_agent
        if not model_override:
            model = env_model

    # Resolve adapter/config/model from agents table when provided.
    if agent_name:
        agent_row = cur.execute(
            "SELECT name, client, model, llm_provider_id, llm_model_id FROM agents WHERE name = ? LIMIT 1",
            (agent_name,),
        ).fetchone()
        if agent_row:
            provider_id = (agent_row["llm_provider_id"] or agent_row["client"] or "").strip()
            resolved_provider = client_override or provider_id or agent_row["client"]
            adapter, config = _load_adapter_config(cur, resolved_provider)
            model = model_override or agent_row["llm_model_id"] or agent_row["model"] or model
    if client_override and not agent_name:
        adapter, config = _load_adapter_config(cur, client_override)
    if model_override:
        model = model_override

    try:
        client = create_llm_client(adapter, config)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to initialize LLM client (adapter={adapter}, model={model}): {exc}", file=sys.stderr)
        conn.close()
        return 1

    if not agent_name:
        agent_name = os.getenv("DEFAULT_AGENT", "")

    tasks = _fetch_tasks(cur, specific=task_ref)
    if not tasks:
        print("No tasks with status ready-to-review/ready-to-qa found.", file=sys.stderr)
        return 0

    for task in tasks:
        task_ref_text = task["task_id"] or f"{task['story_slug']}:{int(task['position']) + 1}"
        print(f"Reviewing {task_ref_text} ...", file=sys.stderr)
        context_text = _render_task_context(task, project_root, cur)
        system, messages = _build_prompt(context_text)
        start_ts = time.time()
        try:
            result = client.send_chat(
                messages,
                model,
                system=system,
                workdir=str(project_root),
                sandbox="workspace-write",
            )
        except Exception as exc:
            print(f"Review for {task_ref_text} failed: {exc}", file=sys.stderr)
            return 1
        duration_s = time.time() - start_ts
        parsed = _parse_review_response(result.content)
        verdict = (parsed.get("verdict") or "").strip().lower()
        if verdict not in {"pass", "fail"}:
            verdict = "fail"
        summary = (parsed.get("summary") or "").strip() or "No summary provided."
        issues = parsed.get("issues") or []
        issues_text = []
        suggested_fix = ""
        if isinstance(issues, list):
            limited_issues = issues[:max_issues] if max_issues > 0 else issues
            for issue in limited_issues:
                if not isinstance(issue, dict):
                    continue
                sev = issue.get("severity") or "warning"
                title = issue.get("title") or ""
                details = issue.get("details") or ""
                issues_text.append(f"[{sev}] {title} — {details}")
                if not suggested_fix and details:
                    suggested_fix = details[:500]
        tokens_prompt = getattr(getattr(result, "tokens", None), "prompt", 0) or 0
        tokens_completion = getattr(getattr(result, "tokens", None), "completion", 0) or 0
        _record_usage(project_root, task_ref_text, model, adapter, tokens_prompt, tokens_completion, exit_code=0)
        body_lines = [
            f"Verdict: {verdict}",
            f"Summary: {summary}",
            f"LLM tokens: prompt={tokens_prompt}, completion={tokens_completion}, duration={duration_s:.1f}s",
            "Issues:",
        ]
        if issues_text:
            body_lines.extend(f"- {line}" for line in issues_text)
        else:
            body_lines.append("- None reported")
        comment_body_full = "\n".join(body_lines)
        if max_output_chars > 0 and len(comment_body_full) > max_output_chars:
            comment_body = comment_body_full[:max_output_chars]
        else:
            comment_body = comment_body_full
        next_status = "ready-for-qa" if verdict == "pass" else "pending"
        if not dry_run:
            insert_task_comment(
                cur,
                task_row_id=int(task["id"]),
                task_uid=task["uid"],
                story_slug=task["story_slug"],
                task_ref=task_ref_text,
                commenter=agent_name or "code-review",
                details=comment_body,
                status_from=task["status"],
                status_to=next_status,
                severity="blocking" if verdict != "pass" else "info",
                component="code",
                suggested_fix=suggested_fix,
                blocking=(verdict != "pass"),
            )
            update_task_state(
                db_path,
                task["story_slug"],
                str(int(task["position"])),
                next_status,
                "review-run",
            )
            conn.commit()
        print(f"  → status {task['status']} -> {next_status} (verdict={verdict})", file=sys.stderr)
    conn.close()
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Run code review over ready-to-review tasks.")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project root (default cwd)")
    parser.add_argument("--db", type=Path, help="Path to tasks.db (default: <project>/.gpt-creator/staging/plan/tasks/tasks.db)")
    parser.add_argument("--agent", help="Agent name to use for the review (defaults to codex_cli adapter)")
    parser.add_argument("--client", help="Override LLM client/provider id for review")
    parser.add_argument("--model", help="Override model id for review")
    parser.add_argument("--max-issues", type=int, default=10, help="Cap number of issues emitted (0 = no cap)")
    parser.add_argument("--max-output", type=int, default=4000, help="Cap review comment length in chars (0 = no cap)")
    parser.add_argument("--task", help="Specific task id or story:position to review")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating statuses/comments")
    args = parser.parse_args(argv)

    client_override = args.client or os.getenv("GC_REVIEW_CLIENT")
    model_override = args.model or os.getenv("GC_REVIEW_MODEL")
    max_issues = args.max_issues
    max_output = args.max_output
    try:
        env_max_issues = int(os.getenv("GC_REVIEW_MAX_ISSUES", "").strip() or max_issues)
        max_issues = env_max_issues
    except Exception:
        pass
    try:
        env_max_output = int(os.getenv("GC_REVIEW_MAX_OUTPUT", "").strip() or max_output)
        max_output = env_max_output
    except Exception:
        pass

    project_root = args.project.resolve()
    db_path = args.db or _default_db(project_root)
    return review_tasks(
        db_path=db_path,
        project_root=project_root,
        agent_name=args.agent,
        client_override=client_override,
        model_override=model_override,
        max_issues=max_issues,
        max_output_chars=max_output,
        dry_run=args.dry_run,
        task_ref=args.task,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
