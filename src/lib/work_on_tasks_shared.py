#!/usr/bin/env python3
"""Runtime helpers extracted from bin/gpt-creator."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, Tuple, Optional, List, Set
import importlib
try:  # pragma: no cover - POSIX-only helper
    import pwd  # type: ignore
except ImportError:  # pragma: no cover - Windows fallback
    pwd = None  # type: ignore

docdex_client = None  # type: ignore
_docdex_logged_success = False

LAST_PENDING_CHANGES: Dict[str, Tuple[str, ...]] = {}

DEPENDENCY_DIR_BASENAMES = {
    "node_modules",
    "vendor",
    "deps",
    "packages",
    "site-packages",
    "venv",
    ".venv",
    "env",
    "envs",
    "virtualenv",
    "dist",
    "build",
    "target",
    "pods",
    "third_party",
    "buck-out",
    "bazel-out",
    "cmake-build-debug",
    "cmake-build-release",
    "deriveddata",
    ".gradle",
    ".m2",
    ".cargo",
    ".dart_tool",
    "gopath",
    "pkgcache",
    "pkg-cache",
    ".nuget",
}

DEPENDENCY_CLONE_SUFFIXES = (
    ".orig",
    ".backup",
    ".bak",
    ".copy",
    ".tmp",
    ".temp",
    ".old",
    ".hold",
    "-orig",
    "-backup",
    "-bak",
    "-copy",
    "-tmp",
    "-temp",
    "-old",
    "-hold",
    "_orig",
    "_backup",
    "_bak",
    "_copy",
    "_tmp",
    "_temp",
    "_old",
    "_hold",
)

DEPENDENCY_CLONE_PREFIXES = (
    "copy_of_",
    "copy-of-",
    "copy_",
    "copy-",
    "backup_",
    "backup-",
    "tmp_",
    "tmp-",
    "temp_",
    "temp-",
    "old_",
    "old-",
    "zzz_",
    "zzz-",
    "save_",
    "save-",
    "snapshot_",
    "snapshot-",
)


def _has_action_token(text: str) -> bool:
    lowered = text.lower()
    if any(token in lowered for token in ('action:', 'result:', 'command', 'next:', 'plan:', 'test:')):
        return True
    stripped = text.strip()
    stripped_lower = stripped.lower()
    if re.match(r'^(plan|focus|commands|notes)\b', stripped_lower):
        return True
    if not stripped:
        return False
    if stripped[0] in {'-', '*', '•'}:
        return True
    if stripped[:1].isdigit():
        suffix = stripped[1:2]
        if suffix in {'.', ')', ':'} or (suffix == ' ' and len(stripped) > 2):
            return True
    if ' -> ' in stripped:
        return True
    return False


def _autoformat_note_entry(text: str) -> Tuple[str, bool]:
    """Coerce narration into Action/Result format so guards are satisfied."""
    stripped = text.strip()
    if not stripped:
        return text, False
    if _has_action_token(stripped):
        return text, False
    normalized = re.sub(r"\s+", " ", stripped)
    preview = normalized[:80].strip()
    preview = preview.rstrip(".,;:·•-") or "note"
    words = [w for w in re.split(r"[^a-z0-9]+", preview.lower()) if w]
    slug = "-".join(words[:3]) if words else "note"
    action_label = f"auto-note:{slug}" if slug else "auto-note"
    formatted = f"Action: {action_label} | Result: {stripped}"
    return formatted, True


def _owner_name_for_uid(uid: int) -> str:
    if pwd is None:  # pragma: no cover - Windows fallback
        return f"uid {uid}"
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:  # pragma: no cover - best effort
        return f"uid {uid}"


def _friendly_relpath(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _normalize_dependency_dir_name(entry_name: str) -> Tuple[Optional[str], bool]:
    lowered = entry_name.strip().lower()
    if not lowered:
        return None, False
    candidate = lowered
    clone_detected = False
    changed = True
    while changed:
        changed = False
        for suffix in DEPENDENCY_CLONE_SUFFIXES:
            if candidate.endswith(suffix) and len(candidate) > len(suffix):
                candidate = candidate[: -len(suffix)]
                clone_detected = True
                changed = True
                break
        if changed:
            continue
        for prefix in DEPENDENCY_CLONE_PREFIXES:
            if candidate.startswith(prefix) and len(candidate) > len(prefix):
                candidate = candidate[len(prefix):]
                clone_detected = True
                changed = True
                break
    trimmed = candidate.strip("_-.")
    if trimmed in DEPENDENCY_DIR_BASENAMES:
        return trimmed, clone_detected
    return None, False


def _scan_dependency_directories(project_root: Path, *, max_depth: int = 5) -> Tuple[List[Path], List[Tuple[Path, str]]]:
    suspicious_clones: List[Path] = []
    ownership_issues: List[Tuple[Path, str]] = []
    if not project_root.exists():
        return suspicious_clones, ownership_issues
    if not hasattr(os, "getuid"):
        return suspicious_clones, ownership_issues
    current_uid = os.getuid()
    visited: Set[Path] = set()
    stack: List[Tuple[Path, int]] = [(project_root, 0)]
    skip_names = {".git", ".hg", ".svn", ".gpt-creator"}
    while stack:
        base, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            if name in skip_names:
                continue
            try:
                resolved = entry.resolve()
            except OSError:
                resolved = entry
            if resolved in visited:
                continue
            visited.add(resolved)
            normalized_name, clone_detected = _normalize_dependency_dir_name(name)
            if normalized_name:
                try:
                    stat_result = entry.stat()
                except OSError:
                    stat_result = None
                if clone_detected:
                    suspicious_clones.append(entry)
                if stat_result is not None and stat_result.st_uid != current_uid:
                    owner_label = _owner_name_for_uid(stat_result.st_uid)
                    ownership_issues.append((entry, owner_label))
                continue
            if depth + 1 <= max_depth:
                stack.append((entry, depth + 1))
    return suspicious_clones, ownership_issues

_HELPER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "python"
if _HELPER_DIR.exists():
    helper_str = str(_HELPER_DIR)
    if helper_str not in sys.path:
        sys.path.insert(0, helper_str)

_EXTRA_HELPER_DIR = os.getenv("GC_PY_HELPERS_DIR", "")
if _EXTRA_HELPER_DIR:
    try:
        extra_path = Path(_EXTRA_HELPER_DIR).resolve()
        extra_str = str(extra_path)
        if extra_path.exists() and extra_str not in sys.path:
            sys.path.insert(0, extra_str)
    except Exception:
        pass

def _load_docdex_client() -> bool:
    global docdex_client, _docdex_logged_success
    if docdex_client is not None:
        print("[work_on_tasks] docdex_client already loaded", file=sys.stderr)
        return True
    try:
        docdex_client = importlib.import_module("docdex_client")  # type: ignore
        if not _docdex_logged_success:
            print("[work_on_tasks] docdex_client import succeeded", file=sys.stderr)
            _docdex_logged_success = True
        return True
    except Exception as err:  # pragma: no cover - optional dependency
        print(f"[work_on_tasks] docdex_client import failed: {err}", file=sys.stderr)
        docdex_client = None  # type: ignore
        return False


_load_docdex_client()


def _silence_prompt_logs() -> None:
    """Keep noisy prompt-generation loggers from spamming stdout."""
    targets = (
        "gpt_creator.promptgen",
        "gpt_creator.prompt",
        "openai",
        "httpx",
        "urllib3",
    )
    for name in targets:
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
