#!/usr/bin/env python3
"""
Helper utilities for interacting with the docdexd search/index daemon.

This module provides a thin wrapper used by gpt-creator to ensure the
Rust-based docdex daemon is running, trigger incremental ingests, and
query for documentation hits/snippets.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_PORT = int(os.environ.get("GC_DOCDEX_PORT", "46137"))
DEFAULT_HOST = os.environ.get("GC_DOCDEX_HOST", "127.0.0.1")
CLI_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = Path(".gpt-creator/run")
LOG_DIR = Path(".gpt-creator/logs")
PID_FILE = RUN_DIR / "docdexd.pid"
LOG_FILE = LOG_DIR / "docdexd.log"
HTTP_RETRY_ATTEMPTS = 4
HTTP_RETRY_BASE_DELAY = 0.35


class DocDexError(RuntimeError):
    """Base exception for docdex client errors."""


def _log(message: str) -> None:
    print(f"[docdex_client] {message}", file=sys.stderr)


def _resolve_repo_root(repo_root: Optional[Path] = None) -> Path:
    if repo_root:
        return repo_root
    return Path(os.environ.get("GC_PROJECT_ROOT", os.getcwd())).resolve()


def _format_target(host: str, port: int, repo: Optional[Path] = None) -> str:
    repo_part = f", repo={repo}" if repo else ""
    return f"host={host}, port={port}{repo_part}"


def _binary_path(repo_root: Path) -> Path:
    candidates: list[Path] = []
    env_bin = os.environ.get("GC_DOCDEX_BIN")
    if env_bin:
        path = Path(env_bin).expanduser()
        candidates.append(path)
    cli_candidate = CLI_ROOT / ".gpt-creator/bin/docdexd"
    repo_candidate = repo_root / ".gpt-creator/bin/docdexd"
    candidates.extend([cli_candidate, repo_candidate])
    for candidate in candidates:
        if candidate.exists():
            _log(f"using docdexd binary at {candidate}")
            return candidate
    search_list = ", ".join(str(p) for p in candidates)
    raise DocDexError(
        "docdexd binary not found. "
        f"Expected at: {search_list}. Run `gpt-creator docdex build` "
        "or set GC_DOCDEX_BIN to a valid docdexd binary."
    )


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.connect((host, port))
            _log(f"port {host}:{port} already open")
            return True
        except OSError:
            return False


def _wait_for_health(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://{host}:{port}/healthz"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1) as resp:
                data = resp.read()
                if resp.status == 200 and b"ok" in data.lower():
                    return True
        except URLError:
            pass
        time.sleep(0.2)
    return False


def _read_pid() -> Optional[int]:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _write_pid(pid: int) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _start_daemon(repo_root: Path, host: str, port: int) -> None:
    binary = _binary_path(repo_root)
    _log(f"starting docdexd via {binary} for repo {repo_root}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "ab")
    cmd = [
        str(binary),
        "serve",
        "--repo",
        str(repo_root),
        "--host",
        host,
        "--port",
        str(port),
        "--log",
        os.environ.get("GC_DOCDEX_LOG", "info"),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=str(repo_root),
    )
    _write_pid(proc.pid)
    _log(f"launched docdexd pid={proc.pid} host={host} port={port}")
    if not _wait_for_health(host, port):
        raise DocDexError(
            f"docdexd failed to start for repo '{repo_root}' on {host}:{port}; "
            f"check logs at {LOG_FILE}"
        )


def ensure_daemon(
    repo_root: Optional[Path] = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Start the docdex daemon if it is not already running."""
    repo = _resolve_repo_root(repo_root)
    if _port_open(host, port):
        _log(f"docdexd already responding on {host}:{port}")
        return
    _log(f"docdexd unavailable on {host}:{port}; attempting to start")
    _start_daemon(repo, host, port)


def _http_get(
    path: str,
    *,
    host: str,
    port: int,
    repo: Optional[Path] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    url = f"http://{host}:{port}{path}{query}"
    req = Request(url, headers={"Accept": "application/json"})
    last_error: Optional[Exception] = None
    for attempt in range(HTTP_RETRY_ATTEMPTS):
        try:
            with urlopen(req, timeout=10) as resp:
                data = resp.read()
                return json.loads(data.decode("utf-8"))
        except URLError as exc:
            last_error = exc
            delay = HTTP_RETRY_BASE_DELAY * (2 ** attempt)
            time.sleep(min(delay, 2.5))
    target = _format_target(host, port, repo)
    raise DocDexError(
        f"docdexd request to {path} failed after {HTTP_RETRY_ATTEMPTS} attempts "
        f"({target}): {last_error}"
    ) from last_error


def _run_cli(args: Iterable[str], repo_root: Path) -> None:
    binary = _binary_path(repo_root)
    cmd = [str(binary), *args]
    proc = subprocess.run(cmd, cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        context = f"(repo={repo_root})"
        raise DocDexError(
            proc.stderr.strip()
            or proc.stdout.strip()
            or f"docdexd exited {proc.returncode} {context}"
        )


def ingest_file(path: Path, repo_root: Optional[Path] = None) -> None:
    """Trigger an incremental ingest for a single document."""
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
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> Dict[str, Any]:
    repo = _resolve_repo_root(repo_root)
    _log(f"search_docs(query='{query[:40]}', limit={limit}, repo={repo})")
    ensure_daemon(repo, host=host, port=port)
    payload = _http_get(
        "/search",
        host=host,
        port=port,
        repo=repo,
        params={"q": query, "limit": limit},
    )
    return payload


def fetch_snippet(
    doc_id: str,
    *,
    query: Optional[str] = None,
    window: int = 60,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo = _resolve_repo_root(repo_root)
    ensure_daemon(repo, host=host, port=port)
    params: Dict[str, Any] = {"window": window}
    if query and query.strip():
        params["q"] = query
    return _http_get(
        f"/snippet/{doc_id}",
        host=host,
        port=port,
        repo=repo,
        params=params,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Interact with docdexd daemon.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="command", required=True)

    ensure_cmd = sub.add_parser("ensure", help="Ensure the docdex daemon is running.")
    ensure_cmd.set_defaults(func="ensure")

    search_cmd = sub.add_parser("search", help="Run a search query.")
    search_cmd.add_argument("--query", "-q", required=True)
    search_cmd.add_argument("--limit", type=int, default=8)
    search_cmd.set_defaults(func="search")

    ingest_cmd = sub.add_parser("ingest", help="Ingest one or more files.")
    ingest_cmd.add_argument("paths", nargs="+")
    ingest_cmd.set_defaults(func="ingest")

    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    if args.func == "ensure":
        ensure_daemon(repo, host=args.host, port=args.port)
        print(f"docdexd ready on {args.host}:{args.port}")
    elif args.func == "search":
        result = search_docs(args.query, limit=args.limit, repo_root=repo, host=args.host, port=args.port)
        json.dump(result, sys.stdout, indent=2)
        print()
    elif args.func == "ingest":
        ingest_many([Path(p) for p in args.paths], repo_root=repo)
        print(f"Ingested {len(args.paths)} file(s).")
