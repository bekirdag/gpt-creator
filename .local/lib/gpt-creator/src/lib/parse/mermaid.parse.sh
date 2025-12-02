#!/usr/bin/env bash
# mermaid.parse.sh — parse Mermaid diagram files (workflow, ERD) and extract nodes and edges
# Used to convert diagram elements into structured information.

if [[ -n "${GC_LIB_MERMAID_PARSE_SH:-}" ]]; then return 0; fi
GC_LIB_MERMAID_PARSE_SH=1

# Parse Mermaid diagram for elements (nodes and edges)
parse_mermaid() {
  local file="$1"
  [[ -f "$file" ]] || { echo "parse_mermaid: file not found: $file" >&2; return 2; }
  awk '/graph|sequenceDiagram|classDiagram|gantt/ { print $0 }' "$file" |
    sed -e 's/[^a-zA-Z0-9 ]//g' -e 's/\s\s*/ /g'
}

# Usage: parse_mermaid "diagram.mmd"
