#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=""
FORCE=0

clone_python_tool() {
  local script_name="${1:?python script name required}"
  local root_param="${2:-}"
  local root="${root_param:-${PROJECT_ROOT:-$PWD}}"
  if command -v gc_clone_python_tool >/dev/null 2>&1; then
    gc_clone_python_tool "$script_name" "$root"
    return
  fi
  local cli_root="${CLI_ROOT:-}"
  if [[ -z "$cli_root" ]]; then
    cli_root="$(cd "$(dirname "$0")/.." && pwd -P)" || cli_root=""
  fi
  if [[ -z "$cli_root" ]]; then
    echo "Unable to determine CLI root while preparing ${script_name}" >&2
    return 1
  fi
  local source_path="${cli_root}/scripts/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    echo "Python helper missing at ${source_path}" >&2
    return 1
  fi
  local work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  local target_dir="${root%/}/${work_dir_name}/shims/python"
  local target_path="${target_dir}/${script_name}"
  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || return 1
  fi
  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || return 1
  fi
  if [[ "$script_name" == *.py ]]; then
    local base_name="${script_name%.py}"
    local sidecar="${base_name}_lib.py"
    local sidecar_source="${cli_root}/scripts/python/${sidecar}"
    local sidecar_target="${target_dir}/${sidecar}"
    if [[ -f "$sidecar_source" ]]; then
      if [[ ! -f "$sidecar_target" || "$sidecar_source" -nt "$sidecar_target" ]]; then
        cp "$sidecar_source" "$sidecar_target" || return 1
      fi
    fi
  fi
  printf '%s\n' "$target_path"
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
