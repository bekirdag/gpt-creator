#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
HELP_DIR="${ROOT_DIR}/assets/templates/help"

usage() {
  local usage_file="${HELP_DIR}/work_on_tasks_retry_usage.txt"
  if [[ -f "$usage_file" ]]; then
    cat "$usage_file" >&2
  else
    printf '%s\n' \
      "Usage: work-on-tasks-retry.sh [task-ref] [additional gpt-creator args]" \
      "" \
      "Runs \`gpt-creator work-on-tasks\` (batch size 1, memory enabled) and" \
      "automatically retries once when the CLI reports a timeout (exit 124)." \
      "" \
      "Examples:" \
      "  scripts/work-on-tasks-retry.sh story-slug:003 --project /path/to/project" \
      "  scripts/work-on-tasks-retry.sh --project /path/to/project" >&2
  fi
  exit 2
}

if [[ $# -gt 0 && "$1" == "--help" ]]; then
  usage
fi

if [[ -z "${TMUX:-}" && -z "${STY:-}" ]]; then
  echo "[warn] Not running inside tmux/screen; start a session manager for long Codex runs." >&2
fi

task_ref=""
if [[ $# -gt 0 && "$1" != -* ]]; then
  task_ref="$1"
  shift
fi

declare -a base_args=(
  gpt-creator work-on-tasks
  --batch-size 1
  --memory-cycle
)

if [[ -n "$task_ref" ]]; then
  base_args+=(--from-task "$task_ref")
fi

if [[ $# -gt 0 ]]; then
  base_args+=("$@")
fi

child_pid=0

forward_signal() {
  local signal="$1"
  if (( child_pid > 0 )); then
    echo "[warn] Received ${signal}; signalling gpt-creator (pid ${child_pid}) to wrap up active task..." >&2
    kill -s "$signal" "$child_pid" 2>/dev/null || true
    wait "$child_pid" || true
  fi
}

trap 'forward_signal INT' INT
trap 'forward_signal TERM' TERM

run_once() {
  local log_file
  log_file="$(mktemp -t gc_work_XXXX.log)"
  local status=0
  if "${SCRIPT_DIR}/run-and-filter.sh" --log "$log_file" -- "${base_args[@]}"; then
    status=0
  else
    status=$?
  fi
  mkdir -p "${ROOT_DIR}/.gpt-creator/logs"
  cp "$log_file" "${ROOT_DIR}/.gpt-creator/logs/last_run.log"
  python3 "${SCRIPT_DIR}/python/git_change_detector.py" >/dev/null 2>&1 || true
  return "$status"
}

max_attempts="${MAX_ATTEMPTS:-3}"
attempt=1
status=0

mkdir -p "${ROOT_DIR}/.gpt-creator/logs"
MAX_SPINS="${MAX_SPINS:-1000}"
spins=0
prev_story=""

while (( spins < MAX_SPINS )); do
  git rev-parse HEAD > "${ROOT_DIR}/.gpt-creator/logs/last_run.base_sha" 2>/dev/null || true
  attempt=1
  status=0

  while (( attempt <= max_attempts )); do
    if run_once; then
      status=0
      break
    fi
    status=$?
    if (( status == 124 && attempt < max_attempts )); then
      echo "[info] work-on-tasks exited with timeout (124); retrying task ${task_ref}..." >&2
      ((attempt++))
      continue
    fi
    break
  done

  if (( status != 0 )); then
    break
  fi

  current_story="$(grep -Eo "Preparing prompt for story '[^']+'" "${ROOT_DIR}/.gpt-creator/logs/last_run.log" | tail -n1 | sed -E "s/.*'([^']+)'.*/\1/" || true)"
  if [[ -z "$current_story" || "$current_story" == "$prev_story" ]]; then
    break
  fi

  prev_story="$current_story"
  ((spins++))
done

exit "$status"
