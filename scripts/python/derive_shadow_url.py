#!/usr/bin/env python3
"""Derive a Prisma shadow database URL by appending a suffix to the schema path tail."""

from __future__ import annotations

import sys
from urllib.parse import urlparse, urlunparse


def derive_shadow_url(raw_url: str, suffix: str) -> str | None:
    """Return the derived URL or None if it cannot be constructed."""
    url = raw_url.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.path or parsed.path == "/":
        return None
    head, _, tail = parsed.path.rpartition("/")
    if not tail:
        return None
    new_tail = f"{tail}{suffix}"
    new_path = f"{head}/{new_tail}" if head else f"/{new_tail}"
    return urlunparse(parsed._replace(path=new_path))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return 0
    result = derive_shadow_url(argv[1], argv[2])
    if result:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
