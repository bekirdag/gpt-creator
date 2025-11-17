#!/usr/bin/env python3
"""
Targeted repository search helper.

Designed to replace ad-hoc "python3 - <<'PY' ... os.walk(...)" scripts that scan
the entire repo for a handful of strings. This tool keeps searches bounded:
  * requires explicit directories/paths (no implicit whole-repo walk)
  * limits depth, file count, and match count unless you opt in
  * reports concise snippets for each hit
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence


DEFAULT_EXTS = {".ts", ".tsx", ".js", ".jsx", ".py", ".md"}
MAX_DEFAULT_FILES = 200
MAX_DEFAULT_MATCHES = 200


@dataclass
class SearchHit:
  path: Path
  line_no: int
  line_text: str
  pattern: str
  context: list[tuple[int, str]] | None = None


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
      description="Search a limited set of files for text or regex patterns.",
  )
  parser.add_argument(
      "--pattern",
      "-p",
      action="append",
      required=True,
      help="Text or regex pattern to search for (repeatable).",
  )
  parser.add_argument(
      "--regex",
      action="store_true",
      help="Treat patterns as regular expressions (default: literal substring).",
  )
  parser.add_argument(
      "--case-sensitive",
      action="store_true",
      help="Case-sensitive search (default: case-insensitive).",
  )
  parser.add_argument(
      "--paths",
      "-P",
      action="append",
      required=True,
      help="Directories or files to inspect (repeatable).",
  )
  parser.add_argument(
      "--ext",
      action="append",
      default=[],
      help="File extension whitelist (repeatable, e.g. --ext .ts). Defaults to a small set.",
  )
  parser.add_argument(
      "--max-depth",
      type=int,
      default=4,
      help="Maximum directory depth to traverse from each path (default: 4).",
  )
  parser.add_argument(
      "--max-files",
      type=int,
      default=MAX_DEFAULT_FILES,
      help=f"Maximum files to scan before stopping (default: {MAX_DEFAULT_FILES}).",
  )
  parser.add_argument(
      "--allow-large",
      action="store_true",
      help="Permit scanning more than --max-files files (use cautiously).",
  )
  parser.add_argument(
      "--max-matches",
      type=int,
      default=MAX_DEFAULT_MATCHES,
      help=f"Maximum matches to display (default: {MAX_DEFAULT_MATCHES}).",
  )
  parser.add_argument(
      "--context",
      type=int,
      default=0,
      help="Number of context lines to show before/after each match.",
  )
  parser.add_argument(
      "--include-hidden",
      action="store_true",
      help="Include files or directories that start with '.'.",
  )
  parser.add_argument(
      "--no-summary",
      action="store_true",
      help="Suppress the summary footer.",
  )
  return parser.parse_args()


def normalize_exts(exts: Sequence[str]) -> set[str]:
  if not exts:
    return set(DEFAULT_EXTS)
  normalized = set()
  for ext in exts:
    e = ext.lower()
    if not e.startswith("."):
      e = f".{e}"
    normalized.add(e)
  return normalized


def iter_files(
    root: Path,
    *,
    max_depth: int,
    include_hidden: bool,
    allowed_exts: set[str],
) -> Iterator[Path]:
  if root.is_file():
    if not root.name.startswith(".") or include_hidden:
      if not allowed_exts or root.suffix.lower() in allowed_exts:
        yield root
    return

  def _walk(current: Path, depth: int) -> Iterator[Path]:
    if depth > max_depth:
      return
    try:
      entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except FileNotFoundError:
      return
    for entry in entries:
      if not include_hidden and entry.name.startswith("."):
        continue
      if entry.is_dir():
        yield from _walk(entry, depth + 1)
        continue
      if allowed_exts and entry.suffix.lower() not in allowed_exts:
        continue
      yield entry

  yield from _walk(root, 0)


def collect_files(
    paths: Sequence[str],
    *,
    max_depth: int,
    include_hidden: bool,
    allowed_exts: set[str],
    max_files: int,
) -> tuple[list[Path], bool]:
  files: list[Path] = []
  truncated = False
  seen: set[Path] = set()
  for raw in paths:
    path = Path(raw).resolve()
    if not path.exists():
      print(f"[targeted-search] path not found: {path}", file=sys.stderr)
      continue
    for candidate in iter_files(
        path,
        max_depth=max_depth,
        include_hidden=include_hidden,
        allowed_exts=allowed_exts,
    ):
      if candidate in seen:
        continue
      seen.add(candidate)
      files.append(candidate)
      if len(files) >= max_files:
        truncated = True
        return files, truncated
  return files, truncated


def compile_patterns(patterns: Sequence[str], *, regex: bool, case_sensitive: bool) -> list[re.Pattern[str]]:
  flags = 0 if case_sensitive else re.IGNORECASE
  compiled: list[re.Pattern[str]] = []
  for pattern in patterns:
    text = pattern if regex else re.escape(pattern)
    try:
      compiled.append(re.compile(text, flags))
    except re.error as exc:
      print(f"[targeted-search] invalid regex '{pattern}': {exc}", file=sys.stderr)
  return compiled


def search_file(
    path: Path,
    compiled: Sequence[re.Pattern[str]],
    *,
    max_matches: int,
    context: int,
    current_matches: int,
) -> tuple[list[SearchHit], int, bool]:
  hits: list[SearchHit] = []
  try:
    text = path.read_text(encoding="utf-8", errors="ignore")
  except OSError as exc:
    print(f"[targeted-search] unable to read {path}: {exc}", file=sys.stderr)
    return hits, current_matches, False
  lines = text.splitlines()
  for idx, line in enumerate(lines, start=1):
    for pattern in compiled:
      if not pattern.search(line):
        continue
      ctx_block: list[tuple[int, str]] | None = None
      if context > 0:
        start = max(1, idx - context)
        end = min(len(lines), idx + context)
        ctx_block = [(lineno, lines[lineno - 1]) for lineno in range(start, end + 1)]
      hits.append(
          SearchHit(
              path=path,
              line_no=idx,
              line_text=line.rstrip(),
              pattern=pattern.pattern,
              context=ctx_block,
          )
      )
      current_matches += 1
      if current_matches >= max_matches:
        return hits, current_matches, True
      break
  return hits, current_matches, current_matches >= max_matches


def format_hits(hits: Iterable[SearchHit]) -> None:
  for hit in hits:
    snippet = hit.line_text.strip()
    print(f"{hit.path}:{hit.line_no}: {snippet}")
    if hit.context:
      for lineno, text in hit.context:
        prefix = ">" if lineno == hit.line_no else " "
        print(f"    {prefix} {lineno:>4}: {text.rstrip()}")
      print()


def main() -> None:
  args = parse_args()
  allowed_exts = normalize_exts(args.ext)
  file_limit = args.max_files if not args.allow_large else max(args.max_files, MAX_DEFAULT_FILES * 10)
  files, truncated = collect_files(
      args.paths,
      max_depth=max(0, args.max_depth),
      include_hidden=args.include_hidden,
      allowed_exts=allowed_exts,
      max_files=max(1, file_limit),
  )
  if not files:
    print("[targeted-search] no files matched the provided paths/extensions.", file=sys.stderr)
    sys.exit(1)
  if truncated and not args.allow_large:
    print(
        f"[targeted-search] reached file limit ({args.max_files}); searched first {len(files)} files only. "
        "Refine --paths/--ext or pass --allow-large to cover more files.",
        file=sys.stderr,
    )

  compiled = compile_patterns(
      args.pattern,
      regex=args.regex,
      case_sensitive=args.case_sensitive,
  )
  if not compiled:
    print("[targeted-search] no valid patterns to search.", file=sys.stderr)
    sys.exit(3)

  total_matches = 0
  for path in files:
    hits, total_matches, exhausted = search_file(
        path,
        compiled,
        max_matches=max(1, args.max_matches),
        context=max(0, args.context),
        current_matches=total_matches,
    )
    if hits:
      format_hits(hits)
    if exhausted:
      print("[targeted-search] max matches reached; stopping early.", file=sys.stderr)
      break

  if not args.no_summary:
    print(f"\nScanned {len(files)} file(s); matched {total_matches} line(s).")


if __name__ == "__main__":
  try:
    main()
  except KeyboardInterrupt:
    sys.exit(130)
