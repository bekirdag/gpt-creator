#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE' >&2
Usage: work-on-tasks-retry.sh <task-ref> [additional gpt-creator args]

Runs `gpt-creator work-on-tasks` scoped to a single task (batch size 1) and
automatically retries once when the CLI reports a timeout (exit 124).

Examples:
  scripts/work-on-tasks-retry.sh story-slug:003 --project /path/to/project
USAGE
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
  "${base_args[@]}" &
  child_pid=$!
  wait "$child_pid"
  local status=$?
  child_pid=0
  return "$status"
}

max_attempts=2
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

exit "$status"
