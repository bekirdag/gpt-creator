#!/usr/bin/env python3
"""
Prune docker-compose.yml services to a provided allowlist.

Usage: prune_compose_services.py /path/to/docker-compose.yml service1 service2 ...
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_service_header(line: str) -> str | None:
    if line.startswith("  ") and not line.startswith("    "):
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith("#"):
            return stripped[:-1]
    return None


def prune_compose(compose_path: Path, keep: set[str]) -> None:
    lines = compose_path.read_text().splitlines()
    out_lines: list[str] = []
    section = "root"
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith("services:"):
            section = "services"
            out_lines.append(line)
            i += 1
            continue

        if section == "services":
            name = is_service_header(line)
            if name:
                if name in keep:
                    out_lines.append(line)
                    i += 1
                    while i < len(lines):
                        nxt = lines[i]
                        maybe_header = is_service_header(nxt)
                        if maybe_header:
                            break
                        out_lines.append(nxt)
                        i += 1
                    continue
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    maybe_header = is_service_header(nxt)
                    if maybe_header:
                        break
                    i += 1
                continue

        out_lines.append(line)
        i += 1

    compose_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: prune_compose_services.py <compose.yml> <service> [service...]", file=sys.stderr)
        return 1
    compose_path = Path(argv[0])
    if not compose_path.is_file():
        print(f"Compose file not found: {compose_path}", file=sys.stderr)
        return 1
    keep = set(argv[1:])
    if not keep:
        print("No services specified to keep; nothing to do.", file=sys.stderr)
        return 1
    prune_compose(compose_path, keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
