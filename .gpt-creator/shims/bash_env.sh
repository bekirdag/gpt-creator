#!/usr/bin/env bash
# .gpt-creator/shims/bash_env.sh
# Loaded into every `bash -lc` via BASH_ENV
# - Auto-refreshes `gpt-creator show-file` when a cached banner is detected
# - De-duplicates repeated scans (`rg`, `find`, and `gpt-creator show-file`) while the repo state is unchanged
# - Cross-platform (Linux/macOS); safe to source multiple times

set -Eeuo pipefail
shopt -s expand_aliases

# ------------------------ Config (with safe defaults) -------------------------
: "${GC_DISABLE_SCAN_DEDUP:=0}"              # 1 to disable all scan de-dup
: "${GC_SCAN_DEDUP_TTL:=120}"                # seconds to cache scan outputs
: "${GC_SCAN_CACHE_DIR:=$PWD/.gpt-creator/tmp/scan-cache}"
# Paths we consider "scan targets" (space-separated)
: "${GC_SCAN_DEDUP_TARGETS:=.gpt-creator/staging .gpt-creator/plan .gpt-creator/work docs}"

mkdir -p "$GC_SCAN_CACHE_DIR" 2>/dev/null || true

# --------------------------- Runtime path helpers -----------------------------
__gc_prepend_path() {
  local dir="${1:-}"
  if [[ -n "$dir" && -d "$dir" ]]; then
    case ":${PATH:-}:" in
      *":$dir:"*) ;;  # already present
      *) PATH="$dir:${PATH:-}"; export PATH ;;
    esac
  fi
}

if [[ -n "${GC_NODE_RUNTIME:-}" ]]; then
  __gc_prepend_path "${GC_NODE_RUNTIME}/bin"
fi

if [[ -n "${PNPM_HOME:-}" ]]; then
  __gc_prepend_path "${PNPM_HOME}"
elif [[ -n "${GC_NODE_RUNTIME:-}" ]]; then
  __gc_prepend_path "${GC_NODE_RUNTIME}/pnpm-home"
fi

if [[ -n "${NPM_CONFIG_PREFIX:-}" ]]; then
  __gc_prepend_path "${NPM_CONFIG_PREFIX}/bin"
elif [[ -n "${npm_config_prefix:-}" ]]; then
  __gc_prepend_path "${npm_config_prefix}/bin"
fi

# --------------------------- Small utility helpers ----------------------------
__gc_cmd_exists() { command -v "$1" >/dev/null 2>&1; }

__gc_hash() {
  if __gc_cmd_exists sha1sum; then sha1sum | awk '{print $1}'
  elif __gc_cmd_exists shasum; then shasum -a 1 | awk '{print $1}'
  else openssl sha1 2>/dev/null | awk '{print $2}'; fi
}

__gc_mtime() {  # prints mtime (epoch) for a file/dir or 0 if missing
  { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; } || echo 0
}

__gc_repo_sig() {
  # A cheap signature of the current working state; if this changes, we invalidate cache.
  if __gc_cmd_exists git && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    {
      git rev-parse HEAD 2>/dev/null || echo "no-head"
      git diff --shortstat 2>/dev/null || true
      git diff --name-only 2>/dev/null | head -n 200 || true
      git status --porcelain 2>/dev/null || true
    } | __gc_hash
  else
    # Not a git repo; use mtimes of target dirs (lightweight and good enough with TTL).
    local acc=""
    for p in $GC_SCAN_DEDUP_TARGETS; do
      acc+="$p:$(__gc_mtime "$p") "
    done
    printf "%s" "$acc" | __gc_hash
  fi
}

__gc_should_dedup() {
  # Only de-dup scans that touch declared targets
  local s="$*"
  for t in $GC_SCAN_DEDUP_TARGETS; do
    [[ "$s" == *"$t"* ]] && return 0
  done
  return 1
}

__gc_atomic_write() { # atomic write: tmp + mv
  local file="$1"; shift
  local tmp
  tmp="$(mktemp "${file}.XXXXXX")"
  # shellcheck disable=SC2059
  printf "%s" "$*" >"$tmp"
  mv -f "$tmp" "$file"
}

