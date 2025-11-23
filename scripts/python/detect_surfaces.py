#!/usr/bin/env python3
"""Heuristic surface detector for create-project.

Reads the staged inputs (or an explicit RFP file) and decides which app surfaces
to scaffold: api, web, admin, db, docker, mobile (future-proof). Output is a
space-separated list written to stdout.
"""

from __future__ import annotations

import argparse
import pathlib
import re
from typing import Iterable


def gather_text(paths: Iterable[pathlib.Path], limit: int = 200_000) -> str:
    chunks: list[str] = []
    for path in paths:
        try:
            data = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if not data:
            continue
        chunks.append(data[:limit])
    return "\n".join(chunks)


def detect_surfaces(text: str) -> list[str]:
    text_lower = text.lower()
    surfaces: set[str] = set()
    # Always include API; this is the core surface.
    surfaces.add("api")
    # Database is typically needed for backend scaffolds.
    surfaces.add("db")

    web_keywords = [
        "frontend",
        "web app",
        "browser",
        "spa",
        "vue",
        "react",
        "angular",
        "ui",
        "page",
    ]
    admin_keywords = [
        "admin",
        "backoffice",
        "dashboard",
        "console",
        "cms",
        "control panel",
    ]
    mobile_keywords = [
        "mobile app",
        "react native",
        "expo",
        "android",
        "ios",
    ]
    db_keywords = [
        "database",
        "mysql",
        "postgres",
        "sql",
        "schema",
        "table",
        "entity",
        "orm",
    ]

    if any(k in text_lower for k in web_keywords):
        surfaces.add("web")
    if any(k in text_lower for k in admin_keywords):
        surfaces.add("admin")
    if any(k in text_lower for k in mobile_keywords):
        surfaces.add("mobile")
    if any(k in text_lower for k in db_keywords):
        surfaces.add("db")

    # Docker is required when any containerized surface is present.
    if surfaces:
        surfaces.add("docker")

    return sorted(surfaces, key=lambda x: ["api", "db", "web", "admin", "mobile", "docker"].index(x) if x in ["api", "db", "web", "admin", "mobile", "docker"] else 99)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect which app surfaces to scaffold.")
    parser.add_argument("project_root", help="Project root directory")
    parser.add_argument("--rfp", help="Explicit RFP file to inspect", default=None)
    args = parser.parse_args()

    project_root = pathlib.Path(args.project_root)
    if not project_root.exists():
        return 1

    candidates: list[pathlib.Path] = []
    if args.rfp:
        rfp_path = pathlib.Path(args.rfp)
        if rfp_path.is_file():
            candidates.append(rfp_path)
    if not candidates:
        inputs_dir = project_root / ".gpt-creator" / "staging" / "inputs"
        if inputs_dir.is_dir():
            for pattern in ("*.md", "*.txt", "*.rst", "*.html", "*.json", "*.yaml", "*.yml"):
                candidates.extend(inputs_dir.glob(pattern))

    text = gather_text(candidates)
    surfaces = detect_surfaces(text)
    if not surfaces:
        surfaces = ["api", "db", "docker"]
    print(" ".join(surfaces))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
