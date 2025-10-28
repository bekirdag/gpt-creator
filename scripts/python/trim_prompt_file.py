#!/usr/bin/env python3
"""Trim prompt files to stay within approximate token budgets."""

from __future__ import annotations

import sys
from pathlib import Path

MAX_TOKENS = 60000
RESERVED_FOR_REPLY = 4000
DIGEST_KEEP_CHARS = 2000
APPROX_CHARS_PER_TOKEN = 4
NOTICE_BUDGET = "\n\n[prompt trimmed automatically to respect token budget]\n"
NOTICE_MODEL = "\n\n[prompt trimmed automatically to respect model budget]\n"
NOTICE_DIGEST = "\n\n[shared-context trimmed automatically to respect token budget]"


def estimate_tokens(text: str) -> int:
    return (len(text) + APPROX_CHARS_PER_TOKEN - 1) // APPROX_CHARS_PER_TOKEN


def clamp_text(text: str, char_limit: int, notice: str) -> tuple[str, bool]:
    if len(text) <= char_limit:
        return text, False
    trimmed = text[:char_limit].rstrip() + notice
    return trimmed, True


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(1)

    path = Path(sys.argv[1])
    hard_cap = int(sys.argv[2])

    if not path.exists():
        raise SystemExit(0)
    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    modified = False

    if hard_cap <= 0:
        hard_cap = MAX_TOKENS - RESERVED_FOR_REPLY

    hard_cap_tokens = min(hard_cap, MAX_TOKENS - RESERVED_FOR_REPLY)
    if hard_cap_tokens <= 0:
        hard_cap_tokens = MAX_TOKENS - RESERVED_FOR_REPLY

    char_limit = hard_cap_tokens * APPROX_CHARS_PER_TOKEN
    if estimate_tokens(text) + RESERVED_FOR_REPLY <= MAX_TOKENS and len(text) <= char_limit:
        raise SystemExit(0)

    digest_marker = "## Shared Context Digest"
    if digest_marker in text:
        head, tail = text.split(digest_marker, 1)
        digest_end = tail.find("\n## ")
        if digest_end == -1:
            digest_end = len(tail)
        digest_body = tail[:digest_end]
        remainder = tail[digest_end:]
        if len(digest_body) > DIGEST_KEEP_CHARS:
            digest_body = digest_body[:DIGEST_KEEP_CHARS].rstrip()
            separator = "" if not remainder or remainder.startswith("\n") else "\n"
            tail = digest_body + NOTICE_DIGEST + separator + remainder
            text = head + digest_marker + "\n" + tail
            modified = True

        if estimate_tokens(text) + RESERVED_FOR_REPLY <= MAX_TOKENS and len(text) <= char_limit:
            if modified and text != original:
                path.write_text(text, encoding="utf-8")
                print("[prompt-trim] shared context digest trimmed for token budget")
            raise SystemExit(0)

    max_char_budget = min(char_limit, (MAX_TOKENS - RESERVED_FOR_REPLY) * APPROX_CHARS_PER_TOKEN)
    text, changed = clamp_text(text, max_char_budget, NOTICE_BUDGET)
    modified = modified or changed

    if estimate_tokens(text) + RESERVED_FOR_REPLY > MAX_TOKENS:
        allowed_chars = (MAX_TOKENS - RESERVED_FOR_REPLY) * APPROX_CHARS_PER_TOKEN
        text, changed = clamp_text(text, allowed_chars, NOTICE_MODEL)
        modified = modified or changed

    if modified and text != original:
        path.write_text(text, encoding="utf-8")
        print(f"[prompt-trim] prompt trimmed to stay within token budget (<= {hard_cap_tokens} tokens)")


if __name__ == "__main__":
    main()

