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
      "Usage: work-on-tasks-retry.sh <task-ref> [additional gpt-creator args]" \
      "" \
      "Runs \`gpt-creator work-on-tasks\` scoped to a single task (batch size 1) and" \
      "automatically retries when the CLI exits with 124 or reports transient Codex errors." \
      "Set MAX_ATTEMPTS to change the retry limit (default 3)." \
      "" \
      "Examples:" \
      "  scripts/work-on-tasks-retry.sh story-slug:003 --project /path/to/project" >&2
  fi
  exit 2
}

if [[ $# -lt 1 ]]; then
  usage
fi

if [[ -z "${TMUX:-}" && -z "${STY:-}" ]]; then
  echo "[warn] Not running inside tmux/screen; start a session manager for long Codex runs." >&2
fi

task_ref="$1"; shift
declare -a base_args=(
  gpt-creator work-on-tasks
  --from-task "$task_ref"
  --batch-size 1
  --memory-cycle
)

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
  "${base_args[@]}" >"$log_file" 2>&1 &
  child_pid=$!
  wait "$child_pid"
  local status=$?
  child_pid=""
  # Treat transient LLM/tooling failures as retryable
  if (( status != 0 )); then
    if grep -Eiq '(heredoc[^\n]*(missing closing|unterminated)|blocked-?heredoc-?unterminated)' "$log_file"; then
      echo "[warn] Detected unterminated heredoc; marking as retryable (124)." >&2
      status=124
    elif grep -Eiq '(stream disconnected before completion|context window|exceeds the context window|produced no output|JSON not found in Codex output|Structured instructions not found in Codex output)' "$log_file"; then
      echo "[warn] Detected model stream/context failure; marking as retryable (124)." >&2
      status=124
    elif grep -Eiq 'apply-failed-migration-context|empty-apply checkpoint' "$log_file"; then
      echo "[warn] Detected empty-apply/migration-context issue; marking as retryable (124)." >&2
      status=124
    fi
  fi
  cat "$log_file"; rm -f "$log_file"
  return "$status"
}

max_attempts="${MAX_ATTEMPTS:-3}"
attempt=1
status=0

while (( attempt <= max_attempts )); do
  if (( attempt > 1 )); then
    export CJT_REFINE_SDS_OVERVIEW_LIMIT="${CJT_REFINE_SDS_OVERVIEW_LIMIT:-2}"
    export CJT_REFINE_SDS_CHUNK_LIMIT="${CJT_REFINE_SDS_CHUNK_LIMIT:-1}"
    export CJT_REFINE_OTHER_TASKS_LIMIT="${CJT_REFINE_OTHER_TASKS_LIMIT:-2}"
    export CJT_REFINE_TASK_FIELD_LIST_LIMIT="${CJT_REFINE_TASK_FIELD_LIST_LIMIT:-2}"
    export CJT_REFINE_TASK_FIELD_CHAR_LIMIT="${CJT_REFINE_TASK_FIELD_CHAR_LIMIT:-160}"
    export CJT_REFINE_SDS_SNIPPET_CHAR_LIMIT="${CJT_REFINE_SDS_SNIPPET_CHAR_LIMIT:-160}"
    export CJT_REFINE_SDS_SUMMARY_CHAR_LIMIT="${CJT_REFINE_SDS_SUMMARY_CHAR_LIMIT:-140}"
  fi
  if run_once; then
    status=0
    break
  fi
  status=$?
  if (( status == 124 && attempt < max_attempts )); then
    echo "[info] work-on-tasks marked retryable (exit 124); retrying task ${task_ref}..." >&2
    ((attempt++))
    continue
  fi
  break
done

exit "$status"
