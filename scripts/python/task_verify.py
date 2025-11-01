#!/usr/bin/env python3
"""Generic verification adapters for gpt-creator tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class CheckResult:
    name: str
    status: str  # pass | fail | skip
    message: str
    kind: str


def load_config(project_root: Path, override: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    candidates: List[Path] = []
    if override:
        override_path = Path(override)
        if not override_path.is_absolute():
            override_path = project_root / override_path
        candidates.append(override_path)
    candidates.extend(
        [
            project_root / ".gpt-creator" / "verify" / "adapters.json",
            project_root / "verify" / "adapters.json",
            project_root / "config" / "verify" / "adapters.json",
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    return json.load(fh), candidate
            except Exception:
                return None, candidate
    return None, None


def run_presence_adapter(project_root: Path, payload: Dict[str, Any]) -> CheckResult:
    rel_path = payload.get("path")
    name = payload.get("name") or f"presence:{rel_path}"
    if not rel_path:
        return CheckResult(name=name, status="skip", message="Missing 'path' for presence adapter.", kind="presence")

    path = (project_root / rel_path).resolve()
    must_exist = payload.get("must_exist", True)
    if must_exist and not path.exists():
        return CheckResult(
            name=name,
            status="fail",
            message=f"Expected path '{rel_path}' to exist.",
            kind="presence",
        )
    if not must_exist and path.exists():
        return CheckResult(
            name=name,
            status="fail",
            message=f"Path '{rel_path}' should be absent but exists.",
            kind="presence",
        )

    pattern = payload.get("pattern")
    if pattern and path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return CheckResult(
                name=name,
                status="fail",
                message=f"Unable to read '{rel_path}': {exc}",
                kind="presence",
            )
        flags = re.IGNORECASE if payload.get("ignore_case", True) else 0
        if not re.search(pattern, text, flags=flags):
            return CheckResult(
                name=name,
                status="fail",
                message=f"Pattern '{pattern}' not found in '{rel_path}'.",
                kind="presence",
            )

    return CheckResult(
        name=name,
        status="pass",
        message=f"Presence check satisfied for '{rel_path}'.",
        kind="presence",
    )


def run_command_adapter(project_root: Path, payload: Dict[str, Any]) -> CheckResult:
    cmd_raw = payload.get("cmd") or payload.get("command")
    name = payload.get("name") or "command"
    allow_missing = bool(payload.get("allow_missing", False))
    shell = bool(payload.get("shell", False))
    cwd = payload.get("cwd")
    cwd_path = (project_root / cwd).resolve() if cwd else project_root

    if not cmd_raw:
        return CheckResult(
            name=name,
            status="skip",
            message="Missing 'cmd' for command adapter.",
            kind="command",
        )

    if isinstance(cmd_raw, str) and not shell:
        cmd = shlex.split(cmd_raw)
    elif isinstance(cmd_raw, str):
        cmd = cmd_raw
    elif isinstance(cmd_raw, Iterable):
        cmd = list(cmd_raw)
    else:
        return CheckResult(
            name=name,
            status="skip",
            message="Invalid command specification.",
            kind="command",
        )

    try:
        if shell and isinstance(cmd, str):
            proc = subprocess.run(cmd, cwd=str(cwd_path), shell=True, capture_output=True, text=True)
        else:
            proc = subprocess.run(cmd, cwd=str(cwd_path), shell=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        if allow_missing:
            return CheckResult(
                name=name,
                status="skip",
                message=f"Command missing ({exc}); skipping.",
                kind="command",
            )
        return CheckResult(
            name=name,
            status="fail",
            message=f"Command not found: {exc}",
            kind="command",
        )
    except Exception as exc:
        return CheckResult(
            name=name,
            status="fail",
            message=f"Failed to execute command: {exc}",
            kind="command",
        )

    if proc.returncode != 0:
        return CheckResult(
            name=name,
            status="fail",
            message=f"Command exited {proc.returncode}",
            kind="command",
        )

    return CheckResult(
        name=name,
        status="pass",
        message="Command succeeded.",
        kind="command",
    )


def run_graph_adapter(project_root: Path, payload: Dict[str, Any]) -> CheckResult:
    # Graph adapters piggy-back on presence checks to keep implementation generic.
    payload = dict(payload)
    payload.setdefault("must_exist", True)
    if "name" not in payload:
        payload["name"] = payload.get("label") or f"graph:{payload.get('path', 'unknown')}"
    return run_presence_adapter(project_root, payload)


ADAPTER_DISPATCH = {
    "presence": run_presence_adapter,
    "pattern": run_presence_adapter,
    "artifact": run_presence_adapter,
    "graph": run_graph_adapter,
    "command": run_command_adapter,
}


def evaluate_adapters(project_root: Path, config: Dict[str, Any]) -> List[CheckResult]:
    adapters = config.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        return [
            CheckResult(
                name="verification",
                status="skip",
                message="No adapters configured.",
                kind="meta",
            )
        ]

    results: List[CheckResult] = []
    for entry in adapters:
        if not isinstance(entry, dict):
            results.append(
                CheckResult(
                    name="unknown",
                    status="skip",
                    message="Adapter entry must be an object.",
                    kind="meta",
                )
            )
            continue
        adapter_type = str(entry.get("type") or "presence").lower()
        handler = ADAPTER_DISPATCH.get(adapter_type)
        if handler is None:
            results.append(
                CheckResult(
                    name=entry.get("name") or adapter_type,
                    status="skip",
                    message=f"Unsupported adapter type '{adapter_type}'.",
                    kind=adapter_type,
                )
            )
            continue
        results.append(handler(project_root, entry))
    return results


def aggregate_status(results: List[CheckResult]) -> str:
    if any(r.status == "fail" for r in results):
        return "fail"
    if any(r.status == "pass" for r in results):
        return "pass"
    return "inconclusive"


def build_summary(results: List[CheckResult]) -> str:
    counts = {"pass": 0, "fail": 0, "skip": 0}
    for res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
    segments = [f"{counts['pass']} pass", f"{counts['fail']} fail", f"{counts['skip']} skip"]
    return ", ".join(segments)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run generic task verification adapters.")
    parser.add_argument("--project", default=os.getcwd(), help="Project root directory.")
    parser.add_argument("--config", help="Explicit adapters config path.")
    parser.add_argument("--task-ref", help="Task reference string (for logging).")
    parser.add_argument("--output", help="Write verification report to this file.")
    args = parser.parse_args(argv)

    project_root = Path(args.project).resolve()
    config, config_path = load_config(project_root, args.config)

    result_payload: Dict[str, Any] = {
        "status": "inconclusive",
        "summary": "No verification adapters configured.",
        "details": [],
        "config_path": str(config_path) if config_path else None,
        "task_ref": args.task_ref,
    }

    if config is None:
        if config_path and not config_path.exists():
            result_payload["summary"] = f"Verification config not found at {config_path}"
        elif config_path:
            result_payload["summary"] = f"Failed to parse verification config at {config_path}"
        output = json.dumps(result_payload, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        print(output)
        return 0

    results = evaluate_adapters(project_root, config)
    overall = aggregate_status(results)
    result_payload["status"] = overall
    result_payload["details"] = [
        {"name": r.name, "status": r.status, "message": r.message, "kind": r.kind} for r in results
    ]
    result_payload["summary"] = build_summary(results)

    output = json.dumps(result_payload, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
