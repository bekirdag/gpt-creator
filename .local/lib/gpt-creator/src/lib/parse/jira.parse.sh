#!/usr/bin/env bash
# jira.parse.sh — parse Jira task markdown and extract task metadata (title, status, description)

if [[ -n "${GC_LIB_JIRA_PARSE_SH:-}" ]]; then return 0; fi
GC_LIB_JIRA_PARSE_SH=1

# Parse Jira tasks from markdown and extract relevant metadata (task ID, title, description)
parse_jira() {
  local file="$1"
  [[ -f "$file" ]] || { echo "parse_jira: file not found: $file" >&2; return 2; }
  # Extract task title, status, and description from Jira markdown (default format)
  awk '/^- \[ \] / { print "Task: " $0 }' "$file" | sed 's/^- \[ \] //g' |
    awk -F'|' '{print "Title: " $1; print "Status: " $2;}'
}

# Usage: parse_jira "tasks.md"
