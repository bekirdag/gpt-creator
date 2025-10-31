#!/usr/bin/env python3
"""
Publish prompt snapshots into a repository-friendly registry.

This keeps a canonical copy of each generated prompt (plus metadata such as
story/task identifiers and SHA256). Snapshots are written under a configurable
subdirectory so teams can review prompts without spelunking the staging cache.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

DEFAULT_TARGET_DIR = Path("docs") / "automation" / "prompts"
DEFAULT_INDEX_PATH = Path("docs") / "PROMPTS.md"


def _sha256_text(text: str) -> str:
    digest = hashlib.sha256()
    digest.update(text.encode("utf-8", "ignore"))
    return digest.hexdigest()


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def normalise_text(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"


def _context_from_meta(meta_path: Path) -> dict:
    try:
        raw = meta_path.read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def publish_prompt(
    prompt_path: Path,
    meta_path: Path,
    project_root: Path,
    *,
    target_dir: Optional[Path] = None,
    index_path: Optional[Path] = None,
) -> Path:
    """
    Publish a prompt snapshot into the working repository.

    Args:
        prompt_path: path to the generated prompt markdown.
        meta_path: companion metadata file produced during prompt build.
        project_root: repository root so paths can be made relative.
        target_dir: optional override for the destination directory.
        index_path: optional override for markdown index file.

    Returns:
        The relative path (from project root) where the prompt snapshot lives.
    """
    project_root = project_root.resolve()
    prompt_path = prompt_path.resolve()
    meta_path = meta_path.resolve()

    target_dir = target_dir or DEFAULT_TARGET_DIR
    if not target_dir.is_absolute():
        target_dir = project_root / target_dir
    index_path = index_path or DEFAULT_INDEX_PATH
    if not index_path.is_absolute():
        index_path = project_root / index_path

    meta = _context_from_meta(meta_path)
    body = prompt_path.read_text(encoding="utf-8", errors="ignore")
    body = normalise_text(body)

    run_id = str(meta.get("run_id") or meta.get("run_stamp") or "run").strip()
    story_id = str(meta.get("story_id") or meta.get("story_slug") or meta.get("story") or "story").strip()
    task_id = str(meta.get("task_id") or meta.get("task") or "task").strip()

    digest = str(meta.get("sha256") or _sha256_text(body)).lower()
    byte_count = len(body.encode("utf-8"))

    timestamp = meta.get("created_at") or int(time.time())
    if isinstance(timestamp, str) and timestamp.isdigit():
        timestamp = int(timestamp)

    dest = target_dir / run_id / story_id / f"task_{task_id}.prompt.md"
    _atomic_write(dest, body)

    relative_dest = dest.relative_to(project_root)
    summary_line = (
        f"- `{story_id}#{task_id}` → {relative_dest.as_posix()} · "
        f"sha:{digest[:12]} · bytes:{byte_count} · ts:{timestamp}"
    )

    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8", errors="ignore")
        if summary_line not in existing:
            updated = existing.rstrip() + "\n" + summary_line + "\n"
            _atomic_write(index_path, updated)
    else:
        header = "# Prompt Snapshots\n\n"
        _atomic_write(index_path, header + summary_line + "\n")

    return relative_dest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish prompt snapshot into docs/automation/prompts.")
    parser.add_argument("prompt_path", type=Path)
    parser.add_argument("meta_path", type=Path)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--target-dir", type=Path, default=None, help="Override destination directory.")
    parser.add_argument("--index-md", type=Path, default=None, help="Override index markdown file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dest = publish_prompt(
        args.prompt_path,
        args.meta_path,
        args.project_root,
        target_dir=args.target_dir,
        index_path=args.index_md,
    )
    print(dest.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
