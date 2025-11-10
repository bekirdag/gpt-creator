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

# Primary catalog lives in the staged tasks DB; fall back to the legacy stub if
# the runtime file is missing. This keeps docs/SDS references consistent across
# commands even before `work-on-tasks` refreshes the catalog explicitly.
RUNTIME_DB="$WS/.gpt-creator/staging/plan/tasks/tasks.db"
STUB_DB="$WS/.gpt-creator/docs/catalog.db"

# Candidate precedence: CLI → env → runtime DB → stub file.
CAND="${DOC_DB:-${GC_DOCUMENTATION_DB_PATH:-}}"
if [ -z "${CAND:-}" ]; then
  if [ -f "$RUNTIME_DB" ]; then
    CAND="$RUNTIME_DB"
  else
    CAND="$STUB_DB"
  fi
fi

mkdir -p "$(dirname "$STUB_DB")"
mkdir -p "$(dirname "$RUNTIME_DB")"
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
  helper_path=""
  if command -v gc_clone_python_tool >/dev/null 2>&1; then
    helper_path="$(gc_clone_python_tool "bootstrap_min_catalog.py" "$WS")" || return 1
  else
    helper_root="${CLI_ROOT:-}"
    if [ -z "$helper_root" ]; then
      helper_root="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || helper_root=""
    fi
    helper_path="${helper_root}/scripts/python/bootstrap_min_catalog.py"
    if [ ! -f "$helper_path" ]; then
      printf >&2 "gpt-creator: bootstrap helper missing at '%s'\n" "$helper_path"
      return 1
    fi
  fi
  python3 "$helper_path" "$db"
}

# If the stub is selected but the staged tasks DB already exists (and contains
# the documentation tables), prefer the staged DB so downstream helpers point at
# the authoritative catalog automatically.
if [ "$CAND" = "$STUB_DB" ] && [ -f "$RUNTIME_DB" ]; then
  if is_sqlite_catalog "$RUNTIME_DB"; then
    CAND="$RUNTIME_DB"
  fi
fi

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
