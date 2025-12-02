#!/usr/bin/env python3
"""Summarise YAML reports for work-on-tasks."""

import datetime
import os
import sys


def parse_report(path):
    summary = ""
    priority = ""
    timestamp = ""
    issue_type = ""
    status = ""
    likes = 0
    comments = 0
    reporter = ""
    metadata = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("summary:") and not summary:
                    value = stripped.split(":", 1)[1].strip().strip('"')
                    summary = value
                elif stripped.startswith("priority:") and not priority:
                    priority = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("type:") and not issue_type:
                    issue_type = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("timestamp:") and not timestamp:
                    timestamp = stripped.split(":", 1)[1].strip().strip('"')
                if stripped == "metadata:":
                    metadata = True
                    continue
                if metadata:
                    if line.startswith("  "):
                        meta = line.strip()
                        if meta.startswith("timestamp:") and not timestamp:
                            timestamp = meta.split(":", 1)[1].strip().strip('"')
                        elif meta.startswith("status:") and not status:
                            status = meta.split(":", 1)[1].strip()
                        elif meta.startswith("likes:") and likes == 0:
                            try:
                                likes = int(meta.split(":", 1)[1].strip())
                            except ValueError:
                                likes = 0
                        elif meta.startswith("comments:") and comments == 0:
                            try:
                                comments = int(meta.split(":", 1)[1].strip())
                            except ValueError:
                                comments = 0
                        elif meta.startswith("reporter:") and not reporter:
                            reporter = meta.split(":", 1)[1].strip().strip('"')
                    else:
                        metadata = False
    except OSError:
        return None
    return {
        "summary": summary or "(no summary)",
        "priority": priority or "unknown",
        "timestamp": timestamp,
        "issue_type": issue_type or "unknown",
        "status": status or "open",
        "likes": likes,
        "comments": comments,
        "reporter": reporter,
    }


def main(argv):
    if len(argv) != 3:
        raise SystemExit("Usage: reports_summarize.py REPORTS_DIR MODE")

    dir_path = argv[1]
    mode = argv[2]
    entries = []

    for name in os.listdir(dir_path):
        lower = name.lower()
        if not (lower.endswith(".yml") or lower.endswith(".yaml")):
            continue
        path = os.path.join(dir_path, name)
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        meta = parse_report(path)
        if not meta:
            continue
        slug = os.path.splitext(name)[0]
        entries.append((stat.st_mtime, slug, meta))

    entries.sort(key=lambda item: item[0], reverse=True)

    printed = False
    for mtime, slug, meta in entries:
        status = meta["status"].lower()
        if mode == "backlog" and status not in ("open", "new", "todo"):
            continue
        display_time = meta["timestamp"] or datetime.datetime.utcfromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary = meta["summary"]
        priority = meta["priority"]
        issue_type = meta["issue_type"]
        popularity = meta["likes"] + meta["comments"]
        print(f"[{slug}] {display_time} {priority} ({issue_type}) status={status or 'open'} pop={popularity} (likes={meta['likes']}, comments={meta['comments']})")
        if meta["reporter"]:
            print(f"  reporter={meta['reporter']}")
        print(f"  {summary}")
        print()
        printed = True

    if mode == "backlog" and not printed:
        print("No open reports found.")


if __name__ == "__main__":
    main(sys.argv)
