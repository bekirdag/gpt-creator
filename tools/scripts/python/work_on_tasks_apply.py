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
from pathlib import Path
from typing import Dict, List, Optional


def run_codex(call_name: str, step: str, prompt_path: Path, output_path: Path) -> subprocess.CompletedProcess:
    cmd = [
        "bash",
        "-lc",
        (
            f"codex exec --model \"${{CODEX_MODEL:-{os.getenv('CODEX_MODEL','gpt-5.1-codex')}}}\" "
            f"--step '{step}' < '{prompt_path}' > '{output_path}'"
        ),
    ]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def apply_patch(output_path: Path, project_root: Path, patch_artifact_path: Path) -> subprocess.CompletedProcess:
    cmd = [
        "bash",
        "-lc",
        f"BASH={os.getenv('BASH','bash')} GC_APPLY_PATCH_PROJECT_ROOT='{project_root}' '{os.getenv('CLI_ROOT','.')}/scripts/auto_apply_patch.sh' '{output_path}' '{patch_artifact_path}'",
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
    proc = run_codex(args.call_name, args.step, prompt_path, output_path)
    if proc.returncode != 0:
        result["status"] = "codex-failed"
        result["notes"].append(f"Codex failed: {proc.stderr.strip()}")
        emit_plain(result)
        return 0

    # Token accounting from environment if available
    prompt_tokens = int(os.getenv("GC_LAST_CODEX_PROMPT_TOKENS", "0") or 0)
    completion_tokens = int(os.getenv("GC_LAST_CODEX_COMPLETION_TOKENS", "0") or 0)
    total_tokens = int(os.getenv("GC_CODEX_CALL_TOKEN_ACCUM", os.getenv("GC_LAST_CODEX_TOTAL_TOKENS", "0")) or 0)
    result["tokens"] = {"prompt": prompt_tokens, "completion": completion_tokens, "total": total_tokens}

    if not output_path.exists() or output_path.stat().st_size == 0:
        result["status"] = "empty-output"
        result["apply_status"] = "no-output"
        result["notes"].append("Codex produced no output.")
        emit_plain(result)
        return 0

    apply_proc = apply_patch(output_path, project_root, patch_artifact_path)
    if apply_proc.returncode != 0:
        result["status"] = "apply-failed"
        result["apply_status"] = "apply-failed"
        result["notes"].append(apply_proc.stderr.strip() or apply_proc.stdout.strip())
        emit_plain(result)
        return 0

    apply_output = apply_proc.stdout.strip()
    if apply_output in {"no-output", "empty-output"}:
        result["status"] = "empty-apply"
        result["apply_status"] = apply_output
        result["notes"].append("Patch apply returned no actionable changes.")
        emit_plain(result)
        return 0

    if args.diff_guard:
        diff_after = fingerprint_diff()
        if diff_before and diff_after and diff_before == diff_after:
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
