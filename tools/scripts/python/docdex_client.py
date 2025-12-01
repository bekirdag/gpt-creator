#!/usr/bin/env python3
"""
Docdex CLI helper (npm distribution).

This client shells out to the npm-provided `docdexd` binary (alias: `docdex`)
for indexing, querying, and ingesting docs. No bundled Rust binary or local
daemon management is needed; the CLI fetches the right platform build during
`npm i -g docdex`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class DocDexError(RuntimeError):
    """Base exception for docdex client errors."""


def _log(message: str) -> None:
    try:
        print(f"[docdex_client] {message}", file=sys.stderr)
    except Exception:
        # Logging must never interfere with callers consuming stdout.
        pass


def _resolve_repo_root(repo_root: Optional[Path] = None) -> Path:
    if repo_root:
        return repo_root
    return Path(os.environ.get("GC_PROJECT_ROOT", os.getcwd())).resolve()


def _docdex_cmd() -> str:
    env_cmd = os.environ.get("DOCDEX_BIN") or os.environ.get("GC_DOCDEX_BIN")
    if env_cmd:
        return env_cmd
    for candidate in ("docdexd", "docdex"):
        if shutil.which(candidate):
            return candidate
    raise DocDexError("docdex CLI not found in PATH; install via `npm i -g docdex`.")


def _default_state_dir(repo_root: Path) -> Path:
    """Fallback state dir under the gpt-creator installation for sandboxed environments."""
    env_dir = os.environ.get("DOCDEX_STATE_DIR") or os.environ.get("GC_DOCDEX_STATE_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    base = Path(__file__).resolve().parents[2] / ".docdex"
    repo_hash = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:12]
    return base / repo_hash


def _run_cli_json(args: Iterable[str], repo_root: Path) -> Dict[str, Any]:
    cmd = [_docdex_cmd(), *args]
    env = os.environ.copy()
    # Default state dir under the CLI root (writable even when repo is sandboxed)
    state_dir = _default_state_dir(repo_root)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    env.setdefault("DOCDEX_STATE_DIR", str(state_dir))
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise DocDexError(f"docdex CLI failed ({proc.returncode}): {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise DocDexError(f"docdex CLI returned invalid JSON: {exc}") from exc


def _run_cli(args: Iterable[str], repo_root: Path) -> None:
    cmd = [_docdex_cmd(), *args]
    env = os.environ.copy()
    state_dir = _default_state_dir(repo_root)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    env.setdefault("DOCDEX_STATE_DIR", str(state_dir))
    _log(f"running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(repo_root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise DocDexError(f"docdex CLI failed ({proc.returncode}): {proc.stderr.strip()}")


def ensure_daemon(
    repo_root: Optional[Path] = None,
    *,
    host: str = "",
    port: Optional[int] = None,
) -> None:
    """No-op placeholder retained for compatibility."""
    repo_root = _resolve_repo_root(repo_root)
    _log(f"docdex daemon not required; using CLI for repo {repo_root}")


def index_repo(repo_root: Optional[Path] = None) -> None:
    repo = _resolve_repo_root(repo_root)
    _run_cli(["index", "--repo", str(repo)], repo)


def ingest_file(path: Path, repo_root: Optional[Path] = None) -> None:
    repo = _resolve_repo_root(repo_root)
    rel = path if path.is_absolute() else repo / path
    if not rel.exists():
        raise DocDexError(f"Cannot ingest missing file: {rel}")
    _run_cli(["ingest", "--repo", str(repo), "--file", str(rel)], repo)


def ingest_many(paths: Iterable[Path], repo_root: Optional[Path] = None) -> None:
    repo = _resolve_repo_root(repo_root)
    for path in paths:
        ingest_file(path, repo)


def search_docs(
    query: str,
    *,
    limit: int = 8,
    repo_root: Optional[Path] = None,
    host: str = "",
    port: Optional[int] = None,
) -> Dict[str, Any]:
    repo = _resolve_repo_root(repo_root)
    _log(f"search_docs(query='{query[:40]}', limit={limit}, repo={repo})")
    try:
        payload = _run_cli_json(
            ["query", "--repo", str(repo), "--query", query, "--limit", str(limit)],
            repo,
        )
        if "hits" not in payload:
            payload = {"hits": payload.get("hits", [])}
        return payload
    except DocDexError as err:
        msg = str(err)
        if "Lockfile" in msg or "LockBusy" in msg:
            _log("docdex query skipped due to index lock; returning no hits.")
            return {"hits": []}
        raise


def search_docs_cli(
    query: str,
    *,
    limit: int = 8,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    return search_docs(query, limit=limit, repo_root=repo_root)


def fetch_snippet(
    doc_id: str,
    *,
    query: Optional[str] = None,
    window: int = 60,
    host: str = "",
    port: Optional[int] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo = _resolve_repo_root(repo_root)
    try:
        payload = _run_cli_json(
            ["query", "--repo", str(repo), "--query", query or doc_id, "--limit", "12"],
            repo,
        )
    except DocDexError as err:
        msg = str(err)
        if "Lockfile" in msg or "LockBusy" in msg:
            _log("docdex snippet lookup skipped due to index lock; returning empty snippet.")
            return {"doc": None, "snippet": None}
        raise
    hits = payload.get("hits", [])
    for hit in hits:
        if hit.get("doc_id") == doc_id:
            return {"doc": hit, "snippet": hit.get("snippet") or hit.get("summary")}
    return {"doc": None, "snippet": None}
