#!/usr/bin/env python3
"""Filter repeated boilerplate paragraphs from context."""

'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
dest = Path(sys.argv[2])
cache_path = Path(sys.argv[3])

if not source.exists():
    dest.write_text('', encoding='utf-8')
    raise SystemExit(0)

try:
    text = source.read_text(encoding='utf-8', errors='ignore')
except Exception:
    dest.write_text('', encoding='utf-8')
    raise SystemExit(0)

seen = set()
if cache_path.exists():
    try:
        seen = {
            line.strip()
            for line in cache_path.read_text(encoding='utf-8', errors='ignore').splitlines()
            if line.strip()
        }
    except Exception:
        seen = set()

def iter_paragraphs(blob: str):
    lines = []
    for raw_line in blob.splitlines():
        if raw_line.strip():
            lines.append(raw_line)
        else:
            if lines:
                yield lines
                lines = []
    if lines:
        yield lines

def signature(lines):
    if not lines:
        return None
    first_line = lines[0].lstrip()
    if first_line.startswith('#'):
        return None
    normalized = ' '.join(part.strip().lower() for part in lines if part.strip())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    if len(normalized) < 60:
        return None
    return normalized[:480]

paragraphs = list(iter_paragraphs(text))
filtered = []
added_signatures = set()

for lines in paragraphs:
    sig = signature(lines)
    if sig and sig in seen:
        continue
    filtered.append('\n'.join(lines).strip())
    if sig:
        seen.add(sig)
        added_signatures.add(sig)

if not filtered and paragraphs:
    fallback = '\n'.join(paragraphs[0]).strip()
    if fallback:
        filtered.append(fallback)
        sig = signature(paragraphs[0])
        if sig:
            seen.add(sig)
            added_signatures.add(sig)

output = '\n\n'.join(filtered).strip()
if output:
    output += '\n'
dest.write_text(output, encoding='utf-8')

if seen:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text('\n'.join(sorted(seen)) + '\n', encoding='utf-8')
