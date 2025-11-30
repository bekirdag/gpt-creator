#!/usr/bin/env python3
"""Populate missing discovery manifest entries with best-effort defaults."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_REQUIRED = ["pdr", "sds", "rfp", "jira", "ui_pages", "openapi", "sql"]


def parse_found_section(lines: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    entries: dict[str, str] = {}
    order: list[str] = []
    seen: set[str] = set()
    in_found = False
    base_indent: int | None = None

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped == "found:" and raw.lstrip() == stripped:
            in_found = True
            base_indent = None
            continue
        if not in_found:
            continue
        indent = len(raw) - len(raw.lstrip())
        if base_indent is None:
            if indent <= 0:
                in_found = False
                continue
            base_indent = indent
        if indent < base_indent or not stripped or ":" not in stripped:
            in_found = False
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        entries[key] = value
        if key not in seen:
            order.append(key)
            seen.add(key)

    return order, entries


def determine_roots(file_path: Path) -> tuple[Path, Path, Path]:
    input_dir_env = os.environ.get("INPUT_DIR")
    candidates: list[Path] = []
    if input_dir_env:
        candidates.append(Path(input_dir_env))
    candidates.append(file_path.parent / "inputs")
    candidates.append(file_path.parent)

    input_dir: Path | None = None
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved.exists():
            input_dir = resolved
            break

    if input_dir is None:
        input_dir = file_path.parent.resolve()

    staging_root = input_dir.parent if input_dir.name == "inputs" else input_dir
    project_root = staging_root.parent if staging_root.name == "staging" else staging_root

    return input_dir, staging_root, project_root


def resolve_candidate(base: Path | None, relative: str) -> Path | None:
    if base is None:
        return None
    target = base / relative if relative else base
    try:
        resolved = target.resolve()
    except Exception:
        resolved = target
    return resolved if resolved.exists() else None


def resolve_from_registry(staging_root: Path, key: str) -> Path | None:
    doc_type_map = {
        "pdr": "pdr",
        "sds": "sds",
        "rfp": "rfp",
        "jira": "jira",
        "ui_pages": "ui",
        "openapi": "openapi",
        "sql": "sql",
    }
    doc_type = doc_type_map.get(key)
    if not doc_type:
        return None

    registry_path = staging_root / "plan" / "tasks" / "tasks.db"
    if not registry_path.exists():
        return None

    try:
        conn = sqlite3.connect(str(registry_path))
        conn.row_factory = sqlite3.Row  # type: ignore[attr-defined]
    except Exception:
        return None

    def pick(row: sqlite3.Row | None) -> Path | None:
        if not row:
            return None
        candidate = row["resolved_path"]
        if not candidate:
            return None
        try:
            return Path(candidate).resolve()
        except Exception:
            return Path(candidate)

    try:
        row = conn.execute(
            """
            SELECT COALESCE(staging_path, source_path) AS resolved_path
            FROM documentation
            WHERE status = 'active'
              AND doc_type = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (doc_type,),
        ).fetchone()
        resolved = pick(row)
        if resolved is None:
            row = conn.execute(
                """
                SELECT COALESCE(staging_path, source_path) AS resolved_path
                FROM documentation
                WHERE status = 'active'
                  AND tags_json LIKE ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (f'%"{doc_type}"%',),
            ).fetchone()
            resolved = pick(row)

        if resolved is None:
            search_terms = {
                "pdr": ["pdr", "product"],
                "sds": ["sds", "system", "design-spec"],
                "rfp": ["rfp", "proposal"],
                "jira": ["jira"],
                "ui_pages": ["ui-pages", "ui_pages", "ui pages", "ui"],
                "openapi": ["openapi", "swagger"],
                "sql": [".sql", "dump"],
            }.get(key, [])
            lowered_terms = [term.lower() for term in search_terms]
            for term in lowered_terms:
                row = conn.execute(
                    """
                    SELECT COALESCE(staging_path, source_path) AS resolved_path
                    FROM documentation
                    WHERE status = 'active'
                      AND (
                        LOWER(COALESCE(rel_path, '')) LIKE ?
                        OR LOWER(COALESCE(file_name, '')) LIKE ?
                      )
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (f"%{term}%", f"%{term}%"),
                ).fetchone()
                resolved = pick(row)
                if resolved is not None:
                    break
    except Exception:
        resolved = None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return resolved


