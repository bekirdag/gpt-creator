#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -n "${PROJECT_ROOT:-}" && -d "${PROJECT_ROOT}" ]]; then
  ROOT_DIR="$(cd "${PROJECT_ROOT}" && pwd -P)"
else
  ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
fi
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
      "  scripts/work-on-tasks-retry.sh --project /path/to/project" \
      "  scripts/work-on-tasks-retry.sh --story story-slug --project /path/to/project" >&2
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

args=("$@")
story_filter=""
task_filter=""
for (( idx = 0; idx < ${#args[@]}; idx++ )); do
  arg="${args[idx]}"
  case "$arg" in
    --story|--from-story)
      if (( idx + 1 < ${#args[@]} )); then
        story_filter="${args[idx + 1]}"
      fi
      ;;
    --story=*|--from-story=*)
      story_filter="${arg#*=}"
      ;;
    --task)
      if (( idx + 1 < ${#args[@]} )); then
        task_filter="${args[idx + 1]}"
      fi
      ;;
    --task=*)
      task_filter="${arg#*=}"
      ;;
  esac
done

declare -a base_args=(
  gpt-creator work-on-tasks
  --batch-size 1
  --memory-cycle
)

if [[ -n "$task_ref" ]]; then
  base_args+=(--from-task "$task_ref")
fi

if [[ -z "$task_filter" && -n "${TASK_FILTER:-}" ]]; then
  task_filter="${TASK_FILTER}"
fi

if (( ${#args[@]} > 0 )); then
  base_args+=("${args[@]}")
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

run_with_retries() {
  local attempt=1
  local status=0
  local retry_label=""
  if [[ -n "$task_ref" ]]; then
    retry_label="$task_ref"
  elif [[ -n "$task_filter" ]]; then
    retry_label="$task_filter"
  elif [[ -n "$story_filter" ]]; then
    retry_label="$story_filter"
  fi

  while (( attempt <= max_attempts )); do
    if run_once; then
      status=0
      break
    fi
    status=$?
    if (( status == 124 && attempt < max_attempts )); then
      if [[ -n "$retry_label" ]]; then
        echo "[info] work-on-tasks exited with timeout (124); retrying ${retry_label}..." >&2
      else
        echo "[info] work-on-tasks exited with timeout (124); retrying..." >&2
      fi
      ((attempt++))
      continue
    fi
    break
  done

  return "$status"
}

max_attempts="${MAX_ATTEMPTS:-3}"
status=0

mkdir -p "${ROOT_DIR}/.gpt-creator/logs"
LAST_BASE_SHA="${ROOT_DIR}/.gpt-creator/logs/last_run.base_sha"

record_base_sha() {
  git rev-parse HEAD > "$LAST_BASE_SHA" 2>/dev/null || true
}

record_base_sha

if [[ -n "$story_filter" ]]; then
  if run_with_retries; then
    exit 0
  fi
  status=$?
  exit "$status"
fi

MAX_SPINS="${MAX_SPINS:-1000}"
spins=0
prev_story=""

while (( spins < MAX_SPINS )); do
  record_base_sha

  if run_with_retries; then
    status=0
  else
    status=$?
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
