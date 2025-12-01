#!/usr/bin/env python3
"""
Run a Codex apply step for work-on-tasks and return structured results.
This wraps the Codex CLI and patch application to reduce Bash complexity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from llm_client_factory import create_llm_client
from llm_client import ChatResult
import record_codex_usage_lib as codex_usage  # type: ignore


def resolve_cli_root() -> Path:
    """Best-effort detection of the CLI root for helper scripts."""
    env_root = os.getenv("CLI_ROOT") or os.getenv("GC_CLI_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    # tools/scripts/python -> scripts live at parents[3]/scripts
    return Path(__file__).resolve().parents[3]


def log_debug(project_root: Path, message: str) -> None:
    """Append lightweight debug breadcrumbs for troubleshooting."""
    ts = datetime.utcnow().isoformat() + "Z"
    log_path = project_root / ".gpt-creator" / "logs" / "work-on-tasks-apply.debug.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{ts} {message}\n")
    except Exception:
        # Never block on logging; this is best-effort only.
        pass


def run_codex(call_name: str, step: str, prompt_path: Path, output_path: Path, project_root: Path) -> tuple[subprocess.CompletedProcess, Path]:
    # Keep the Codex invocation minimal and non-interactive: feed prompt via stdin
    # and constrain the sandbox to workspace-write.
    stderr_log = project_root / ".gpt-creator" / "logs" / "codex-apply" / f"{call_name}.stderr.log"
    try:
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    cmd = [
        "bash",
        "-lc",
        (
            f"codex exec --model \"${{CODEX_MODEL:-{os.getenv('CODEX_MODEL','gpt-5.1-codex')}}}\" "
            f"-c task_name=\"{call_name}\" "
            f"--sandbox workspace-write "
            f"--cd \"{project_root}\" "
            f"< '{prompt_path}' > '{output_path}' "
            f"2> >(tee -a '{stderr_log}' >&2)"
        ),
    ]
    log_debug(project_root, f"[codex] launching (step={step}) cmd={cmd[2]}")
    # Stream stderr to the user (inherited), while also tee'ing into a logfile.
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
    return proc, stderr_log


def record_usage(project_root: Path, task_id: str, model: str, stderr_log: Path, prompt_path: Path, output_path: Path, rc: int) -> None:
    """Append a usage entry to codex-usage.ndjson."""
    usage_file = project_root / ".gpt-creator" / "logs" / "codex-usage.ndjson"
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().isoformat() + "Z"
    try:
        # We don't have token counts; use 0s but capture rc and log path for auditing.
        entry = {
            "timestamp": ts,
            "task": task_id,
            "model": model,
            "prompt_path": str(prompt_path),
            "output_path": str(output_path),
            "stderr_log": str(stderr_log),
            "exit": rc,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "captured": False,
        }
        with usage_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log_debug(project_root, f"[usage] failed to record codex usage: {exc}")


def run_generic_agent(adapter: str, model: str, prompt_path: Path, output_path: Path, project_root: Path) -> ChatResult:
    """Run a non-Codex adapter via llm_client_factory."""
    agent_file = os.getenv("GC_ACTIVE_AGENT_FILE", "").strip()
    config: Dict[str, object] = {}
    if agent_file:
        try:
            data = json.loads(Path(agent_file).read_text(encoding="utf-8"))
            # Agents registry stores config fields at the top level or under "agent"
            if isinstance(data, dict):
                config = data.get("agent") or data  # type: ignore[assignment]
                if not isinstance(config, dict):
                    config = {}
        except Exception as exc:  # pragma: no cover - best effort
            log_debug(project_root, f"[agent] failed to read agent file {agent_file}: {exc}")
    # Fallback adapter config from environment if provided
    adapter_cfg_env = os.getenv("GC_AGENT_CONFIG_JSON", "").strip()
    if adapter_cfg_env and not config:
        try:
            env_cfg = json.loads(adapter_cfg_env)
            if isinstance(env_cfg, dict):
                config = env_cfg
        except Exception:
            pass

    llm = create_llm_client(adapter, config or {})
    prompt_text = prompt_path.read_text(encoding="utf-8")
    result = llm.send_chat([prompt_text], model=model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.content, encoding="utf-8")
    return result


def apply_patch(output_path: Path, project_root: Path, patch_artifact_path: Path) -> subprocess.CompletedProcess:
    cli_root = resolve_cli_root()
    helper = None
    candidates = [
        cli_root / "scripts" / "auto_apply_patch.sh",
        cli_root / "tools" / "scripts" / "auto_apply_patch.sh",
    ]
    for candidate in candidates:
        if candidate.is_file():
            helper = candidate
            break
    if helper is None:
        return subprocess.CompletedProcess(
            args=[],
            returncode=127,
            stdout="",
            stderr="auto_apply_patch.sh not found; apply changes manually.",
        )

    cmd = [
        "bash",
        "-lc",
        f"BASH={os.getenv('BASH','bash')} GC_APPLY_PATCH_PROJECT_ROOT='{project_root}' '{helper}' '{output_path}' '{patch_artifact_path}'",
    ]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def fingerprint_diff() -> str:
    proc = subprocess.run(["bash", "-lc", "git status --porcelain | sha256sum | awk '{print $1}'"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode == 0:
        return proc.stdout.strip()
    return ""


def emit_plain(result: Dict[str, Optional[object]]) -> None:
    print(f"APPLY_STATUS:{result.get('apply_status','')}")
    print(f"STATUS:{result.get('status','')}")
    tokens = result.get("tokens", {}) or {}
    print(f"TOKENS_PROMPT:{tokens.get('prompt', 0)}")
    print(f"TOKENS_COMPLETION:{tokens.get('completion', 0)}")
    print(f"TOKENS_TOTAL:{tokens.get('total', 0)}")
    for note in result.get("notes", []) or []:
        print(f"NOTE:{note}")


def main(argv: List[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--call-name", required=True)
    parser.add_argument("--step", default="patch")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--patch-artifact", required=True)
    parser.add_argument("--contract-guard", action="store_true")
    parser.add_argument("--diff-guard", action="store_true")
    args = parser.parse_args(argv)

    prompt_path = Path(args.prompt)
    output_path = Path(args.output)
    project_root = Path(args.project_root)
    patch_artifact_path = Path(args.patch_artifact)

    result: Dict[str, Optional[object]] = {
        "status": "unknown",
        "tokens": {"prompt": 0, "completion": 0, "total": 0},
        "apply_status": "",
        "notes": [],
        "patch_artifact": str(patch_artifact_path),
    }

    diff_before = fingerprint_diff() if args.diff_guard else ""
    adapter = (os.getenv("GC_ACTIVE_AGENT_ADAPTER", "codex_cli") or "codex_cli").strip().lower()
    model = (
        os.getenv("DEFAULT_LLM")
        or os.getenv("CODEX_MODEL")
        or os.getenv("GC_ACTIVE_AGENT_MODEL")
        or "gpt-5.1-codex-max"
    )
    chat_result: Optional[ChatResult] = None

    if adapter in {"codex_cli", "openai_cli", "openai", ""}:
        proc, stderr_log = run_codex(args.call_name, args.step, prompt_path, output_path, project_root)
        log_debug(project_root, f"[codex] completed rc={proc.returncode} (see stderr log at {stderr_log})")
        record_usage(project_root, args.call_name, model, stderr_log, prompt_path, output_path, proc.returncode)
        if proc.returncode != 0:
            result["status"] = "codex-failed"
            stderr_snippet = ""
            try:
                if stderr_log.exists():
                    text = stderr_log.read_text(encoding="utf-8", errors="ignore")
                    stderr_snippet = text.splitlines()[-1] if text else ""
            except Exception:
                stderr_snippet = ""
            if stderr_snippet:
                result["notes"].append(f"Codex failed: {stderr_snippet}")
            result["notes"].append(f"Codex stderr log: {stderr_log}")
            emit_plain(result)
            return 0
    else:
        try:
            chat_result = run_generic_agent(adapter, model, prompt_path, output_path, project_root)
        except Exception as exc:
            log_debug(project_root, f"[agent] adapter '{adapter}' failed: {exc}")
            result["status"] = "agent-failed"
            result["apply_status"] = "agent-failed"
            result["notes"].append(f"Agent adapter '{adapter}' failed: {exc}")
            emit_plain(result)
            return 0

    # Token accounting from environment if available
    prompt_tokens = int(os.getenv("GC_LAST_CODEX_PROMPT_TOKENS", "0") or 0)
    completion_tokens = int(os.getenv("GC_LAST_CODEX_COMPLETION_TOKENS", "0") or 0)
    total_tokens = int(os.getenv("GC_CODEX_CALL_TOKEN_ACCUM", os.getenv("GC_LAST_CODEX_TOTAL_TOKENS", "0")) or 0)
    if chat_result is not None:
        prompt_tokens = getattr(chat_result.tokens, "prompt", prompt_tokens)
        completion_tokens = getattr(chat_result.tokens, "completion", completion_tokens)
        total_tokens = prompt_tokens + completion_tokens
    result["tokens"] = {"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens}

    if not output_path.exists() or output_path.stat().st_size == 0:
        log_debug(project_root, "[codex] produced empty output file")
        result["status"] = "empty-output"
        result["apply_status"] = "no-output"
        result["notes"].append("Codex produced no output.")
        emit_plain(result)
        return 0

    apply_proc = apply_patch(output_path, project_root, patch_artifact_path)
    log_debug(project_root, f"[apply] completed rc={apply_proc.returncode}")
    if apply_proc.returncode != 0:
        result["status"] = "apply-failed"
        result["apply_status"] = "apply-failed"
        result["notes"].append(apply_proc.stderr.strip() or apply_proc.stdout.strip())
        emit_plain(result)
        return 0

    apply_output = apply_proc.stdout.strip()
    if apply_output in {"no-output", "empty-output"}:
        log_debug(project_root, "[apply] no-output/empty-output from auto_apply_patch")
        result["status"] = "empty-apply"
        result["apply_status"] = apply_output
        result["notes"].append("Patch apply returned no actionable changes.")
        emit_plain(result)
        return 0

    if args.diff_guard:
        diff_after = fingerprint_diff()
        if diff_before and diff_after and diff_before == diff_after:
            log_debug(project_root, "[apply] diff guard detected no changes")
            result["status"] = "no-diff"
            result["apply_status"] = "no-diff"
            result["notes"].append("No diff detected after apply.")
            emit_plain(result)
            return 0

    result["status"] = "ok"
    result["apply_status"] = "applied"
    emit_plain(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
