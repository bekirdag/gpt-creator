#!/usr/bin/env python3
"""List report slugs filtered by reporter for work-on-tasks."""

import os
import sys


def report_matches(path, reporter_filter):
    metadata = {}
    metadata_active = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped == "metadata:":
                    metadata_active = True
                    continue
                if metadata_active:
                    if line.startswith("  ") and ":" in stripped:
                        key, value = stripped.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"')
                    else:
                        metadata_active = False
    except OSError:
        return None
    reporter = metadata.get("reporter", "")
    status = metadata.get("status", "open").lower()
    if reporter_filter and reporter.lower() != reporter_filter.lower():
        return None
    if status not in ("open", "new", "todo"):
        return None
    return True


def main(argv):
    if len(argv) != 3:
        raise SystemExit("Usage: reports_list_by_reporter.py REPORTS_DIR REPORTER")

    dir_path = argv[1]
    reporter_filter = argv[2].strip()
    entries = []

    for name in os.listdir(dir_path):
        lower = name.lower()
        if not (lower.endswith('.yml') or lower.endswith('.yaml')):
            continue
        path = os.path.join(dir_path, name)
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if report_matches(path, reporter_filter):
            slug = os.path.splitext(name)[0]
            entries.append((stat.st_mtime, slug))

    entries.sort(key=lambda item: item[0], reverse=True)
    for _, slug in entries:
        print(slug)


if __name__ == "__main__":
    main(sys.argv)
