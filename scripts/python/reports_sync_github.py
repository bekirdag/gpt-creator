#!/usr/bin/env python3
"""Create GitHub issues for automated gpt-creator reports."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(1)
    repo, token = sys.argv[1:3]

    summary = (os.environ.get("GC_REPORT_SUMMARY") or "").strip()
    definition = (os.environ.get("GC_REPORT_DEFINITION") or "").strip()
    priority = (os.environ.get("GC_REPORT_PRIORITY") or "P2-medium").strip() or "P2-medium"
    kind = (os.environ.get("GC_REPORT_KIND") or "generic").strip() or "generic"
    report_file = os.environ.get("GC_REPORT_FILE", "")
    invocation = os.environ.get("GC_REPORT_COMMAND", "")
    exit_code = os.environ.get("GC_REPORT_EXIT", "")
    last_cmd = os.environ.get("GC_REPORT_LAST_CMD", "")
    project_root = os.environ.get("GC_REPORT_PROJECT") or os.getcwd()
    workdir = os.environ.get("GC_REPORT_WORKDIR") or os.getcwd()
    reporter = os.environ.get("GC_REPORTER", "")
    version = (os.environ.get("GC_REPORT_VERSION") or "").strip()
    binary_path = (os.environ.get("GC_REPORT_BINARY") or "").strip()

    title = summary or f"{kind.capitalize()} report"
    title = title.strip()[:120] or "Automated crash report"

    body_lines = []
    if definition:
        body_lines.append(definition)
    else:
        body_lines.append("(no additional details provided)")
    body_lines.extend(["", "---", ""])

    binary_hash = ""
    if binary_path:
        try:
            path = Path(binary_path)
            if path.is_file():
                binary_hash = sha256_file(path)
        except (OSError, ValueError):
            binary_hash = ""

    signature = ""
    if version or binary_hash:
        payload_source = f"{version}:{binary_hash}".encode("utf-8")
        signature = hashlib.sha256(payload_source).hexdigest()

    metadata = [
        ("Priority", priority),
        ("Report Type", kind),
        ("Reporter", reporter),
        ("Invocation", invocation),
        ("Exit Code", exit_code),
        ("Last Command", last_cmd),
        ("Project Root", project_root),
        ("Working Directory", workdir),
        ("Report File", report_file),
        ("CLI Version", version),
        ("CLI Binary SHA256", binary_hash),
        ("CLI Signature", signature),
    ]

    for label, value in metadata:
        if value:
            body_lines.append(f"- **{label}**: {value}")

    watermark = ""
    if signature:
        watermark = f"{version or 'unknown'}:{signature}"
    elif version:
        watermark = f"{version}:unsigned"
    if watermark:
        body_lines.extend(["", f"<!-- gpt-creator:{watermark} -->"])

    labels = [
        "auto-report",
        f"kind:{kind}",
        f"priority:{priority}",
    ]
    if version:
        labels.append(f"cli-version:{version.replace(' ', '_')}")

    payload = {
        "title": title,
        "body": "\n".join(body_lines),
        "labels": labels,
    }

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        message = err.read().decode("utf-8", "ignore")
        print(f"HTTP {err.code}: {message}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"GitHub issue request failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

    html_url = data.get("html_url", "")
    number = data.get("number")
    print(html_url)
    print(number if number is not None else "")


if __name__ == "__main__":
    main()

