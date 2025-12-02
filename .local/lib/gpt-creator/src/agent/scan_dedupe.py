#!/usr/bin/env python3
"""Command deduplication helper for scan-like operations.

This module is invoked from the Bash shim injected via BASH_ENV. It provides a
very small cache that skips redundant filesystem scans targeting
`.gpt-creator/{staging,plan,work}` during a single work-on-tasks session. The
cache key combines the task identifier, working directory, normalised command,
and a mutation epoch emitted by the orchestrator whenever files change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore


FALLBACK_EXIT = 199
DEFAULT_TTL = 120.0
MAX_CACHE_ENTRIES = 120
MAX_OUTPUT_CHARS = 64000
STAGING_TOKENS = (".gpt-creator/staging/", ".gpt-creator/plan/", ".gpt-creator/work/")


class Cache:
    """Lightweight JSON cache with advisory locking."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: Dict[str, Dict[str, object]] = {}
        self._load()

    def _lock(self, handle, flags) -> None:
        if fcntl is None:
            return
        try:
            fcntl.flock(handle.fileno(), flags)
        except OSError:
            pass

    def _unlock(self, handle) -> None:
        if fcntl is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def _load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.data = {}
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._lock(handle, fcntl.LOCK_SH if fcntl else 0)
                raw = handle.read()
                self._unlock(handle)
        except Exception:
            self.data = {}
            return
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            self.data = parsed
        else:
            self.data = {}

    def get(self, key: str) -> Dict[str, object] | None:
        entry = self.data.get(key)
        return entry if isinstance(entry, dict) else None

    def set(self, key: str, entry: Dict[str, object]) -> None:
        self.data[key] = entry
        if len(self.data) > MAX_CACHE_ENTRIES:
            ordered = sorted(
                self.data.items(),
                key=lambda item: item[1].get("ts", 0.0),  # type: ignore[arg-type]
                reverse=True,
            )
            self.data = dict(ordered[:MAX_CACHE_ENTRIES])
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        tmp_path = self.path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp_path.replace(self.path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


def normalise_command(cmd: Tuple[str, ...]) -> str:
    return shlex.join(cmd)


def compute_key(task: str, cwd: str, cmd: Tuple[str, ...], epoch: int) -> str:
    digest = hashlib.sha256()
    digest.update((task or "global").encode("utf-8", "ignore"))
    digest.update(b"\0")
    digest.update(cwd.encode("utf-8", "ignore"))
    digest.update(b"\0")
    digest.update(normalise_command(cmd).encode("utf-8", "ignore"))
    digest.update(b"\0")
    digest.update(str(epoch).encode("utf-8", "ignore"))
    return digest.hexdigest()


def run_and_capture(cmd: Tuple[str, ...], cwd: Path) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, f"{cmd[0]}: command not found\n"
    except Exception as exc:  # pragma: no cover - defensive fallback
        return FALLBACK_EXIT, f"[scan-dedup] failed to execute {cmd[0]}: {exc}\n"
    output = completed.stdout or ""
    if not output.endswith("\n"):
        output = output + "\n"
    return completed.returncode, output


def handle_show_file(
    cmd: Tuple[str, ...], cwd: Path
) -> Tuple[int, str, Tuple[str, ...]]:
    has_refresh = any(
        token == "--refresh" or token.startswith("--refresh=") for token in cmd
    )
    if has_refresh:
        code, output = run_and_capture(cmd, cwd)
        return code, output, cmd

    code, output = run_and_capture(cmd, cwd)
    banner = "use --refresh to re-display"
    if code == 0 and banner in output:
        refreshed = cmd + ("--refresh",)
        code, output = run_and_capture(refreshed, cwd)
        return code, output, refreshed
    return code, output, cmd


def should_consider(tokens: Tuple[str, ...]) -> bool:
    for token in tokens:
        lower = token.lower()
        if lower.startswith("--"):
            continue
        for marker in STAGING_TOKENS:
            if marker in lower:
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan dedupe runner")
    parser.add_argument("--mode", required=True, choices=["show-file", "rg", "ls", "find"])
    parser.add_argument("--cache", required=True)
    parser.add_argument("--task", default="global")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--epoch", type=int, default=0)
    parser.add_argument("--ttl", type=float, default=DEFAULT_TTL)
    parser.add_argument("--command-label", default="")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    raw_cmd = tuple(args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd)
    if not raw_cmd:
        return FALLBACK_EXIT

    cwd_path = Path(args.cwd).resolve()
    cache_path = Path(args.cache).resolve()
    ttl = args.ttl if args.ttl > 0 else None

    if ttl is None:
        cache = None
    else:
        try:
            cache = Cache(cache_path)
        except Exception:
            cache = None

    normalized_cwd = str(cwd_path)
    key = compute_key(args.task or "global", normalized_cwd, raw_cmd, int(args.epoch))
    now = time.time()

    if cache is not None:
        entry = cache.get(key)
        if entry:
            try:
                ts = float(entry.get("ts", 0.0))
            except Exception:
                ts = 0.0
            if ts and (now - ts) < ttl:  # type: ignore[arg-type]
                cached_output = str(entry.get("output", ""))
                exit_code = int(entry.get("exit", 0))
                command_label = (
                    args.command_label or str(entry.get("cmd") or normalise_command(raw_cmd))
                )
                print(
                    f"[scan-dedup] skip (unchanged, epoch={args.epoch}, ttl={int(ttl)}s): {command_label}"
                )
                if cached_output:
                    sys.stdout.write(cached_output)
                return exit_code

    if args.mode != "show-file" and not should_consider(raw_cmd):
        code, output = run_and_capture(raw_cmd, cwd_path)
    elif args.mode == "show-file":
        code, output, raw_cmd = handle_show_file(raw_cmd, cwd_path)
    else:
        code, output = run_and_capture(raw_cmd, cwd_path)

    if code == FALLBACK_EXIT:
        return FALLBACK_EXIT

    sys.stdout.write(output)

    if cache is not None:
        limited_output = output[:MAX_OUTPUT_CHARS]
    else:
        limited_output = output

    if cache is not None:
        cache.set(
            key,
            {
                "ts": now,
                "exit": code,
                "output": limited_output,
                "line_count": limited_output.count("\n"),
                "cmd": normalise_command(raw_cmd),
                "cwd": normalized_cwd,
            },
        )

    return code


if __name__ == "__main__":
    sys.exit(main())
