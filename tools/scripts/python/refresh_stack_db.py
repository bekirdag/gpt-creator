#!/usr/bin/env python3
"""
Apply schema/seed SQL to a running MySQL container for refresh-stack.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


def run_mysql(container: str, sql_file: Path, user: str, password: str, db: str, port: str) -> bool:
    cmd = [
        "docker",
        "exec",
        "-i",
        container,
        "sh",
        "-c",
        f"mysql -u{user} -p'{password}' -P {port} -h 127.0.0.1 {db}",
    ]
    with sql_file.open("rb") as fh:
        proc = subprocess.run(cmd, stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode == 0


def apply_sql(files: Iterable[Path], container: str, root_user: str, root_pass: str, app_user: str, app_pass: str, db_name: str, port: str, nullable_db: bool) -> Tuple[int, List[str]]:
    rc = 0
    applied: List[str] = []
    for file in files:
        if not file.is_file():
            rc = 1
            continue
        db_arg = db_name if not nullable_db else ""
        if run_mysql(container, file, root_user, root_pass, db_arg, port):
            applied.append(str(file))
            continue
        if run_mysql(container, file, app_user, app_pass, db_arg, port):
            applied.append(str(file))
            continue
        rc = 1
    return rc, applied


def main(argv: list[str]) -> int:
    if len(argv) < 9:
        print(
            "Usage: refresh_stack_db.py <container> <root_user> <root_pass> <app_user> <app_pass> <db_name> <port> <schema_file...> -- <seed_file...>",
            file=sys.stderr,
        )
        return 1

    container, root_user, root_pass, app_user, app_pass, db_name, port = argv[:7]
    remainder = argv[7:]
    if "--" in remainder:
        split_idx = remainder.index("--")
        schema_args = remainder[:split_idx]
        seed_args = remainder[split_idx + 1 :]
    else:
        schema_args = remainder
        seed_args = []

    schema_files = [Path(p) for p in schema_args]
    seed_files = [Path(p) for p in seed_args]

    schema_rc, schema_applied = apply_sql(schema_files, container, root_user, root_pass, app_user, app_pass, db_name, port, nullable_db=True)
    seed_rc, seed_applied = apply_sql(seed_files, container, root_user, root_pass, app_user, app_pass, db_name, port, nullable_db=False)

    result = {
        "schema_applied": schema_applied,
        "seed_applied": seed_applied,
        "schema_rc": schema_rc,
        "seed_rc": seed_rc,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
