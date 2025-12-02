#!/usr/bin/env python3
"""Derive a human-friendly project title from a path."""

"$input"
import pathlib
import re
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else ''
if raw:
    path = pathlib.Path(raw)
    if path.exists():
        raw = path.name
raw = re.sub(r'[_\-]+', ' ', raw)
raw = re.sub(r'\s+', ' ', raw).strip()
if not raw:
    print("Project")
else:
    words = []
    for token in raw.split():
        if len(token) <= 3:
            words.append(token.upper())
        elif token.isupper():
            words.append(token)
        else:
            words.append(token.capitalize())
    print(' '.join(words))