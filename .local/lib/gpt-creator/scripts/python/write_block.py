#!/usr/bin/env python3
"""Safely write or append multi-line content to a file without heredoc quoting pitfalls."""

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path


def _load_content_from_json(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        if "text" in parsed and isinstance(parsed["text"], str):
            return parsed["text"]
        if "lines" in parsed and isinstance(parsed["lines"], list) and all(isinstance(line, str) for line in parsed["lines"]):
            return "\n".join(parsed["lines"])
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return "\n".join(parsed)
    raise ValueError("JSON payload must be a string, a {\"text\": str} object, or a list of strings.")


def _resolve_content(args: argparse.Namespace) -> str:
    sources = [args.content_json is not None, args.content_b64 is not None, args.content_file is not None]
    if sum(1 for flag in sources if flag) != 1:
        raise ValueError("Provide exactly one of --content-json, --content-b64, or --content-file.")
    if args.content_json is not None:
        return _load_content_from_json(args.content_json)
    if args.content_b64 is not None:
        try:
            decoded = base64.b64decode(args.content_b64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"Invalid base64 payload: {exc}") from exc
        return decoded.decode(args.encoding)
    if args.content_file is not None:
        src = Path(args.content_file)
        if not src.exists():
            raise ValueError(f"Content file '{src}' does not exist.")
        return src.read_text(encoding=args.encoding)
    raise AssertionError("Unreachable content resolution path.")


def _write_content(target: Path, content: str, *, mode: str, encoding: str, ensure_trailing_newline: bool) -> bool:
    if ensure_trailing_newline and content and not content.endswith("\n"):
        content = content + "\n"
    if mode == "append":
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding=encoding) as handle:
            handle.write(content)
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        current = target.read_text(encoding=encoding)
        if current == content:
            return False
    target.write_text(content, encoding=encoding)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write or append safely encoded content to a file.")
    parser.add_argument("--path", required=True, help="Destination file path.")
    parser.add_argument("--mode", choices=("overwrite", "append"), default="overwrite", help="Overwrite (default) or append to the destination.")
    parser.add_argument("--encoding", default="utf-8", help="File encoding; defaults to utf-8.")
    parser.add_argument("--ensure-trailing-newline", action="store_true", help="Ensure the written content ends with a newline when overwriting.")
    parser.add_argument("--content-json", help="JSON string payload (string, {\"text\": str}, or list of strings).")
    parser.add_argument("--content-b64", help="Base64-encoded payload.")
    parser.add_argument("--content-file", help="Path to a file whose contents should be written verbatim.")
    args = parser.parse_args(argv)

    try:
        content = _resolve_content(args)
    except ValueError as exc:
        print(f"write_block.py: {exc}", file=sys.stderr)
        return 2

    target = Path(args.path)
    try:
        changed = _write_content(target, content, mode=args.mode, encoding=args.encoding, ensure_trailing_newline=args.ensure_trailing_newline)
    except Exception as exc:  # pragma: no cover
        print(f"write_block.py: failed to write '{target}': {exc}", file=sys.stderr)
        return 1

    if changed:
        print(f"write_block.py: wrote {len(content)} byte(s) to {target}")
    else:
        print(f"write_block.py: no changes written to {target} (content already up-to-date)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
