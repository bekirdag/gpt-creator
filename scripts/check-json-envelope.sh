#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: check-json-envelope.sh <file>" >&2
  exit 2
fi

file="$1"
if [[ ! -f "$file" ]]; then
  echo "check-json-envelope: file not found: $file" >&2
  exit 1
fi

if LC_ALL=C grep -n -E '[^\x00-\x7F]' "$file" >/dev/null; then
  echo "[warn] non-ASCII characters detected in ${file}" >&2
fi

first_nonempty_line=$(grep -n '\S' "$file" | head -n 1 | cut -d: -f1 || true)
if [[ -n "$first_nonempty_line" ]]; then
  line_content=$(sed -n "${first_nonempty_line}p" "$file")
  if [[ "$line_content" != '{'* ]]; then
    echo "[warn] leading prose detected before JSON object in ${file}" >&2
  fi
fi
