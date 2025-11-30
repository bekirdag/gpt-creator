#!/usr/bin/env python3
"""Mutate a report YAML file's metadata section."""

from __future__ import annotations

import sys
from pathlib import Path


def update_metadata(path: Path, key: str, value: str) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except FileNotFoundError as exc:
        raise SystemExit(f"report file not found: {path}") from exc

    metadata_found = False
    metadata_active = False
    inserted = False
    result: list[str] = []

    for line in lines:
        if line.strip() == "metadata:":
            metadata_found = True
            metadata_active = True
            result.append(line)
            continue
        if metadata_active:
            if line.startswith("  "):
                stripped = line.strip()
                if ":" in stripped:
                    current_key = stripped.split(":", 1)[0].strip()
                    if current_key == key:
                        result.append(f"  {key}: {value}".rstrip())
                        inserted = True
                        continue
            else:
                if not inserted:
                    result.append(f"  {key}: {value}".rstrip())
                    inserted = True
                metadata_active = False
        result.append(line)

    if metadata_active and not inserted:
        result.append(f"  {key}: {value}".rstrip())
        inserted = True

    if not metadata_found:
        result.append("metadata:")
        result.append(f"  {key}: {value}".rstrip())

    path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: reports_set_metadata_field.py <file> <key> <value>")
    report_path = Path(sys.argv[1])
    key = sys.argv[2]
    value = sys.argv[3]
    update_metadata(report_path, key, value)


if __name__ == "__main__":
    main()

