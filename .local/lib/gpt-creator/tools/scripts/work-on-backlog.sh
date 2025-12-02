#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
NEXT_STORY_HELPER="${SCRIPT_DIR}/python/next_story_after.py"

MAX_STORY_SPINS="${MAX_STORY_SPINS:-0}"
spins=0
prev_story=""

declare -a passthrough_args=()
project_root_arg=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      project_root_arg="${2:-}"
      passthrough_args+=("$1" "$2")
      shift 2
      ;;
    --project=*)
      project_root_arg="${1#--project=}"
      passthrough_args+=("$1")
      shift
      ;;
    *)
      passthrough_args+=("$1")
      shift
      ;;
  esac
done

PROJECT_ROOT="${project_root_arg:-${GC_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}}"
if [[ -d "$PROJECT_ROOT" ]]; then
  PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
fi

TASKS_DB_PATH="${TASKS_DB_PATH:-${PROJECT_ROOT}/.gpt-creator/plan/tasks/tasks.db}"

if [[ ! -f "$TASKS_DB_PATH" ]]; then
  echo "[error] tasks database not found at ${TASKS_DB_PATH}. Run 'gpt-creator create-tasks --project ${PROJECT_ROOT}' first." >&2
  exit 1
fi

mkdir -p "${ROOT_DIR}/.gpt-creator/logs"
LAST_LOG="${ROOT_DIR}/.gpt-creator/logs/last_run.log"

while :; do
  if (( MAX_STORY_SPINS > 0 )) && (( spins >= MAX_STORY_SPINS )); then
    echo "[stop] reached MAX_STORY_SPINS=${MAX_STORY_SPINS}."
    break
  fi

  next_story="$(python3 "$NEXT_STORY_HELPER" "$TASKS_DB_PATH" "$prev_story" 2>/dev/null || echo "NONE")"
  if [[ -z "$next_story" || "$next_story" == "NONE" ]]; then
    echo "[done] all stories in backlog are complete."
    break
  fi

  : >"$LAST_LOG"
  echo "▶ Working story: ${next_story}"

  if ! "${SCRIPT_DIR}/work-on-tasks-retry.sh" --story "$next_story" "${passthrough_args[@]}"; then
    echo "[error] work-on-tasks failed for story '${next_story}'; stopping." >&2
    exit 1
  fi

  prev_story="$next_story"
  ((spins++))
done

echo "[ok] processed ${spins} stor(ies)."
