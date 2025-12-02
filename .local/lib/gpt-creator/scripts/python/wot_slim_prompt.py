#!/usr/bin/env python3
import hashlib
import io
import os
import re
import sys
from pathlib import Path

KEEP_FIRST_ONCE = {
    re.compile(r'^##\s*Task\b', re.I),
    re.compile(r'^##\s*Output JSON schema\b', re.I),
}

SUPPLEMENTAL_HDR = re.compile(r'^##\s*Supplemental Instruction Prompts\s*$', re.I)
PROMPT_FILE_HDR = re.compile(r'^###\s+.*\.prompt\.md\s*$', re.I)


def norm(s: str) -> str:
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    s = re.sub(r'[ \t]+$', '', s, flags=re.M)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip() + '\n'


def digest(s: str) -> str:
    return hashlib.sha256(re.sub(r'\s+', ' ', s).encode()).hexdigest()[:16]


def slim_sections(lines: list[str]) -> str:
    out: list[str] = []
    seen_digests: set[str] = set()
    i = 0
    n = len(lines)
    kept_once = {pat: False for pat in KEEP_FIRST_ONCE}

    while i < n:
        line = lines[i]
        if SUPPLEMENTAL_HDR.match(line):
            out.append(line)
            i += 1
            pointers: list[str] = []
            while i < n and not re.match(r'^##\s+', lines[i]):
                if PROMPT_FILE_HDR.match(lines[i]):
                    pointers.append('- ' + lines[i].strip('# ').strip())
                i += 1
            if pointers:
                out.append('\n'.join(pointers) + '\n')
            continue

        if line.startswith('#'):
            j = i + 1
            while j < n and not (lines[j].startswith('# ') or lines[j].startswith('## ')):
                j += 1
            block = norm(''.join(lines[i:j]))
            keep_once_hit = False
            for pat in kept_once:
                if pat.match(line):
                    if kept_once[pat]:
                        keep_once_hit = True
                    else:
                        kept_once[pat] = True
                    break
            if keep_once_hit:
                i = j
                continue
            sig = digest(block)
            if sig in seen_digests:
                i = j
                continue
            seen_digests.add(sig)
            out.append(block)
            i = j
            continue

        if line.strip():
            out.append(line)
        i += 1

    text = norm(''.join(out))
    text = re.sub(r'(?m)^(#{1,6}\s+.*)\n\1\n', r'\1\n', text)
    return norm(text)


def main(path_arg: str) -> int:
    path = Path(path_arg)
    try:
        raw = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return 1
    slimmed = slim_sections(raw.splitlines(True))
    if slimmed != raw:
        tmp = path.with_suffix(path.suffix + '.tmp')
        with io.open(tmp, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(slimmed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage: wot_slim_prompt.py <prompt.md>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
