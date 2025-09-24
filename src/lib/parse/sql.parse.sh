#!/usr/bin/env bash
# sql.parse.sh — parse SQL dump or schema file to identify tables and columns
# Extracts table definitions and column names.

if [[ -n "${GC_LIB_SQL_PARSE_SH:-}" ]]; then return 0; fi
GC_LIB_SQL_PARSE_SH=1

# Parse SQL dump (tables and columns)
parse_sql() {
  local file="$1"
  [[ -f "$file" ]] || { echo "parse_sql: file not found: $file" >&2; return 2; }
  # Extract table and column definitions
  awk '/CREATE TABLE/,/);/ { if ($0 ~ /CREATE TABLE/ || $0 ~ /\(/) print $0; }' "$file" |
    sed -e 's/`//g' -e 's/CREATE TABLE//g' -e 's/(\s*//g' -e 's/\s*);//g' -e 's/,\s*$//g' -e 's/\s\s*/ /g'
}

# Usage: parse_sql "schema.sql"
