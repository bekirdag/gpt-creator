#!/usr/bin/env python3
"""Regenerate doc catalog artifacts in the format expected by work-on-tasks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh documentation catalog artifacts.")
    parser.add_argument("--project-root", required=True, help="Repository root to scan")
    parser.add_argument("--staging-dir", required=True, help="Staging directory for catalog outputs")
    parser.add_argument("--out-json", required=True, help="Path to write doc-catalog JSON")
    parser.add_argument("--out-library", required=True, help="Path to write Markdown library file")
    parser.add_argument("--out-index", required=True, help="Path to write Markdown index file")
    return parser.parse_args()


def run_doc_catalog_list(project_root: Path) -> Tuple[int, str, str]:
    catalog_script = Path(__file__).resolve().parent / "doc_catalog.py"
    cmd = [sys.executable, str(catalog_script), "list", "--limit", "2000"]
    proc = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def parse_listing(output: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=1)
        doc_id = parts[0]
        rel_path = parts[1] if len(parts) > 1 else ""
        entries.append((doc_id, rel_path))
    return entries


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, entries: List[Tuple[str, str]]) -> None:
    payload = {
        "documents": {
            doc_id: {
                "path": rel_path,
            }
            for doc_id, rel_path in entries
        },
        "snippets": {},
        "version": 1,
    }
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, title: str, entries: List[Tuple[str, str]]) -> None:
    ensure_parent(path)
    lines = [f"# {title}", ""]
    for doc_id, rel_path in entries:
        if rel_path:
            lines.append(f"- **{doc_id}** `{rel_path}`")
        else:
            lines.append(f"- **{doc_id}**")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    retcode, stdout, stderr = run_doc_catalog_list(project_root)
    if retcode != 0:
        sys.stderr.write(stderr or stdout or "doc catalog listing failed\n")
        return retcode
    entries = parse_listing(stdout)
    if not entries:
        sys.stderr.write("doc catalog listing empty; nothing to refresh\n")
        return 0
    write_json(Path(args.out_json), entries)
    write_markdown(Path(args.out_library), "Documentation Library", entries)
    write_markdown(Path(args.out_index), "Documentation Index", entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
