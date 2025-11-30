#!/usr/bin/env python3
"""Normalize discovery artifacts into staging inputs and plan directories."""

from __future__ import annotations

import io
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable


def load_scan(scan_path: Path) -> dict:
    try:
        return json.loads(scan_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def copy_file(
    src: Path,
    dest: Path,
    provenance: list[dict],
    entry: dict,
    input_root: Path,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    try:
        rel_dest = dest.relative_to(input_root).as_posix()
    except ValueError:
        rel_dest = dest.as_posix()
    provenance.append(
        {
            "type": entry.get("type"),
            "source": str(src),
            "destination": rel_dest,
            "confidence": entry.get("confidence", 0),
        }
    )


def select_best_entries(artifacts: Iterable[dict], types: set[str]) -> dict[str, dict]:
    selected: dict[str, dict] = {}
    for entry in artifacts:
        kind = entry.get("type")
        if kind not in types:
            continue
        current = selected.get(kind)
        if current is None or entry.get("confidence", 0) > current.get("confidence", 0):
            selected[kind] = entry
    return selected


def main(argv: list[str]) -> None:
    if len(argv) != 4:
        raise SystemExit("Usage: normalize_inputs.py SCAN_JSON INPUT_DIR PLAN_DIR")

    scan_path = Path(argv[1])
    input_dir = Path(argv[2])
    plan_dir = Path(argv[3])

    input_dir.mkdir(parents=True, exist_ok=True)
    plan_dir.mkdir(parents=True, exist_ok=True)

    data = load_scan(scan_path)
    project_root = Path(data.get("project_root", ".")).resolve()
    artifacts = data.get("artifacts") or []

    unique_types = {"pdr", "sds", "rfp", "jira", "ui_pages", "openapi"}
    unique_entries = select_best_entries(artifacts, unique_types)

    multi_type_dirs = {
        "sql": Path("sql"),
        "mermaid": Path("mermaid"),
        "page_sample_html": Path("page_samples"),
        "page_sample_css": Path("page_samples"),
    }

    grouped: dict[str, list[dict]] = {key: [] for key in multi_type_dirs}
    for entry in artifacts:
        kind = entry.get("type")
        if kind in grouped:
            grouped[kind].append(entry)

    provenance: list[dict] = []

    name_map = {
        "pdr": Path("pdr.md"),
        "sds": Path("sds.md"),
        "rfp": Path("rfp.md"),
        "jira": Path("jira.md"),
        "ui_pages": Path("ui-pages.md"),
    }

    for kind, entry in unique_entries.items():
        path_value = entry.get("path")
        if not path_value:
            continue
        src_path = Path(path_value)
        if kind == "openapi":
            suffix = src_path.suffix.lower()
            if suffix in {".yaml", ".yml"}:
                rel_path = Path("openapi.yaml")
            elif suffix == ".json":
                rel_path = Path("openapi.json")
            else:
                rel_path = Path("openapi.src")
        else:
            rel_path = name_map.get(kind, Path(src_path.name))
        copy_file(src_path, input_dir / rel_path, provenance, entry, input_dir)

    for kind, entries in grouped.items():
        dest_root = multi_type_dirs[kind]
        for entry in entries:
            path_value = entry.get("path")
            if not path_value:
                continue
            src_path = Path(path_value)
            try:
                relative = src_path.resolve().relative_to(project_root)
            except ValueError:
                relative = Path(src_path.name)
            dest_path = input_dir / dest_root / relative
            copy_file(src_path, dest_path, provenance, entry, input_dir)

    summary = io.StringIO()
    summary.write(
        f"generated_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    )
    summary.write(f"project_root: {project_root}\n")
    summary.write("artifacts:\n")
    for entry in artifacts:
        summary.write(f"  - type: {entry.get('type')}\n")
        summary.write(f"    confidence: {entry.get('confidence', 0):.2f}\n")
        summary.write(f"    path: {entry.get('path')}\n")
    discovery_path = (input_dir.parent / "discovery.yaml").resolve()
    discovery_path.write_text(summary.getvalue(), encoding="utf-8")

    focus_targets: list[str] = []
    core_types = {"pdr", "sds", "rfp", "jira", "openapi", "ui_pages", "sql"}
    seen_focus: set[str] = set()
    for entry in provenance:
        dest = entry.get("destination")
        if not dest:
            continue
        dest_rel = Path(dest).as_posix()
        if entry.get("type") in core_types and dest_rel not in seen_focus:
            focus_targets.append(dest_rel)
            seen_focus.add(dest_rel)
    if not focus_targets:
        for entry in provenance:
            dest = entry.get("destination")
            if not dest:
                continue
            dest_rel = Path(dest).as_posix()
            if dest_rel not in seen_focus:
                focus_targets.append(dest_rel)
                seen_focus.add(dest_rel)

    prov_payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": provenance,
        "focus": focus_targets,
    }
    (plan_dir / "provenance.json").write_text(
        json.dumps(prov_payload, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main(sys.argv)