def populate_entries(
    file_path: Path, required: list[str], order: list[str], entries: dict[str, str]
) -> None:
    seen = set(order)
    for key in required:
        if key not in entries or not entries[key].strip():
            entries[key] = ""
            if key not in seen:
                order.append(key)
                seen.add(key)

    for key in list(entries):
        if key not in seen:
            order.append(key)
            seen.add(key)

    input_dir, staging_root, project_root = determine_roots(file_path)

    locations: dict[str, Path | None] = {
        "input_dir": input_dir,
        "staging_root": staging_root,
        "staging_docs": staging_root / "docs",
        "staging_openapi": staging_root / "openapi",
        "staging_sql": staging_root / "sql",
        "project_root": project_root,
        "project_docs": project_root / "docs",
        "project_openapi": project_root / "openapi",
        "project_sql": project_root / "sql",
    }

    candidate_map: dict[str, list[tuple[str, str]]] = {
        "pdr": [
            ("input_dir", "pdr.md"),
            ("staging_docs", "pdr.md"),
            ("staging_docs", "PDR.md"),
            ("project_docs", "pdr.md"),
            ("project_docs", "PDR.md"),
        ],
        "sds": [
            ("input_dir", "sds.md"),
            ("staging_docs", "sds.md"),
            ("project_docs", "sds.md"),
        ],
        "rfp": [
            ("input_dir", "rfp.md"),
            ("staging_docs", "rfp.md"),
            ("project_docs", "rfp.md"),
        ],
        "jira": [
            ("input_dir", "jira.md"),
            ("staging_docs", "jira.md"),
            ("project_docs", "jira.md"),
        ],
        "ui_pages": [
            ("input_dir", "ui-pages.md"),
            ("input_dir", "ui_pages.md"),
            ("staging_docs", "ui-pages.md"),
            ("staging_docs", "ui_pages.md"),
            ("project_docs", "ui-pages.md"),
            ("project_docs", "ui_pages.md"),
        ],
        "openapi": [
            ("input_dir", "openapi.yaml"),
            ("input_dir", "openapi.yml"),
            ("input_dir", "openapi.json"),
            ("staging_openapi", "openapi.yaml"),
            ("staging_openapi", "openapi.yml"),
            ("staging_openapi", "openapi.json"),
            ("project_openapi", "openapi.yaml"),
            ("project_openapi", "openapi.yml"),
            ("project_openapi", "openapi.json"),
        ],
        "sql": [
            ("input_dir", "sql"),
            ("staging_sql", ""),
            ("project_sql", ""),
        ],
    }

    for key in required:
        value = entries.get(key, "").strip()
        if value and value.lower() != "n/a":
            continue

        resolved = None
        for base_key, relative in candidate_map.get(key, []):
            resolved = resolve_candidate(locations.get(base_key), relative)
            if resolved is not None:
                break

        if resolved is None:
            resolved = resolve_from_registry(staging_root, key)

        entries[key] = str(resolved) if resolved is not None else "n/a"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(1)
    file_path = Path(sys.argv[1])
    required = list(sys.argv[2:]) or DEFAULT_REQUIRED

    raw_lines = file_path.read_text(encoding="utf-8").splitlines()
    if raw_lines and raw_lines[0].strip() == "---":
        header = ["---"]
        content_lines = raw_lines[1:]
    else:
        header = []
        content_lines = raw_lines

    order, entries = parse_found_section(content_lines)
    populate_entries(file_path, required, order, entries)

    out_lines = header[:]
    out_lines.append("found:")
    for key in order:
        out_lines.append(f"  {key}: {entries.get(key, 'n/a')}")

    file_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
