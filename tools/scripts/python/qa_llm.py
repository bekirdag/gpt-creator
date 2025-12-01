#!/usr/bin/env python3
"""LLM-driven QA helper: summarize ready-for-qa tasks and ask an agent to assess."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from llm_client_factory import create_llm_client


READY_QA_STATUSES = {"ready-for-qa", "ready_to_qa", "ready-to-qa"}


def _default_db(project_root: Path) -> Path:
    return project_root / ".gpt-creator" / "staging" / "plan" / "tasks" / "tasks.db"


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


def _safe_tail(path: Path, limit: int = 2000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
        if limit and len(data) > limit:
            return data[-limit:]
        return data
    except Exception:
        return ""


def _fetch_tasks(cur: sqlite3.Cursor, specific: Optional[str]) -> List[sqlite3.Row]:
    where_clauses = ["LOWER(REPLACE(status,'_','-')) IN ('ready-for-qa','ready_to_qa','ready-to-qa')"]
    params: List[Any] = []
    if specific:
        where_clauses.append("(task_id = ? OR LOWER(story_slug || ':' || (position+1)) = LOWER(?))")
        params.extend([specific, specific])
    sql = f"""
    SELECT id, story_slug, position, task_id, title, status, priority, last_history_summary_path, last_history_meta_path,
           last_notes_json, last_commands_json, last_log_path, last_output_path, last_prompt_path, uid
      FROM tasks
     WHERE {" AND ".join(where_clauses)}
     ORDER BY COALESCE(priority, 1000000) ASC, global_order ASC, position ASC
    """
    cur.execute(sql, params)
    return list(cur.fetchall())


def _render_task_brief(task: sqlite3.Row, project_root: Path) -> str:
    lines: List[str] = []
    ref = task["task_id"] or f"{task['story_slug']}:{int(task['position']) + 1}"
    lines.append(f"Task: {ref}")
    if task["title"]:
        lines.append(f"Title: {task['title']}")
    hist_summary = (task["last_history_summary_path"] or "").strip()
    if hist_summary:
        summary_text = _safe_tail((project_root / hist_summary), limit=3000)
        if summary_text:
            lines.append("Latest plan/focus summary:")
            lines.append(summary_text)
    hist_meta = (task["last_history_meta_path"] or "").strip()
    if hist_meta:
        meta_text = _safe_tail((project_root / hist_meta), limit=1200)
        if meta_text:
            lines.append("Plan/focus metadata:")
            lines.append(meta_text)
    last_notes = _parse_list(task["last_notes_json"])
    if last_notes:
        lines.append("Task notes:")
        for note in last_notes[:5]:
            lines.append(f"- {note}")
    last_commands = _parse_list(task["last_commands_json"])
    if last_commands:
        lines.append("Commands used:")
        for cmd in last_commands[:4]:
            lines.append(f"- {cmd}")
    output_path = (task["last_output_path"] or "").strip()
    if output_path:
        output_tail = _safe_tail((project_root / output_path).resolve(), limit=2000)
        if output_tail:
            lines.append("Latest patch/output excerpt:")
            lines.append(output_tail)
    return "\n".join(lines)


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
        os.getenv("GC_ACTIVE_AGENT_MODEL")
        or os.getenv("CODEX_MODEL")
        or "gpt-5.1-codex"
    )
    if not adapter:
        return None
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


def _build_prompt(task_brief: str) -> Tuple[str, List[str]]:
    system = (
        "You are a QA agent. Review the context for the task below and outline a concise QA verdict.\n"
        "- Summarize risks and critical checks.\n"
        "- If the task appears incomplete or risky, return a fail verdict.\n"
        "- Output JSON with fields: verdict ('pass' or 'fail'), summary, issues (list of {severity,title,details})."
    )
    user = f"Task QA context:\n{task_brief}\n\nReturn JSON only."
    return system, [user]


def qa_tasks_llm(
    *,
    db_path: Path,
    project_root: Path,
    agent_name: Optional[str],
    client_override: Optional[str],
    model_override: Optional[str],
    task_ref: Optional[str],
) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    adapter = "codex_cli"
    config: Dict[str, Any] = {}
    model = model_override or os.getenv("CODEX_MODEL") or "gpt-5.1-codex"

    env_agent = _load_agent_from_env()
    if env_agent:
        adapter, config, env_model = env_agent
        if not model_override:
            model = env_model

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

    client = create_llm_client(adapter, config)

    tasks = _fetch_tasks(cur, task_ref)
    if not tasks:
        print("No tasks with status ready-for-qa found.", file=sys.stderr)
        return 0

    for task in tasks:
        task_ref_text = task["task_id"] or f"{task['story_slug']}:{int(task['position']) + 1}"
        print(f"QA (LLM) for {task_ref_text} ...", file=sys.stderr)
        brief = _render_task_brief(task, project_root)
        system, messages = _build_prompt(brief)
        result = client.send_chat(
            messages,
            model,
            system=system,
            workdir=str(project_root),
            sandbox="workspace-write",
        )
        print(f"# {task_ref_text}")
        print(result.content.strip())
        print()

    conn.close()
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Run QA via LLM for ready-for-qa tasks.")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Project root (default cwd)")
    parser.add_argument("--db", type=Path, help="Path to tasks.db (default: <project>/.gpt-creator/staging/plan/tasks/tasks.db)")
    parser.add_argument("--agent", help="Agent name to use (defaults to active agent env or codex)")
    parser.add_argument("--client", help="Override LLM client/provider id")
    parser.add_argument("--model", help="Override model id")
    parser.add_argument("--task", help="Specific task id or story:position to QA")
    args = parser.parse_args(argv)

    project_root = args.project.resolve()
    db_path = args.db or _default_db(project_root)
    return qa_tasks_llm(
        db_path=db_path,
        project_root=project_root,
        agent_name=args.agent,
        client_override=args.client,
        model_override=args.model,
        task_ref=args.task,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

