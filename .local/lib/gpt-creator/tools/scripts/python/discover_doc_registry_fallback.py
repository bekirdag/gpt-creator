#!/usr/bin/env python3
"""Resolve a fallback documentation path from the tasks registry."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


DOC_TYPE_MAP = {
    "pdr": "pdr",
    "sds": "sds",
    "rfp": "rfp",
    "jira": "jira",
    "ui_pages": "ui",
    "openapi": "openapi",
    "sql": "sql",
}

SEARCH_TERMS_MAP = {
    "pdr": ["pdr", "product"],
    "sds": ["sds", "system", "design-spec"],
    "rfp": ["rfp", "proposal"],
    "jira": ["jira"],
    "ui_pages": ["ui-pages", "ui_pages", "ui pages", "ui"],
    "openapi": ["openapi", "swagger"],
    "sql": [".sql", "dump"],
}


def pick(row: sqlite3.Row | None) -> str:
    if row is None:
        return ""
    value = row["resolved_path"]
    if not value:
        return ""
    try:
        return str(Path(value).resolve())
    except Exception:
        return str(Path(value))


def query_fallback(registry: Path, key: str) -> str:
    doc_type = DOC_TYPE_MAP.get(key, "")

    if not registry.exists():
        return ""

    try:
        conn = sqlite3.connect(str(registry))
        conn.row_factory = sqlite3.Row
    except Exception:
        return ""

    try:
        try:
            if doc_type:
                row = conn.execute(
                    """
                    SELECT COALESCE(staging_path, source_path) AS resolved_path
                    FROM documentation
                    WHERE status = 'active' AND doc_type = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (doc_type,),
                ).fetchone()
                resolved = pick(row)
                if resolved:
                    return resolved

            if doc_type:
                row = conn.execute(
                    """
                    SELECT COALESCE(staging_path, source_path) AS resolved_path
                    FROM documentation
                    WHERE status = 'active' AND tags_json LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (f'%"{doc_type}"%',),
                ).fetchone()
                resolved = pick(row)
                if resolved:
                    return resolved

            for term in SEARCH_TERMS_MAP.get(key, []):
                term = term.lower()
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
                if resolved:
                    return resolved
        except sqlite3.Error:
            return ""
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return ""


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(1)
    registry = Path(sys.argv[1])
    key = sys.argv[2]
    print(query_fallback(registry, key))


if __name__ == "__main__":
    main()
