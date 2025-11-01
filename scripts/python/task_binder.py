#!/usr/bin/env python3
"""Task binder cache utilities for work-on-tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
VERSION = 1

_DIGEST_MAX_BYTES = max(1024, int(os.getenv("GC_BINDER_DIGEST_MAX_BYTES", "8192")))
_DIGEST_MAX_LINES = max(16, int(os.getenv("GC_BINDER_DIGEST_MAX_LINES", "120")))
_AUTO_SNAPSHOT_RE = re.compile(r"^chore\(gpt-creator\):\s*auto snapshot", re.IGNORECASE)


def _sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def _make_text_digest(text: str) -> Dict[str, Any]:
    material = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    encoded = material.encode("utf-8", "ignore")
    preview_lines = material.splitlines()
    clipped_lines = preview_lines[:_DIGEST_MAX_LINES]
    preview = "\n".join(clipped_lines)
    preview_bytes = preview.encode("utf-8", "ignore")
    if len(preview_bytes) > _DIGEST_MAX_BYTES:
        preview = preview_bytes[:_DIGEST_MAX_BYTES].decode("utf-8", "ignore")
    return {
        "sha256": _sha256_bytes(encoded),
        "bytes": len(encoded),
        "preview": preview,
        "preview_lines": min(len(preview_lines), _DIGEST_MAX_LINES),
        "truncated": len(encoded) > len(preview.encode("utf-8", "ignore")),
    }


def _slugify(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return "unknown"
    slug = []
    for char in text:
        if char.isalnum():
            slug.append(char)
        elif slug and slug[-1] != "-":
            slug.append("-")
    if not slug:
        return "unknown"
    result = "".join(slug).strip("-")
    return result or "unknown"


def _binder_root(project_root: Path) -> Path:
    return project_root / ".gpt-creator" / "cache" / "task-binder"


def _binder_path(project_root: Path, epic_slug: str, story_slug: str, task_id: str) -> Path:
    root = _binder_root(project_root)
    return root / _slugify(epic_slug) / _slugify(story_slug) / f"{_slugify(task_id)}.json"


def _current_git_head(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_changed_paths(project_root: Path, base_commit: str) -> List[str]:
    if not base_commit:
        return []
    head = _current_git_head(project_root)
    if not head or head == base_commit:
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--name-only", f"{base_commit}..{head}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _commits_are_auto_snapshot(project_root: Path, base_commit: str, head_commit: str) -> bool:
    if not base_commit or not head_commit or base_commit == head_commit:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "log", "--format=%s", f"{base_commit}..{head_commit}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    subjects = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not subjects:
        return False
    return all(_AUTO_SNAPSHOT_RE.match(subject) for subject in subjects)


def _collect_cache_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for item in root.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _trim_cache(root: Path, max_bytes: int) -> None:
    if not root.exists() or max_bytes <= 0:
        return
    files: List[Tuple[float, Path]] = []
    for item in root.rglob("*.json"):
        try:
            files.append((item.stat().st_mtime, item))
        except OSError:
            continue
    files.sort()
    total = _collect_cache_size(root)
    if total <= max_bytes:
        return
    for _, path in files:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        if total <= max_bytes:
            break


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class BinderLoadResult:
    status: str
    path: Path
    binder: Dict[str, Any]
    reason: str


def _ensure_hit_counters(binder: Dict[str, Any]) -> None:
    meta = binder.setdefault("meta", {})
    stats = meta.setdefault("stats", {})
    for key in ("hit_count", "miss_count", "stale_count"):
        stats.setdefault(key, 0)


def export_prior_task_context(binding: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(binding, dict):
        return {}
    digest = binding.get("prompt_digest")
    if not isinstance(digest, dict) or not digest.get("sha256"):
        legacy = binding.get("prompt_text") or binding.get("context") or ""
        if legacy:
            digest = _make_text_digest(str(legacy))
        else:
            digest = None
    result: Dict[str, Any] = {}
    if isinstance(digest, dict) and digest.get("preview"):
        result["prior_task_digest"] = {
            "sha256": digest.get("sha256"),
            "bytes": digest.get("bytes"),
            "preview": digest.get("preview"),
            "preview_lines": digest.get("preview_lines"),
            "truncated": bool(digest.get("truncated")),
        }
    decisions = binding.get("decisions")
    if isinstance(decisions, (list, dict)):
        result["decisions"] = decisions
    return result


def load_for_prompt(
    project_root: Path,
    *,
    epic_slug: str,
    story_slug: str,
    task_id: str,
    ttl_seconds: int,
    max_bytes: int,
) -> BinderLoadResult:
    if not task_id:
        return BinderLoadResult("missing", Path(), {}, "task-id-missing")

    path = _binder_path(project_root, epic_slug, story_slug, task_id)
    if not path.exists():
        return BinderLoadResult("missing", path, {}, "no-file")

    binder = _read_json(path)
    if not binder:
        return BinderLoadResult("stale", path, {}, "invalid-json")

    meta = binder.get("meta") or {}
    updated_at = meta.get("updated_at")
    try:
        updated_ts = float(updated_at)
    except (TypeError, ValueError):
        updated_ts = 0.0
    now_ts = time.time()
    if ttl_seconds > 0 and (now_ts - updated_ts) > ttl_seconds:
        return BinderLoadResult("stale", path, binder, "ttl-expired")

    binder_git = (binder.get("git") or {}).get("head") or ""
    current_git = _current_git_head(project_root)
    if binder_git and current_git and binder_git != current_git:
        auto_snapshot_only = _commits_are_auto_snapshot(project_root, binder_git, current_git)
        changed_paths = [] if auto_snapshot_only else _git_changed_paths(project_root, binder_git)
        if not auto_snapshot_only:
            files_section = binder.get("files") or {}
            allowed = set()
            for key in ("primary", "related", "deps"):
                for item in files_section.get(key) or []:
                    allowed.add((item or "").strip())
            invalidated = False
            for path_changed in changed_paths:
                if not path_changed:
                    continue
                if path_changed not in allowed:
                    invalidated = True
                    break
            if invalidated:
                return BinderLoadResult("stale", path, binder, "git-diverged")

    cache_root = _binder_root(project_root)
    if max_bytes > 0 and _collect_cache_size(cache_root) > max_bytes:
        _trim_cache(cache_root, max_bytes)

    _ensure_hit_counters(binder)
    return BinderLoadResult("hit", path, binder, "ok")


def prepare_binder_payload(
    *,
    project_root: Path,
    epic_slug: str,
    story_slug: str,
    task_id: str,
    task_title: str,
    problem: str,
    invariants: Sequence[str],
    acceptance: Sequence[str],
    doc_refs: Sequence[Dict[str, Any]],
    git_head: str,
    files_section: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    last_tokens: Optional[Dict[str, Any]] = None,
    previous: Optional[Dict[str, Any]] = None,
    binder_status: str = "miss",
    prompt_snapshot: Optional[str] = None,
) -> Tuple[Path, Dict[str, Any]]:
    path = _binder_path(project_root, epic_slug, story_slug, task_id)
    now_ts = time.time()
    binder: Dict[str, Any] = previous.copy() if isinstance(previous, dict) else {}
    binder["version"] = VERSION
    binder["story_slug"] = story_slug
    binder["task_id"] = task_id
    binder["task_title"] = task_title
    binder["problem"] = problem.strip() if problem else ""
    binder["invariants"] = [item for item in (invariants or []) if item]
    binder["acceptance"] = [item for item in (acceptance or []) if item]
    binder["doc_refs"] = list(doc_refs or [])
    binder["git"] = {"head": git_head}
    binder["files"] = files_section or binder.get("files") or {"primary": [], "related": [], "deps": []}
    binder["evidence"] = evidence or binder.get("evidence") or {}
    binder["last_tokens"] = last_tokens or binder.get("last_tokens") or {}
    binder.pop("prompt_text", None)
    binder.pop("context", None)
    binder.pop("prior_prompt_text", None)
    binder.pop("prompt_snapshot", None)
    if prompt_snapshot:
        binder["prompt_digest"] = _make_text_digest(prompt_snapshot)
    elif isinstance(previous, dict) and isinstance(previous.get("prompt_digest"), dict):
        binder["prompt_digest"] = dict(previous["prompt_digest"])
    else:
        binder.pop("prompt_digest", None)
    binder_meta = binder.setdefault("meta", {})
    binder_meta["updated_at"] = str(now_ts)
    binder_meta["status"] = binder_status
    binder_meta["story_slug"] = story_slug
    binder_meta["epic_slug"] = epic_slug
    binder_meta["task_id"] = task_id
    _ensure_hit_counters(binder)
    stats = binder_meta["stats"]
    if binder_status == "hit":
        stats["hit_count"] = int(stats.get("hit_count") or 0) + 1
    elif binder_status == "stale":
        stats["stale_count"] = int(stats.get("stale_count") or 0) + 1
    else:
        stats["miss_count"] = int(stats.get("miss_count") or 0) + 1
    return path, binder


def write_binder(path: Path, binder: Dict[str, Any], *, max_bytes: int) -> None:
    _write_json(path, binder)
    if max_bytes > 0:
        _trim_cache(path.parents[2], max_bytes)


def update_after_progress(
    project_root: Path,
    *,
    epic_slug: str,
    story_slug: str,
    task_id: str,
    status: str,
    apply_status: Optional[str],
    notes: Sequence[str],
    written_paths: Sequence[str],
    patched_paths: Sequence[str],
    tokens_total: Optional[int],
    run_stamp: str,
    reopened_by_migration: bool = False,
    log_path: Optional[str] = None,
    prompt_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> None:
    if not task_id:
        return
    path = _binder_path(project_root, epic_slug, story_slug, task_id)
    if not path.exists():
        return
    binder = _read_json(path)
    if not binder:
        return
    files_section = binder.setdefault("files", {"primary": [], "related": [], "deps": []})
    primary = set(files_section.get("primary") or [])
    related = set(files_section.get("related") or [])
    for item in written_paths:
        if not item:
            continue
        primary.add(item)
    for item in patched_paths:
        if not item:
            continue
        related.add(item)
    files_section["primary"] = sorted(primary)
    files_section["related"] = sorted(related)

    evidence = binder.setdefault("evidence", {})
    existing_notes = evidence.get("notes") or []
    merged_notes = list(existing_notes)
    for note in notes:
        if note and note not in merged_notes:
            merged_notes.append(note)
    if merged_notes:
        evidence["notes"] = merged_notes[:16]
    if log_path:
        evidence["last_log_path"] = log_path
    if prompt_path:
        evidence["last_prompt_path"] = prompt_path
    if output_path:
        evidence["last_output_path"] = output_path

    binder["last_status"] = status
    binder["last_run_stamp"] = run_stamp
    tokens_map = binder.setdefault("last_tokens", {})
    if tokens_total is not None:
        tokens_map["patch"] = int(tokens_total)
    meta = binder.setdefault("meta", {})
    if reopened_by_migration:
        meta["reopened_by_migration"] = True
    if apply_status:
        meta["last_apply_status"] = apply_status
    _write_json(path, binder)


def clear_story(project_root: Path, epic_slug: str, story_slug: str) -> None:
    path = _binder_root(project_root) / _slugify(epic_slug) / _slugify(story_slug)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Task binder utility.")
    sub = parser.add_subparsers(dest="mode", required=True)

    clear_cmd = sub.add_parser("clear", help="Clear binder entries for a story or task.")
    clear_cmd.add_argument("--project", required=True, type=Path)
    clear_cmd.add_argument("--epic", required=True)
    clear_cmd.add_argument("--story", required=True)
    clear_cmd.add_argument("--task", help="Optional task id to clear a single binder.")

    update_cmd = sub.add_parser("update", help="Update binder after progress.")
    update_cmd.add_argument("--project", required=True, type=Path)
    update_cmd.add_argument("--epic", required=True)
    update_cmd.add_argument("--story", required=True)
    update_cmd.add_argument("--task", required=True)
    update_cmd.add_argument("--status", required=True)
    update_cmd.add_argument("--apply-status", default="")
    update_cmd.add_argument("--notes", default="")
    update_cmd.add_argument("--written", default="")
    update_cmd.add_argument("--patched", default="")
    update_cmd.add_argument("--tokens", default="")
    update_cmd.add_argument("--run-stamp", default="")
    update_cmd.add_argument("--reopened", action="store_true")
    update_cmd.add_argument("--log", default="")
    update_cmd.add_argument("--prompt", default="")
    update_cmd.add_argument("--output", default="")

    return parser.parse_args(argv)


def _split_list(value: str) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.splitlines() if item.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.mode == "clear":
        if args.task:
            path = _binder_path(args.project, args.epic, args.story, args.task)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            clear_story(args.project, args.epic, args.story)
        return 0

    if args.mode == "update":
        tokens = None
        if args.tokens:
            try:
                tokens = int(float(args.tokens))
            except (TypeError, ValueError):
                tokens = None
        update_after_progress(
            args.project,
            epic_slug=args.epic,
            story_slug=args.story,
            task_id=args.task,
            status=args.status,
            apply_status=args.apply_status or None,
            notes=_split_list(args.notes),
            written_paths=_split_list(args.written),
            patched_paths=_split_list(args.patched),
            tokens_total=tokens,
            run_stamp=args.run_stamp or "",
            reopened_by_migration=bool(args.reopened),
            log_path=args.log or None,
            prompt_path=args.prompt or None,
            output_path=args.output or None,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
