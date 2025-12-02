#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import os
import re
import sys
from pathlib import Path

_KEEP_FIRST_ONCE = (
    re.compile(r'^##\s*Task\b', re.I),
    re.compile(r'^##\s*Output JSON schema\b', re.I),
)

_HDR_H1 = re.compile(r'^\#\s+')
_HDR_H2 = re.compile(r'^\#\#\s+')
_SUPPLEMENTAL_HDR = re.compile(r'^##\s*Supplemental Instruction Prompts\s*$', re.I)
_PROMPT_FILE_HDR = re.compile(r'^###\s+.*\.prompt\.md\s*$', re.I)


def _norm(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r'[ \t]+$', '', text, flags=re.M)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + "\n"


def _digest(block: str) -> str:
    return hashlib.sha256(re.sub(r'\s+', ' ', block).encode('utf-8')).hexdigest()[:16]


def slim_prompt_markdown(markdown: str) -> str:
    """Collapse duplicate prompt sections and normalize markdown structure."""
    lines = markdown.splitlines(True)
    out: list[str] = []
    seen: set[str] = set()
    keep_once = {pattern: False for pattern in _KEEP_FIRST_ONCE}

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        if _SUPPLEMENTAL_HDR.match(line):
            out.append(line)
            i += 1
            pointers: list[str] = []
            while i < n and not _HDR_H2.match(lines[i]):
                if _PROMPT_FILE_HDR.match(lines[i]):
                    pointers.append('- ' + lines[i].strip('# ').strip())
                i += 1
            if pointers:
                out.append("\n".join(pointers) + "\n")
            continue

        if line.startswith('#'):
            j = i + 1
            while j < n and not (_HDR_H1.match(lines[j]) or _HDR_H2.match(lines[j])):
                j += 1
            block = _norm(''.join(lines[i:j]))

            drop_block = False
            for pattern in keep_once:
                if pattern.match(line):
                    if keep_once[pattern]:
                        drop_block = True
                    else:
                        keep_once[pattern] = True
                    break
            if drop_block:
                i = j
                continue

            signature = _digest(block)
            if signature in seen:
                i = j
                continue
            seen.add(signature)
            out.append(block)
            i = j
            continue

        if line.strip():
            out.append(line)
        i += 1

    text = _norm(''.join(out))
    text = re.sub(r'(?m)^(#{1,6}\s+.+)\n\1\n', r'\1\n', text)
    return _norm(text)


def main(path_arg: str) -> int:
    path = Path(path_arg)
    try:
        raw = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return 1
    slimmed = slim_prompt_markdown(raw)
    if slimmed != raw:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with io.open(tmp, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(slimmed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: prompt_safeguard.py <prompt.md>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
