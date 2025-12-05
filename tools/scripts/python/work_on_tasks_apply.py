#!/usr/bin/env python3
"""
Run an adapter apply step for work-on-tasks and return structured results.
This wraps the adapter invocation and patch application to reduce Bash complexity.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from llm_client_factory import create_llm_client
from llm_client import ChatResult
from agents_registry import AgentRegistry


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


def usage_paths(project_root: Path) -> list[Path]:
    """Return usage log paths (primary + legacy)."""
    log_dir = Path(os.getenv("LOG_DIR") or project_root / ".gpt-creator" / "logs")
    primary = Path(os.getenv("GC_USAGE_FILE") or log_dir / "usage.ndjson")
    legacy = log_dir / "codex-usage.ndjson"
    paths = [primary]
    if legacy != primary:
        paths.append(legacy)
    return paths


def parse_token_counts(log_path: Path) -> Dict[str, int]:
    """Best-effort token extraction from Codex stderr log."""
    counts: Dict[str, int] = {}
    if not log_path.exists():
        return counts

    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return counts

    def parse_number(value: str) -> int:
        cleaned = value.strip().replace(",", "").replace("_", "").replace(" ", "")
        return int(cleaned) if cleaned and cleaned.isdigit() else 0

    patterns = {
        "total": re.compile(r"tokens?\s+used[:\s]+([0-9][0-9,._ ]*)", re.IGNORECASE),
        "prompt": re.compile(r"prompt\s+tokens?[:\s]+([0-9][0-9,._ ]*)", re.IGNORECASE),
        "completion": re.compile(r"completion\s+tokens?[:\s]+([0-9][0-9,._ ]*)", re.IGNORECASE),
    }

    pending_key = ""

    for line in text.splitlines():
        stripped = line.strip()

        if pending_key:
            try:
                value = parse_number(stripped)
            except Exception:
                value = 0
            if value:
                counts[pending_key] = value
            pending_key = ""
            continue

        matched = False
        for key, pattern in patterns.items():
            match = pattern.search(line)
            if match:
                value = parse_number(match.group(1))
                if value:
                    counts[key] = value
                    matched = True
        if matched:
            continue

        # Handle two-line output where the number is on the next line
        if re.match(r"^tokens?\s+used\b", stripped, re.IGNORECASE):
            pending_key = "total"
            continue
        if re.match(r"^prompt\s+tokens?\b", stripped, re.IGNORECASE):
            pending_key = "prompt"
            continue
        if re.match(r"^completion\s+tokens?\b", stripped, re.IGNORECASE):
            pending_key = "completion"
            continue

    if "total" not in counts and ("prompt" in counts or "completion" in counts):
        counts["total"] = counts.get("prompt", 0) + counts.get("completion", 0)

    return counts


def run_codex(
    call_name: str,
    step: str,
    prompt_path: Path,
    output_path: Path,
    project_root: Path,
    model_hint: str | None = None,
) -> tuple[subprocess.CompletedProcess, Path]:
    # Keep the Codex invocation minimal and non-interactive: feed prompt via stdin
    # and constrain the sandbox to workspace-write.
    stderr_log = project_root / ".gpt-creator" / "logs" / "codex-apply" / f"{call_name}.stderr.log"
    try:
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    default_model = (
        os.getenv("CODEX_MODEL")
        or os.getenv("GC_ACTIVE_AGENT_MODEL")
        or os.getenv("DEFAULT_LLM")
        or model_hint
    )
    if not default_model:
        raise RuntimeError(
            "No model resolved for codex-style adapter runs; set GC_ACTIVE_AGENT_MODEL or DEFAULT_LLM."
        )
    cmd = [
        "bash",
        "-lc",
        (
            f"codex exec --model \"{default_model}\" "
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


def record_usage(
    project_root: Path,
    task_id: str,
    adapter: str,
    model: str,
    step: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    exit_code: int,
    status: str,
    usage_captured: bool,
) -> None:
    """Append an adapter-neutral usage entry to usage logs."""
    ts = datetime.utcnow().isoformat() + "Z"
    story_slug = os.getenv("GC_ACTIVE_TASK_SLUG", "") or None
    run_id = os.getenv("GC_ACTIVE_RUN_STAMP") or os.getenv("GC_BUDGET_RUN_ID") or "manual"
    if not adapter:
        adapter = os.getenv("GC_ACTIVE_AGENT_ADAPTER") or os.getenv("GC_ACTIVE_ADAPTER") or "unknown-adapter"
    if not model:
        model = os.getenv("GC_ACTIVE_MODEL") or os.getenv("DEFAULT_LLM") or model
    total = total_tokens or (prompt_tokens + completion_tokens)
    entry = {
        "timestamp": ts,
        "run_id": run_id,
        "task": task_id,
        "story": story_slug,
        "adapter": adapter,
        "model": model,
        "step": step,
        "stage": step,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens_in": prompt_tokens,
        "tokens_out": completion_tokens,
        "total_tokens": total,
        "exit_code": exit_code,
        "usage_captured": usage_captured,
        "status": status,
        "source": "adapter-call",
    }
    telemetry_payload = os.getenv("AGENT_TELEMETRY_PAYLOAD", "").strip()
    if telemetry_payload:
        entry["telemetry_payload"] = telemetry_payload
    for path in usage_paths(project_root):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except Exception as exc:
            log_debug(project_root, f"[usage] failed to append usage to {path}: {exc}")


def merge_registry_config(
    config: Dict[str, object],
    registry_cfg: Optional[Dict[str, object]],
) -> Dict[str, object]:
    """Overlay agent config with registry metadata (adapterConfig, headers, limits)."""
    if not registry_cfg:
        return config
    merged: Dict[str, object] = dict(registry_cfg)
    # Preserve explicit agent overrides where present
    for key, value in config.items():
        if key == "adapterConfig":
            if value:
                merged["adapterConfig"] = value
            elif registry_cfg.get("adapterConfig") and not merged.get("adapterConfig"):
                merged["adapterConfig"] = registry_cfg["adapterConfig"]
        else:
            merged[key] = value
    return merged


def run_generic_agent(
    adapter: str,
    model: str,
    prompt_path: Path,
    output_path: Path,
    project_root: Path,
    registry_cfg: Optional[Dict[str, object]] = None,
) -> ChatResult:
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

    if registry_cfg:
        config = merge_registry_config(config, registry_cfg)

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
    agent_flag = os.getenv("GC_AGENT_FLAG", "").strip().lower() not in {"", "0", "false", "no"}
    active_client = os.getenv("GC_ACTIVE_AGENT_CLIENT", "").strip().lower()
    active_model_env = os.getenv("GC_ACTIVE_AGENT_MODEL", "").strip()
    adapter = (os.getenv("GC_ACTIVE_AGENT_ADAPTER", "") or "").strip().lower()
    agent_file_path = (os.getenv("GC_ACTIVE_AGENT_FILE", "") or "").strip()
    agent_file_model = ""
    agent_file_adapter = ""
    agent_file_client = ""
    if agent_file_path:
        try:
            data = json.loads(Path(agent_file_path).read_text(encoding="utf-8"))
            agent_data = data.get("agent") or data
            if isinstance(agent_data, dict):
                agent_file_model = (agent_data.get("model") or "").strip()
                agent_file_adapter = (agent_data.get("adapter") or "").strip().lower()
                agent_file_client = (agent_data.get("client") or "").strip().lower()
        except Exception:
            pass
    if not adapter and agent_file_adapter:
        adapter = agent_file_adapter
    if not active_model_env and agent_file_model:
        active_model_env = agent_file_model
    if not active_client and agent_file_client:
        active_client = agent_file_client
    registry_model = ""
    # Prefer the agent’s model, then user defaults, then Codex defaults.
    model = active_model_env or os.getenv("DEFAULT_LLM") or registry_model or ""
    if not model:
        raise SystemExit("[agent] No model resolved (set DEFAULT_LLM or select an agent with a model).")
    # Force OSS clients onto command adapter and their own model when not overridden.
    if active_client in {"gpt-oss", "ollama"} and not adapter:
        adapter = "command"
        model = active_model_env or model
    registry_cfg: Optional[Dict[str, object]] = None
    if active_client:
        try:
            registry_cfg = AgentRegistry.load().validate_pair(active_client, model)
            registry_adapter = (registry_cfg.get("adapter") or "").strip().lower()
            registry_model = (registry_cfg.get("model") or "").strip()
            if not adapter:
                adapter = registry_adapter
            if registry_model:
                model = registry_model
        except Exception as exc:  # pragma: no cover - defensive
            log_debug(project_root, f"[agent] registry lookup failed: {exc}")
    if not adapter:
        raise SystemExit(f"[agent] No adapter resolved for client '{active_client}' (set GC_ACTIVE_AGENT_ADAPTER or registry adapter).")
    if agent_flag and active_client in {"gpt-oss", "ollama"} and adapter in {"codex_cli", "openai_cli", "openai"}:
        adapter = "command"
    chat_result: Optional[ChatResult] = None
    parsed_tokens: Dict[str, int] = {}
    adapter_exit_code = 0

    if adapter in {"codex_cli", "openai_cli", "openai"}:
        proc, stderr_log = run_codex(
            args.call_name,
            args.step,
            prompt_path,
            output_path,
            project_root,
            model_hint=model,
        )
        adapter_exit_code = proc.returncode
        log_debug(project_root, f"[codex] completed rc={proc.returncode} (see stderr log at {stderr_log})")
        parsed_tokens = parse_token_counts(stderr_log)
        if proc.returncode != 0:
            result["status"] = "adapter-failed"
            result["apply_status"] = "adapter-failed"
            stderr_snippet = ""
            try:
                if stderr_log.exists():
                    text = stderr_log.read_text(encoding="utf-8", errors="ignore")
                    stderr_snippet = text.splitlines()[-1] if text else ""
            except Exception:
                stderr_snippet = ""
            if stderr_snippet:
                result["notes"].append(f"Adapter '{adapter}' failed: {stderr_snippet}")
            result["notes"].append(f"Adapter stderr log: {stderr_log}")
    else:
        try:
            chat_result = run_generic_agent(adapter, model, prompt_path, output_path, project_root, registry_cfg)
        except Exception as exc:
            log_debug(project_root, f"[agent] adapter '{adapter}' failed: {exc}")
            result["status"] = "adapter-failed"
            result["apply_status"] = "adapter-failed"
            result["notes"].append(f"Adapter '{adapter}' failed: {exc}")
            adapter_exit_code = 1

    # Token accounting from environment if available
    prompt_tokens = int(os.getenv("GC_LAST_CODEX_PROMPT_TOKENS", "0") or 0)
    completion_tokens = int(os.getenv("GC_LAST_CODEX_COMPLETION_TOKENS", "0") or 0)
    total_tokens = int(os.getenv("GC_CODEX_CALL_TOKEN_ACCUM", os.getenv("GC_LAST_CODEX_TOTAL_TOKENS", "0")) or 0)
    if chat_result is not None:
        prompt_tokens = getattr(chat_result.tokens, "prompt", prompt_tokens)
        completion_tokens = getattr(chat_result.tokens, "completion", completion_tokens)
        total_tokens = prompt_tokens + completion_tokens
    if parsed_tokens:
        if prompt_tokens == 0 and parsed_tokens.get("prompt", 0):
            prompt_tokens = parsed_tokens["prompt"]
        if completion_tokens == 0 and parsed_tokens.get("completion", 0):
            completion_tokens = parsed_tokens["completion"]
        if total_tokens == 0 and parsed_tokens.get("total", 0):
            total_tokens = parsed_tokens["total"]
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
    result["tokens"] = {"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens}

    usage_captured = any(val > 0 for val in (prompt_tokens, completion_tokens, total_tokens))
    if result["status"] == "adapter-failed":
        record_usage(
            project_root,
            args.call_name,
            adapter,
            model,
            args.step,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            adapter_exit_code,
            result["status"],
            usage_captured,
        )
        emit_plain(result)
        return 0

    if not output_path.exists() or output_path.stat().st_size == 0:
        log_debug(project_root, "[adapter] produced empty output file")
        result["status"] = "empty-output"
        result["apply_status"] = "no-output"
        result["notes"].append("Adapter produced no output.")
        record_usage(
            project_root,
            args.call_name,
            adapter,
            model,
            args.step,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            adapter_exit_code,
            result["status"],
            usage_captured,
        )
        emit_plain(result)
        return 0

    apply_proc = apply_patch(output_path, project_root, patch_artifact_path)
    log_debug(project_root, f"[apply] completed rc={apply_proc.returncode}")
    if apply_proc.returncode != 0:
        result["status"] = "apply-failed"
        result["apply_status"] = "apply-failed"
        result["notes"].append(apply_proc.stderr.strip() or apply_proc.stdout.strip())
        record_usage(
            project_root,
            args.call_name,
            adapter,
            model,
            args.step,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            adapter_exit_code,
            result["status"],
            usage_captured,
        )
        emit_plain(result)
        return 0

    apply_output = apply_proc.stdout.strip()
    if apply_output in {"no-output", "empty-output"}:
        log_debug(project_root, "[apply] no-output/empty-output from auto_apply_patch")
        result["status"] = "empty-apply"
        result["apply_status"] = apply_output
        result["notes"].append("Patch apply returned no actionable changes.")
        record_usage(
            project_root,
            args.call_name,
            adapter,
            model,
            args.step,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            adapter_exit_code,
            result["status"],
            usage_captured,
        )
        emit_plain(result)
        return 0

    if args.diff_guard:
        diff_after = fingerprint_diff()
        if diff_before and diff_after and diff_before == diff_after:
            log_debug(project_root, "[apply] diff guard detected no changes")
            result["status"] = "no-diff"
            result["apply_status"] = "no-diff"
            result["notes"].append("No diff detected after apply.")
            record_usage(
                project_root,
                args.call_name,
                adapter,
                model,
                args.step,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                adapter_exit_code,
                result["status"],
                usage_captured,
            )
            emit_plain(result)
            return 0

    result["status"] = "ok"
    result["apply_status"] = "applied"
    record_usage(
        project_root,
        args.call_name,
        adapter,
        model,
        args.step,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        adapter_exit_code,
        result["status"],
        usage_captured,
    )
    emit_plain(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
