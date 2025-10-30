#!/usr/bin/env python3
"""Generate plan artifacts (routes/entities/tasks/PLAN_TODO) from discovery inputs."""

import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List


def load_openapi(openapi_path: Path):
    routes: List[Dict[str, str]] = []
    schemas: List[str] = []
    if not openapi_path or not openapi_path.is_file():
        return routes, schemas

    text = openapi_path.read_text(encoding="utf-8", errors="replace")
    data = None
    openapi_loaded = False
    if openapi_path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            openapi_loaded = True
        except Exception:
            data = None
    else:
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)  # type: ignore
            openapi_loaded = isinstance(data, dict)
        except Exception:
            data = None

    if openapi_loaded and isinstance(data, dict):
        paths = data.get("paths") or {}
        if isinstance(paths, dict):
            for path, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                for method, body in methods.items():
                    if not isinstance(body, dict):
                        continue
                    routes.append(
                        {
                            "method": str(method).upper(),
                            "path": path,
                            "summary": body.get("summary") or "",
                        }
                    )
        components = data.get("components") or {}
        schemas = list((components.get("schemas") or {}).keys())
        return routes, schemas

    # Fallback parsing
    routes = []
    schemas = []
    current_path = None
    for line in text.splitlines():
        if re.match(r"^\s*/[^\s]+:\s*$", line):
            current_path = line.strip().rstrip(":")
            continue
        if current_path:
            match = re.match(
                r"^\s{2,}(get|post|put|patch|delete|options|head):\s*$", line, re.I
            )
            if match:
                routes.append(
                    {
                        "method": match.group(1).upper(),
                        "path": current_path,
                        "summary": "",
                    }
                )
                continue
            if re.match(r"^\S", line):
                current_path = None

    in_components = False
    in_schemas = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^components:\s*$", stripped):
            in_components = True
            in_schemas = False
            continue
        if in_components and re.match(r"^schemas:\s*$", stripped):
            in_schemas = True
            continue
        indent = len(line) - len(line.lstrip(" "))
        if in_schemas:
            if indent <= 2 and not stripped.startswith("#") and not stripped.startswith(
                "schemas:"
            ):
                in_schemas = False
                continue
            if indent == 4 and re.match(r"^[A-Za-z0-9_.-]+:\s*$", stripped):
                name = stripped.split(":", 1)[0]
                schemas.append(name)

    return routes, schemas


def load_sql_tables(sql_dir: Path) -> List[str]:
    tables: List[str] = []
    if not sql_dir or not sql_dir.is_dir():
        return tables
    for sql_file in sql_dir.rglob("*.sql"):
        try:
            text = sql_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in re.finditer(
            r"CREATE\s+TABLE\s+`?([A-Za-z0-9_]+)`?", text, flags=re.IGNORECASE
        ):
            tables.append(match.group(1))
    return tables


def write_routes_file(path: Path, routes: List[Dict[str, str]]) -> None:
    lines = ["# Routes", ""]
    if routes:
        for item in sorted(routes, key=lambda r: (r["path"], r["method"])):
            summary = f" — {item['summary']}" if item.get("summary") else ""
            lines.append(f"- `{item['method']} {item['path']}`{summary}")
    else:
        lines.append("No routes detected — ensure openapi.yaml is present in staging/inputs.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_entities_file(
    path: Path, schemas: List[str], sql_tables: List[str], only_api: List[str], only_sql: List[str]
) -> None:
    lines = ["# Entities", ""]
    lines.append("## OpenAPI Schemas")
    if schemas:
        for name in sorted(schemas):
            lines.append(f"- {name}")
    else:
        lines.append("- (none found)")
    lines.append("")
    lines.append("## SQL Tables")
    if sql_tables:
        for name in sorted(sql_tables):
            lines.append(f"- {name}")
    else:
        lines.append("- (none found)")
    lines.append("")
    lines.append("## Detected deltas")
    if only_api:
        lines.append("- Only in OpenAPI: " + ", ".join(only_api))
    if only_sql:
        lines.append("- Only in SQL: " + ", ".join(only_sql))
    if not only_api and not only_sql:
        lines.append("- None (schemas and tables aligned on name)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tasks_file(path: Path, only_api: List[str], only_sql: List[str]) -> None:
    tasks = []
    if only_api:
        tasks.append(
            {
                "id": "align-openapi-sql",
                "title": "Align OpenAPI schemas with SQL tables",
                "details": f"Create tables or update schemas for: {', '.join(only_api)}",
            }
        )
    if only_sql:
        tasks.append(
            {
                "id": "document-sql-gap",
                "title": "Document SQL tables missing from OpenAPI",
                "details": f"Expose or document SQL tables not covered by API: {', '.join(only_sql)}",
            }
        )
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks": tasks,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_plan_todo(path: Path) -> None:
    lines = [
        "# Build Plan",
        "",
        "- Validate discovery outputs under `staging/inputs`.",
        "- Review `routes.md` & `entities.md` for coverage and deltas.",
        "- Implement generation steps for API, DB, Web, Admin, Docker.",
        "- Run `gpt-creator generate all --project <path>` if not already executed.",
        "- Bring the stack up with `gpt-creator run up` and smoke test.",
        "- Execute `gpt-creator verify all` to satisfy acceptance & NFR gates.",
        "- Iterate on Jira tasks using `gpt-creator iterate` until checks pass.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        raise SystemExit(
            "Usage: generate_plan_artifacts.py OPENAPI_PATH SQL_DIR PLAN_DIR"
        )

    openapi_arg = argv[1]
    sql_dir_arg = argv[2]
    plan_dir = Path(argv[3])
    plan_dir.mkdir(parents=True, exist_ok=True)

    openapi_path = Path(openapi_arg) if openapi_arg else None
    sql_dir_path = Path(sql_dir_arg) if sql_dir_arg else None

    routes, schemas = load_openapi(openapi_path) if openapi_path else ([], [])
    sql_tables = load_sql_tables(sql_dir_path) if sql_dir_path else []

    schema_set = {s.lower() for s in schemas}
    table_set = {t.lower() for t in sql_tables}
    only_in_openapi = sorted(schema_set - table_set)
    only_in_sql = sorted(table_set - schema_set)

    write_routes_file(plan_dir / "routes.md", routes)
    write_entities_file(
        plan_dir / "entities.md",
        schemas,
        sql_tables,
        only_in_openapi,
        only_in_sql,
    )
    write_tasks_file(plan_dir / "tasks.json", only_in_openapi, only_in_sql)
    write_plan_todo(plan_dir / "PLAN_TODO.md")


if __name__ == "__main__":
    main(sys.argv)
