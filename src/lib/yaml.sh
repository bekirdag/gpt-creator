#!/usr/bin/env bash
# shellcheck shell=bash
# yaml.sh — utilities for handling YAML (used in gpt-creator)

if [[ -n "${GC_LIB_YAML_SH:-}" ]]; then return 0; fi
GC_LIB_YAML_SH=1

# Parse YAML (simple key-value pairs)
yaml_parse() {
  local file="$1"
  [[ -f "$file" ]] || { echo "yaml_parse: file not found: $file" >&2; return 2; }
  python3 -c "import yaml, sys; yaml.safe_load(sys.stdin)" < "$file"
}

# Write a YAML file
yaml_write() {
  local file="$1"
  shift
  # Requires: python3
  if [[ $# -gt 0 ]]; then
    echo "$@" | python3 -c "import yaml, sys; sys.stdout.write(yaml.dump(sys.stdin.read()))" > "$file"
  else
    echo "yaml_write: missing input text or file" >&2; return 2;
  fi
}
