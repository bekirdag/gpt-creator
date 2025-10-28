#!/usr/bin/env python3
"""Render file snippets with caching and diff support for `gpt-creator show-file`."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def load_lines(file_path: Path) -> tuple[list[str], int]:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return lines, len(lines)


def select_snippet(
    lines: list[str],
    total: int,
    *,
    range_spec: str,
    head_lines: str,
    tail_lines: str,
    max_lines: int,
) -> tuple[list[str], int, int, bool]:
    if total == 0:
        return [], 1, 0, False

    if range_spec:
        raw = range_spec
        if ":" in raw:
            start_s, end_s = raw.split(":", 1)
        else:
            start_s, end_s = raw, ""
        try:
            start_line = int(start_s) if start_s.strip() else 1
        except Exception:
            start_line = 1
        try:
            end_line = int(end_s) if end_s.strip() else total
        except Exception:
            end_line = total
        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            end_line = start_line
        if end_line > total:
            end_line = total
        snippet = lines[start_line - 1 : end_line]
        truncated = (end_line - start_line + 1) < total
        return snippet, start_line, end_line, truncated

    if head_lines:
        try:
            count = int(head_lines)
        except Exception:
            count = max_lines
        if count <= 0:
            count = max_lines
        snippet = lines[:count]
        end_line = min(total, count)
        truncated = end_line < total
        return snippet, 1, end_line, truncated

    if tail_lines:
        try:
            count = int(tail_lines)
        except Exception:
            count = max_lines
        if count <= 0:
            count = max_lines
        snippet = lines[-count:] if count < total else lines[:]
        start_line = total - len(snippet) + 1
        truncated = len(snippet) < total
        return snippet, start_line, total, truncated

    snippet = lines[: min(total, max_lines)]
    end_line = len(snippet)
    truncated = end_line < total
    return snippet, 1, end_line, truncated


def write_cache(cache_path: Path, cache_dir: Path, payload: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def format_header(
    rel_path: str,
    start_line: int,
    end_line: int,
    total: int,
    digest: str,
    note: str = "",
) -> str:
    details = f"{rel_path} (lines {start_line}-{end_line} of {total}; sha256 {digest})"
    if note:
        details += f" — {note}"
    return f"## {details}"


def main() -> None:
    project_root = Path(os.environ.get("GC_SHOW_FILE_PROJECT", "") or ".").resolve()
    path = Path(os.environ.get("GC_SHOW_FILE_PATH", "")).resolve()
    rel_path = os.environ.get("GC_SHOW_FILE_REL") or str(path)
    range_spec = (os.environ.get("GC_SHOW_FILE_RANGE") or "").strip()
    head_lines = (os.environ.get("GC_SHOW_FILE_HEAD") or "").strip()
    tail_lines = (os.environ.get("GC_SHOW_FILE_TAIL") or "").strip()
    max_lines_raw = (os.environ.get("GC_SHOW_FILE_MAX_LINES") or "").strip()
    refresh = os.environ.get("GC_SHOW_FILE_REFRESH") == "1"
    diff_mode = os.environ.get("GC_SHOW_FILE_DIFF") == "1"
    cache_dir = Path(os.environ.get("GC_SHOW_FILE_CACHE_DIR") or "").resolve()

    if not path.exists():
        print(f"File not found: {rel_path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        max_lines = int(max_lines_raw or 400)
    except Exception:
        max_lines = 400
    if max_lines <= 0:
        max_lines = 400

    mode_descriptor = []
    if range_spec:
        mode_descriptor.append(f"range:{range_spec}")
    if head_lines:
        mode_descriptor.append(f"head:{head_lines}")
    if tail_lines:
        mode_descriptor.append(f"tail:{tail_lines}")
    if not mode_descriptor:
        mode_descriptor.append(f"default:{max_lines}")
    mode_string = "|".join(mode_descriptor)

    cache_key_raw = f"{path}::{mode_string}"
    cache_key = hashlib.sha256(cache_key_raw.encode("utf-8", "replace")).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"

    dedup_ttl_env = os.environ.get("GC_SCAN_DEDUP_TTL", "120").strip()
    try:
        dedup_ttl = float(dedup_ttl_env or 0)
    except Exception:
        dedup_ttl = 0.0
    dedup_enabled = (
        dedup_ttl > 0
        and os.environ.get("GC_DISABLE_SCAN_DEDUP", "0") != "1"
        and (
            ".gpt-creator/staging/" in str(path)
            or ".gpt-creator/plan/" in str(path)
            or ".gpt-creator/work/" in str(path)
        )
    )
    dedup_path = None
    dedup_dir = None

    file_stat = path.stat()
    existing = None
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            existing = None

    if dedup_enabled:
        dedup_dir = cache_dir / "_dedup"
        dedup_dir.mkdir(parents=True, exist_ok=True)
        dedup_path = dedup_dir / f"{cache_key}.json"
        if refresh:
            try:
                dedup_record = (
                    json.loads(dedup_path.read_text(encoding="utf-8"))
                    if dedup_path.exists()
                    else None
                )
            except Exception:
                dedup_record = None
            else:
                if dedup_record:
                    try:
                        last_ts = float(dedup_record.get("ts", 0.0))
                    except Exception:
                        last_ts = 0.0
                    prev_mtime = int(dedup_record.get("mtime_ns", -1))
                    prev_size = int(dedup_record.get("size", -1))
                    if (
                        last_ts > 0
                        and (time.time() - last_ts) < dedup_ttl
                        and prev_mtime == getattr(file_stat, "st_mtime_ns", None)
                        and prev_size == file_stat.st_size
                    ):
                        refresh = False
                        print(
                            f"[scan-dedup] skip (unchanged, ttl={int(dedup_ttl)}s): {rel_path}",
                            file=sys.stdout,
                        )

    if existing and not refresh and not diff_mode:
        if (
            existing.get("mtime_ns") == file_stat.st_mtime_ns
            and existing.get("size") == file_stat.st_size
        ):
            if dedup_enabled and dedup_path:
                dedup_payload = {
                    "ts": time.time(),
                    "mtime_ns": file_stat.st_mtime_ns,
                    "size": file_stat.st_size,
                }
                try:
                    dedup_path.write_text(json.dumps(dedup_payload))
                except Exception:
                    pass
            start_line = existing.get("start_line", 1)
            end_line = existing.get("end_line", start_line - 1)
            total_lines = existing.get("total_lines", "?")
            digest = existing.get("snippet_hash", "unknown")
            updated_at = existing.get("updated_at", "")
            note = f"cached snapshot {updated_at}" if updated_at else "cached snapshot"
            print(
                f"(cached) {rel_path} lines {start_line}-{end_line} of {total_lines} "
                f"(sha256 {digest}); use --refresh to re-display or --diff to compare."
            )
            raise SystemExit(0)

    lines, total_lines = load_lines(path)
    snippet_lines, start_line, end_line, truncated_display = select_snippet(
        lines,
        total_lines,
        range_spec=range_spec,
        head_lines=head_lines,
        tail_lines=tail_lines,
        max_lines=max_lines,
    )
    snippet_text = "\n".join(snippet_lines)
    snippet_hash = hashlib.sha256(snippet_text.encode("utf-8", "replace")).hexdigest()[:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    display_note = ""
    if truncated_display and total_lines:
        display_note = (
            f"display truncated (showing lines {start_line}-{end_line} of {total_lines}); "
            "use --range START:END or read the file directly for additional context."
        )

    cache_payload = {
        "path": str(path),
        "relative": rel_path,
        "mode": mode_string,
        "start_line": start_line,
        "end_line": end_line,
        "total_lines": total_lines,
        "snippet_hash": snippet_hash,
        "snippet": snippet_text,
        "mtime_ns": file_stat.st_mtime_ns,
        "size": file_stat.st_size,
        "updated_at": timestamp,
        "truncated": bool(truncated_display),
    }

    if diff_mode and existing:
        old_snippet = existing.get("snippet", "")
        old_start = existing.get("start_line", 1)
        old_end = existing.get("end_line", old_start - 1)
        if old_snippet == snippet_text:
            print(
                f"(no diff) {rel_path} lines {start_line}-{end_line} unchanged "
                "compared to cached snapshot."
            )
        else:
            old_lines = old_snippet.splitlines()
            diff = list(
                difflib.unified_diff(
                    old_lines,
                    snippet_text.splitlines(),
                    fromfile=f"cached/{rel_path}:{old_start}-{old_end}",
                    tofile=f"updated/{rel_path}:{start_line}-{end_line}",
                    lineterm="",
                )
            )
            if not diff:
                print(
                    f"(no diff) {rel_path} lines {start_line}-{end_line} unchanged "
                    "compared to cached snapshot."
                )
            else:
                print(
                    format_header(
                        rel_path, start_line, end_line, total_lines, snippet_hash, note="diff vs cached"
                    )
                )
                for line in diff:
                    print(line)
        write_cache(cache_path, cache_dir, cache_payload)
        raise SystemExit(0)

    print(format_header(rel_path, start_line, end_line, total_lines, snippet_hash, note=display_note))
    if truncated_display:
        print(
            f"! Display truncated to lines {start_line}-{end_line} of {total_lines}. "
            f"Run `gpt-creator show-file {rel_path} --range START:END` with bounds covering the "
            "desired lines or read the file directly for the remaining content."
        )
    if snippet_text:
        print(snippet_text)
    else:
        print("(no content in selected range)")

    write_cache(cache_path, cache_dir, cache_payload)
    if dedup_enabled and dedup_path:
        dedup_payload = {
            "ts": time.time(),
            "mtime_ns": file_stat.st_mtime_ns,
            "size": file_stat.st_size,
        }
        try:
            dedup_path.write_text(json.dumps(dedup_payload))
        except Exception:
            pass


if __name__ == "__main__":
    main()

