#!/usr/bin/env bash
# shellcheck shell=bash
# json.sh — utilities for handling JSON

if [[ -n "${GC_LIB_JSON_SH:-}" ]]; then return 0; fi
GC_LIB_JSON_SH=1

# Parse JSON
json_parse() {
  local file="$1"
  [[ -f "$file" ]] || { echo "json_parse: file not found: $file" >&2; return 2; }
  python3 -c "import json, sys; json.load(sys.stdin)" < "$file"
}

# Write a JSON file
json_write() {
  local file="$1"
  shift
  # Requires: python3
  if [[ $# -gt 0 ]]; then
    echo "$@" | python3 -c "import json, sys; sys.stdout.write(json.dumps(sys.stdin.read(), indent=4))" > "$file"
  else
    echo "json_write: missing input text or file" >&2; return 2;
  fi
}
