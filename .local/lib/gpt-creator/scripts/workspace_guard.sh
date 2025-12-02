#!/usr/bin/env sh
# Resolves a safe workspace dir for all stacks. No deps; POSIX sh.

set -eu

_err(){ printf >&2 "gpt-creator: %s\n" "$*"; exit 64; } # EX_USAGE

# Parse --project from args without mutating "$@"
PROJECT=""
NEXT=0
for a in "$@"; do
  if [ "$NEXT" -eq 1 ]; then PROJECT="$a"; NEXT=0; continue; fi
  case "$a" in
    --project=*) PROJECT="${a#--project=}" ;;
    --project)   NEXT=1 ;;
  esac
done

LOCK=".gpt-creator/workspace.lock"
HOME_SAFE="${HOME:-/nonexistent}"

# 1) precedence: CLI → env → lockfile → upward scan
CANDIDATE="${PROJECT:-${GC_PROJECT_DIR:-}}"
if [ -z "${CANDIDATE}" ] && [ -f "$LOCK" ]; then
  CANDIDATE="$(awk -F\" '/"root":/ {print $4; exit}' "$LOCK" 2>/dev/null || true)"
fi
if [ -z "${CANDIDATE}" ]; then
  d="$PWD"
  while [ "$d" != "/" ]; do
    [ -d "$d/.gpt-creator" ] || [ -d "$d/.git" ] && { CANDIDATE="$d"; break; }
    d=$(dirname "$d")
  done
fi
[ -n "${CANDIDATE:-}" ] || _err "no workspace found; pass --project /abs/path or set GC_PROJECT_DIR"

# 2) validate & harden
case "$CANDIDATE" in
  "/"|"$HOME_SAFE") _err "refusing to run in '$CANDIDATE' (unsafe root)";;
esac
[ -d "$CANDIDATE" ] || _err "workspace does not exist: $CANDIDATE"

# 3) mode detection (git or repo-less) + lockfile
MODE="repo-less"; [ -d "$CANDIDATE/.git" ] && MODE="git"
if ! mkdir -p "$CANDIDATE/.gpt-creator" 2>/dev/null; then
  printf >&2 "gpt-creator: warning: cannot create %s/.gpt-creator (continuing)\n" "$CANDIDATE"
fi
if ! printf '{ "root": "%s", "mode": "%s" }\n' "$CANDIDATE" "$MODE" > "$CANDIDATE/.gpt-creator/workspace.lock" 2>/dev/null; then
  printf >&2 "gpt-creator: warning: cannot write workspace.lock under %s/.gpt-creator (continuing without lock)\n" "$CANDIDATE"
fi

# 4) export + contain all child cmds to the workspace
export GC_WORKSPACE_DIR="$CANDIDATE"
cd "$CANDIDATE" || _err "cannot cd into workspace: $CANDIDATE"
