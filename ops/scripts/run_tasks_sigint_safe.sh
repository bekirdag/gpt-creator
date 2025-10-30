#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=${PROJECT_ROOT:-$(pwd)}
CMD=(gpt-creator work-on-tasks --project "$PROJECT_ROOT")

run_pid=

clone_python_tool() {
  local script_name="${1:?python script name required}"
  local project_root="${2:-${PROJECT_ROOT:-$PWD}}"

  if declare -f gc_clone_python_tool >/dev/null 2>&1; then
    gc_clone_python_tool "$script_name" "$project_root"
    return
  fi

  local cli_root
  if [[ -n "${GC_ROOT:-}" ]]; then
    cli_root="$GC_ROOT"
  else
    cli_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  fi

  local source_path="${cli_root}/scripts/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    printf 'Python helper missing at %s\n' "$source_path" >&2
    exit 1
  fi

  local work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  local target_dir="${project_root%/}/${work_dir_name}/shims/python"
  local target_path="${target_dir}/${script_name}"

  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir"
  fi

  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path"
  fi

  printf '%s\n' "$target_path"
}

mark_interrupted() {
  local signal="$1"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  local work_root="$PROJECT_ROOT/.gpt-creator/staging/plan/work"

  mkdir -p "$work_root"
  printf '{"apply_status":"aborted","interrupted_by_signal":true,"signal":"%s","marked_at":"%s"}\n' \
    "$signal" "$ts" > "$work_root/INTERRUPTED.meta.json"

  # Patch state.json -> apply_status=aborted (safe to retry)
  if [[ -f "$work_root/state.json" ]]; then
    local helper_path
    helper_path="$(clone_python_tool "mark_work_interrupted_state.py" "${PROJECT_ROOT:-$PWD}")" || return 1
    python3 "$helper_path" "$work_root/state.json"
  fi

  # Snapshot WIP so the run is traceable
  git add -A || true
  git commit -m "chore(gpt-creator): WIP snapshot after signal; mark apply_status=aborted" || true

  # Ask child to exit gracefully
  if [[ -n "${run_pid:-}" ]]; then
    kill -TERM "$run_pid" 2>/dev/null || true
    wait "$run_pid" 2>/dev/null || true
  fi
  exit 130
}

trap 'mark_interrupted INT' INT
trap 'mark_interrupted TERM' TERM

"${CMD[@]}" "$@" &
run_pid=$!
wait "$run_pid"
exit $?