# --------------------------- De-dup execution core ----------------------------
__gc_dedup_exec() {
  # Usage: __gc_dedup_exec <real-cmd> <args...>
  local real="$1"; shift
  if [[ "$GC_DISABLE_SCAN_DEDUP" == "1" ]] || ! __gc_should_dedup "$real $*"; then
    command "$real" "$@"
    return $?
  fi

  local sig key hash of rcfile now rc
  sig="$(__gc_repo_sig)"
  key="$PWD|$real|$*|$sig"
  hash="$(printf '%s' "$key" | __gc_hash)"
  of="$GC_SCAN_CACHE_DIR/$hash.out"
  rcfile="$GC_SCAN_CACHE_DIR/$hash.rc"
  now="$(date +%s)"

  # Cache hit within TTL → replay
  if [[ -f "$of" ]]; then
    local age
    age=$(( now - $(__gc_mtime "$of") ))
    if (( age < GC_SCAN_DEDUP_TTL )); then
      # stdout
      cat "$of"
      # exit code
      rc="$(cat "$rcfile" 2>/dev/null || echo 0)"
      return "$rc"
    fi
  fi

  # Miss/expired → execute real command and cache combined stdout+stderr
  local out
  out="$(command "$real" "$@" 2>&1)"
  rc=$?
  __gc_atomic_write "$of" "$out"
  __gc_atomic_write "$rcfile" "$rc"
  printf "%s" "$out"
  return "$rc"
}

# ------------------------------- Wrappers -------------------------------------
# Wrap rg (ripgrep) if present
if __gc_cmd_exists rg; then
  __gc_rg() { __gc_dedup_exec rg "$@"; }
  export -f __gc_rg
  alias rg='__gc_rg'
fi

# Wrap find if present
if __gc_cmd_exists find; then
  __gc_find() { __gc_dedup_exec find "$@"; }
  export -f __gc_find
  alias find='__gc_find'
fi

# Wrap gpt-creator (only if installed)
if __gc_cmd_exists gpt-creator; then
  __GC_REAL="$(command -v gpt-creator)"

  __gc_cmd() {
    # Transparent wrapper with scan de-dup; plus auto-refresh for show-file if cached.
    if [[ "${1:-}" == "show-file" ]]; then
      shift
      local out rc
      out="$(__gc_dedup_exec "$__GC_REAL" show-file "$@" )"; rc=$?
      # Auto-refresh when the tool tells us the rendering was cached
      if [[ $rc -eq 0 && "$out" == *"use --refresh to re-display"* ]]; then
        __gc_dedup_exec "$__GC_REAL" show-file "$@" --refresh
        return $?
      fi
      printf "%s" "$out"
      return $rc
    else
      # For all other subcommands, just pass through (no dedup unless targets are present)
      __gc_dedup_exec "$__GC_REAL" "$@"
      return $?
    fi
  }
  export -f __gc_cmd
  alias gpt-creator='__gc_cmd'
fi

# Documentation search helper backed by the catalog FTS index.
__gc_doc_search() {
  if ! __gc_cmd_exists python3; then
    printf 'doc_search: python3 is required.\n' >&2
    return 127
  fi
  local query="${1:-}"
  local limit="${2:-12}"
  if [[ -z "$query" ]]; then
    printf 'Usage: doc_search "<fts query>" [limit]\n' >&2
    return 1
  fi
  if ! [[ "$limit" =~ ^[0-9]+$ ]]; then
    printf 'doc_search: limit must be numeric (received %s).\n' "$limit" >&2
    return 1
  fi
  local root="${GC_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local script="${root}/src/lib/doc_registry.py"
  if [[ ! -f "$script" ]]; then
    printf 'doc_search: doc registry script not found at %s\n' "$script" >&2
    return 1
  fi
  python3 "$script" search "$query" --limit "$limit"
}
export -f __gc_doc_search
alias doc_search='__gc_doc_search'
