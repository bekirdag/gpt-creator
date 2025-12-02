#!/usr/bin/env python3
"""Render documentation placeholder templates with safe escaping."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from string import Template


def build_context(args: argparse.Namespace) -> dict[str, str]:
    summary_single_line = " ".join(args.summary.splitlines()).strip() or args.summary
    timestamp_compact = f"{args.timestamp.replace('-', '')}T000000Z"

    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer)
    csv_writer.writerow(
        [
            args.owner,
            args.timestamp,
            args.summary,
            "Replace this placeholder with final content",
        ]
    )
    csv_row = csv_buffer.getvalue().strip("\r\n")

    return {
        "FORMAT": args.format,
        "OWNER": args.owner,
        "TIMESTAMP": args.timestamp,
        "SUMMARY": args.summary,
        "SUMMARY_SINGLE_LINE": summary_single_line,
        "TIMESTAMP_COMPACT": timestamp_compact,
        "PATH": args.path,
        "BASE_NAME": args.base_name,
        "CSV_ROW": csv_row,
        "OWNER_JSON": json.dumps(args.owner),
        "TIMESTAMP_JSON": json.dumps(args.timestamp),
        "SUMMARY_JSON": json.dumps(args.summary),
        "PATH_JSON": json.dumps(args.path),
    }


def render_template(template_path: Path, context: dict[str, str]) -> str:
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.safe_substitute(context)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, help="Path to template file")
    parser.add_argument("--format", required=True, help="Template format label")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--base-name", required=True)
    parser.add_argument("--output", help="Optional output path (defaults to stdout)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    template_path = Path(args.template)
    if not template_path.is_file():
        raise SystemExit(f"Template not found: {template_path}")

    context = build_context(args)
    rendered = render_template(template_path, context)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
