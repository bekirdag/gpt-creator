#!/usr/bin/env sh
# POSIX sh guard for documentation catalog resolution.

set -eu

# Modes: strict → fail hard, lazy (default) → attempt bootstrap, off → disable docs.
GC_DOCS_MODE="${GC_DOCS_MODE:-lazy}"

# Parse CLI overrides without mutating "$@"
DOC_DB=""
NEXT=""
for a in "$@"; do
  if [ -n "$NEXT" ]; then
    DOC_DB="$a"
    NEXT=""
    continue
  fi
  case "$a" in
    --doc-db=*) DOC_DB="${a#--doc-db=}" ;;
    --doc-db)   NEXT=1 ;;
    --docs=strict) GC_DOCS_MODE="strict" ;;
    --docs=lazy)   GC_DOCS_MODE="lazy" ;;
    --docs=off)    GC_DOCS_MODE="off" ;;
  esac
done

# Workspace guard should set GC_WORKSPACE_DIR; fall back to PWD for safety.
WS="${GC_WORKSPACE_DIR:-$PWD}"

# Candidate precedence: CLI → env → workspace default.
CAND="${DOC_DB:-${GC_DOCUMENTATION_DB_PATH:-}}"
[ -n "${CAND:-}" ] || CAND="$WS/.gpt-creator/docs/catalog.db"

# Replace obviously wrong backlog DBs.
case "$CAND" in
  */tasks.db) CAND="$WS/.gpt-creator/docs/catalog.db" ;;
esac

mkdir -p "$WS/.gpt-creator/docs"
LOCK="$WS/.gpt-creator/docs/catalog.lock"

is_sqlite_catalog() {
  db="$1"
  if command -v sqlite3 >/dev/null 2>&1; then
    T="$(sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('documents','sections','manifest') LIMIT 1;" 2>/dev/null || true)"
    if [ -n "$T" ]; then
      return 0
    fi
    return 1
  fi
  case "$db" in */tasks.db) return 1 ;; esac
  if [ -s "$db" ]; then
    return 0
  fi
  return 1
}

bootstrap_min_catalog() {
  db="$1"
  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi
  python3 - "$db" <<'PY' || return 1
import os
import sqlite3
import sys
import time

db = sys.argv[1]
os.makedirs(os.path.dirname(db), exist_ok=True)
con = sqlite3.connect(db)
cur = con.cursor()
cur.executescript("""
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, slug TEXT, title TEXT, path TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS sections(
  id TEXT PRIMARY KEY, doc_id TEXT, title TEXT, start_line INTEGER, end_line INTEGER
);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
""")
cur.execute(
    "INSERT OR REPLACE INTO meta(k,v) VALUES('created_at', ?)",
    (time.strftime("%Y-%m-%dT%H:%M:%SZ"),),
)
con.commit()
con.close()
PY
}

DOCS_ENABLED=1
if [ "$GC_DOCS_MODE" = "off" ]; then
  DOCS_ENABLED=0
elif [ ! -f "$CAND" ] || ! is_sqlite_catalog "$CAND"; then
  if [ "$GC_DOCS_MODE" = "strict" ]; then
    printf >&2 "gpt-creator: documentation catalog invalid or missing at '%s' (strict mode)\n" "$CAND"
    exit 65
  fi
  if ! bootstrap_min_catalog "$CAND"; then
    DOCS_ENABLED=0
  fi
fi

export GC_DOCUMENTATION_DB_PATH="$CAND"
export GC_DOCS_ENABLED="$DOCS_ENABLED"
export GC_DOCS_MODE
printf '{ "db": "%s", "enabled": %s, "mode": "%s" }\n' "$CAND" "$DOCS_ENABLED" "$GC_DOCS_MODE" > "$LOCK"
