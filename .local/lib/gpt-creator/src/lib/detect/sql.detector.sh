#!/usr/bin/env bash
# sql.detector.sh — detect SQL-related files (schema, dumps)
# Search for SQL files, commonly used in database schema or dumps.
if [[ -n "${GC_LIB_SQL_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_SQL_DETECTOR_SH=1

detect_sql() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ (sql|dump) && "$file" =~ .*\.(sql)$ ]]; then
    echo "SQL detected: $file"
  fi
}

# Usage: detect_sql "/path/to/file.sql"
