#!/usr/bin/env python3
"""Append file content with line and char limits."""

'
import sys
from pathlib import Path

src = Path(sys.argv[1])
dest = Path(sys.argv[2])
max_lines = int(sys.argv[3])
max_chars = int(sys.argv[4])
if not src.exists():
    text = ''
else:
    text = src.read_text(encoding='utf-8', errors='ignore')
lines = text.splitlines()
truncated = False
if max_lines > 0 and len(lines) > max_lines:
    lines = lines[:max_lines]
    truncated = True
snippet = '\n'.join(lines)
if max_chars > 0 and len(snippet) > max_chars:
    snippet = snippet[:max_chars].rstrip()
    truncated = True
if snippet and not snippet.endswith('\n'):
    snippet += '\n'
with dest.open('a', encoding='utf-8') as fh:
    fh.write(snippet)
    if truncated:
        fh.write("... (truncated; see consolidated context for more)\n\n")
    elif snippet:
        fh.write('\n')
