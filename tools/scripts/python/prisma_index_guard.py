#!/usr/bin/env python3
"""Detect Prisma migrations that drop required indexes without recreating them.

The guard runs before work-on-tasks to prevent acceptance regressions where a
migration removes mandated indexes (for example SDS §5.2.2 session indexes) and
never brings them back. It is intentionally conservative:

* Any `@@index(..., name: "...")` declared in the Prisma schema must have a
  corresponding CREATE INDEX somewhere after the latest DROP INDEX.
* Additional required index names can be supplied via the environment variable
  `GC_PRISMA_REQUIRED_INDEXES`. Accepts a JSON array or a comma-separated list.
* Specific indexes can be exempted with `GC_PRISMA_INDEX_GUARD_ALLOW_DROP`.

If it finds a missing index, it exits non-zero and prints remediation guidance.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, MutableMapping, Set


DEFAULT_REQUIRED_INDEXES = {
    # SDS §5.2.2 requires these for session expiry sweeper + active lookups.
    "idx_sessions_expires_at",
    "idx_sessions_user_active",
}

PRISMA_INDEX_PATTERN = re.compile(
    r"@@index\([^)]*name\s*:\s*\"(?P<name>[^\"]+)\"", re.IGNORECASE
)


@dataclass
class DropRecord:
    name: str
    migration_path: Path


def parse_env_names(var_name: str) -> Set[str]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return set()
    values: Iterable[str]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        values = (str(item).strip() for item in parsed if str(item).strip())
    else:
        values = (item.strip() for item in raw.split(",") if item.strip())
    return {value for value in values if value}


def collect_schema_indexes(schema_path: Path) -> Set[str]:
    if not schema_path.is_file():
        return set()
    try:
        text = schema_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()
    return {
        match.group("name").strip()
        for match in PRISMA_INDEX_PATTERN.finditer(text)
        if match.group("name").strip()
    }


def iter_migration_sql(migrations_dir: Path) -> Iterable[Path]:
    if not migrations_dir.is_dir():
        return []
    for entry in sorted(migrations_dir.iterdir()):
        if not entry.is_dir():
            continue
        sql_path = entry / "migration.sql"
        if sql_path.is_file():
            yield sql_path


def scan_migrations(migrations_dir: Path) -> MutableMapping[str, DropRecord]:
    pending: MutableMapping[str, DropRecord] = {}
    for sql_path in iter_migration_sql(migrations_dir):
        try:
            text = sql_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            # If we cannot read the file, treat it as no-op for safety.
            continue
        for match in re.finditer(
            r"DROP\s+INDEX(?:\s+IF\s+EXISTS)?\s+`(?P<drop>[^`]+)`|CREATE\s+(?:UNIQUE\s+)?INDEX\s+`(?P<create>[^`]+)`\s+ON",
            text,
            flags=re.IGNORECASE,
        ):
            drop_name = match.group("drop")
            create_name = match.group("create")
            if drop_name:
                name = drop_name.strip()
                if name:
                    pending[name.lower()] = DropRecord(name=name, migration_path=sql_path)
            elif create_name:
                name = create_name.strip()
                if name:
                    pending.pop(name.lower(), None)
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify required indexes remain after Prisma migrations.")
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--migrations", required=True, type=Path)
    args = parser.parse_args()

    required = {name.lower() for name in DEFAULT_REQUIRED_INDEXES}
    required |= {name.lower() for name in collect_schema_indexes(args.schema)}
    required |= {name.lower() for name in parse_env_names("GC_PRISMA_REQUIRED_INDEXES")}
    required -= {name.lower() for name in parse_env_names("GC_PRISMA_INDEX_GUARD_ALLOW_DROP")}

    if not required:
        return 0

    pending = scan_migrations(args.migrations)
    if not pending:
        return 0

    missing = {name: record for name, record in pending.items() if name in required}
    if not missing:
        return 0

    print("Detected Prisma migration(s) that drop required index definitions without recreating them:", file=sys.stderr)
    for name, record in sorted(missing.items()):
        print(f"  - {record.name} (dropped in {record.migration_path})", file=sys.stderr)
    print(
        "Add a follow-up migration that restores each index (e.g. `CREATE INDEX ...`) "
        "and keep the Prisma schema in sync (`@@index([...], name: \"...\")`).",
        file=sys.stderr,
    )
    print(
        "If the removal is intentional, add the index name to GC_PRISMA_INDEX_GUARD_ALLOW_DROP.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
