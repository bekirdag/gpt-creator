#!/usr/bin/env bash
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  if [[ -z "${GC_BASH_BOOTSTRAP:-}" ]]; then
    bash_candidates=()
    if [[ -n "${GC_PREFERRED_BASH:-}" ]]; then
      bash_candidates+=("${GC_PREFERRED_BASH}")
    fi
    if [[ -n "${GC_BASH:-}" ]]; then
      bash_candidates+=("${GC_BASH}")
    fi
    if command -v brew >/dev/null 2>&1; then
      brew_bash="$(brew --prefix 2>/dev/null)/bin/bash"
      if [[ -x "${brew_bash:-}" ]]; then
        bash_candidates+=("$brew_bash")
      fi
    fi
    bash_candidates+=("/opt/homebrew/bin/bash" "/usr/local/bin/bash")
    for candidate in "${bash_candidates[@]}"; do
      [[ -n "$candidate" ]] || continue
      if [[ "$candidate" != "$BASH" && -x "$candidate" ]]; then
        if "$candidate" -c '[[ ${BASH_VERSINFO[0]} -ge 4 ]]' >/dev/null 2>&1; then
          export GC_BASH_BOOTSTRAP=1
          PATH="$(dirname "$candidate"):$PATH"
          export PATH
          exec "$candidate" "$0" "$@"
        fi
      fi
    done
  fi
  printf 'run_tasks_sigint_safe requires Bash 4 or newer. Install via `brew install bash` and retry, or set GC_PREFERRED_BASH to a modern shell.\n' >&2
  exit 1
fi

PROJECT_ROOT=${PROJECT_ROOT:-$(pwd)}
cli_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CMD=("${GC_CLI_BIN:-${cli_root}/bin/gpt-creator}" work-on-tasks --project "$PROJECT_ROOT")
python_bin="${PYTHON_BIN:-python3}"

run_pid=
run_pgid=

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
    "$python_bin" "$helper_path" "$work_root/state.json"
  fi

  # Snapshot Codex artifacts so the run is traceable without touching user edits
  local work_dir_name snapshot_dir
  work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  snapshot_dir="${PROJECT_ROOT}/${work_dir_name}"
  if command -v git >/dev/null 2>&1 && git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ -d "$snapshot_dir" ]]; then
      git -C "$PROJECT_ROOT" add -A -- "$work_dir_name" || true
      if ! git -C "$PROJECT_ROOT" diff --cached --quiet -- "$work_dir_name"; then
        git -C "$PROJECT_ROOT" commit -m "chore(gpt-creator): WIP snapshot after signal; mark apply_status=aborted" -- "$work_dir_name" || true
      fi
    fi
  fi

  # Ask child to exit gracefully
  if [[ -n "${run_pid:-}" ]]; then
    local target="-${run_pgid:-$run_pid}"
    kill -TERM "$target" 2>/dev/null || true

    for _ in {1..50}; do
      if ! kill -0 "$run_pid" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done

    if kill -0 "$run_pid" 2>/dev/null; then
      kill -KILL "$target" 2>/dev/null || true
    fi

    wait "$run_pid" 2>/dev/null || true
  fi
  exit 130
}

trap 'mark_interrupted INT' INT
trap 'mark_interrupted TERM' TERM

if command -v setsid >/dev/null 2>&1; then
  setsid "${CMD[@]}" "$@" &
else
  "$python_bin" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "${CMD[@]}" "$@" &
fi
run_pid=$!
if ! run_pgid="$(ps -o pgid= -p "$run_pid" 2>/dev/null)"; then
  run_pgid=""
fi
run_pgid="${run_pgid//[[:space:]]/}"
if [[ -z "${run_pgid:-}" ]]; then
  run_pgid="$run_pid"
fi
wait "$run_pid"
exit $?
