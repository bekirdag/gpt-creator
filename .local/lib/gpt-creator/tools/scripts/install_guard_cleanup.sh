#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=""
FORCE=0

# shellcheck source=tools/scripts/lib/python_clone.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib/python_clone.sh"

clone_python_tool() {
  gc_clone_python_tool "$@"
}

usage() {
  cat <<'EOF'
Usage: scripts/install_guard_cleanup.sh [--project PATH] [--force]

Removes stray PLAN/PLAN.md artifacts and records the install guard sentinel so
automation loops cannot recreate them.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT_ROOT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

require_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for realpath resolution." >&2
    exit 1
  fi
}

resolve_realpath() {
  local helper_path
  helper_path="$(clone_python_tool "resolve_realpath.py" "$PROJECT_ROOT")" || exit 1
  python3 "$helper_path" "$1"
}

if [[ -z "$PROJECT_ROOT" ]]; then
  PROJECT_ROOT="$PWD"
fi

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Project path not found: $PROJECT_ROOT" >&2
  exit 1
fi

require_python

root_real="$(resolve_realpath "$PROJECT_ROOT")"

backup_dir="${PROJECT_ROOT}/.gpt-creator/install-guard/backups"
mkdir -p "$backup_dir"

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
removed_any=0

for candidate in PLAN PLAN.md Plan Plan.md plan plan.md; do
  full_path="${PROJECT_ROOT}/${candidate}"
  if [[ -e "$full_path" ]]; then
    removed_any=1
    full_real="$(resolve_realpath "$full_path")"
    case "$full_real" in
      "$root_real"/*) ;;
      *)
        echo "Refusing to modify path outside project root: ${full_real}" >&2
        exit 3
        ;;
    esac
    if (( FORCE )); then
      rm -rf -- "$full_path"
      echo "Removed ${candidate}"
    else
      mv "$full_path" "${backup_dir}/${candidate}.${timestamp}"
      echo "Archived ${candidate} -> ${backup_dir}/${candidate}.${timestamp}"
    fi
  fi
done

if (( removed_any == 0 )); then
  echo "No PLAN artifacts found under ${PROJECT_ROOT}."
fi

sentinel_dir="${PROJECT_ROOT}/.gpt-creator/install-guard"
mkdir -p "$sentinel_dir"
sentinel="${sentinel_dir}/plan-file-v1.ok"
umask 077
tmp="$(mktemp "${sentinel_dir}/.sentinel.XXXXXX")"
printf 'install-guard plan-file-v1 ok at %s\n' "$timestamp" >"$tmp"
mv -f "$tmp" "$sentinel"
echo "Install guard sentinel updated at ${sentinel}"
echo "Cleanup complete."
