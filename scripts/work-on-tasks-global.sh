#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

story_override="${STORY_FILTER:-}"
task_override="${TASK_FILTER:-}"
project_override=""
declare -a extra_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project|--root)
      if [[ $# -ge 2 ]]; then
        project_override="$2"
        extra_args+=("$1" "$2")
        shift 2
        continue
      fi
      ;;
    --project=*|--root=*)
      project_override="${1#*=}"
      extra_args+=("$1")
      shift
      continue
      ;;
    --story|--from-story)
      if [[ $# -ge 2 ]]; then
        story_override="$2"
        shift 2
        continue
      fi
      ;;
    --story=*|--from-story=*)
      story_override="${1#*=}"
      shift
      continue
      ;;
    --task)
      if [[ $# -ge 2 ]]; then
        task_override="$2"
        shift 2
        continue
      fi
      ;;
    --task=*)
      task_override="${1#*=}"
      shift
      continue
      ;;
  esac
  extra_args+=("$1")
  shift
done

if [[ -n "$project_override" ]]; then
  if [[ ! -d "$project_override" ]]; then
    echo "Project directory not found: $project_override" >&2
    exit 1
  fi
  PROJECT_ROOT_DIR="$(cd "$project_override" && pwd -P)"
elif [[ -n "${PROJECT_ROOT:-}" && -d "${PROJECT_ROOT}" ]]; then
  PROJECT_ROOT_DIR="$(cd "${PROJECT_ROOT}" && pwd -P)"
else
  PROJECT_ROOT_DIR="$(pwd -P)"
fi
export PROJECT_ROOT="$PROJECT_ROOT_DIR"

if [[ -n "${PLAN_DIR:-}" ]]; then
  DB_DEFAULT="$(cd "${PLAN_DIR}" 2>/dev/null && pwd -P)/tasks/tasks.db"
else
  DB_DEFAULT="${PROJECT_ROOT_DIR}/.gpt-creator/staging/plan/tasks/tasks.db"
fi
DB_PATH="${DB_PATH:-$DB_DEFAULT}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Task database not found at $DB_PATH; run 'gpt-creator create-tasks' first." >&2
  exit 1
fi

order_dir="$(cd "$(dirname "$DB_PATH")" && pwd -P)"
order_marker="${order_dir}/ORDERED.ok"
if [[ ! -f "$order_marker" ]]; then
  echo "[work-on-tasks] No recorded global order; running 'order-tasks --no-refine-preflight' once." >&2
  if ! GC_SKIP_REFINE_PREFLIGHT=1 "$ROOT_DIR/bin/gpt-creator" order-tasks --project "$PROJECT_ROOT_DIR" --no-refine-preflight >/dev/null; then
    echo "[work-on-tasks] 'order-tasks' failed; continuing with existing queue." >&2
  fi
fi

readarray -t queue < <(cd "$ROOT_DIR" && python3 "${SCRIPT_DIR}/python/list_global_task_queue.py" "$DB_PATH")

if (( ${#queue[@]} == 0 )); then
  echo "Global task queue is empty; nothing to do."
  exit 0
fi

story_override_norm="${story_override,,}"
task_override_norm="${task_override,,}"
ran_any=0

for entry in "${queue[@]}"; do
  IFS=$'\t' read -r order story_slug task_token _position <<<"$entry"
  [[ -n "$story_slug" && -n "$task_token" ]] || continue
  local_story="${story_slug}"
  local_token="${task_token}"
  fallback_token=""
  if [[ "${_position:-}" =~ ^[0-9]+$ ]]; then
    printf -v fallback_token "%s:%d" "${story_slug,,}" $((_position + 1))
  fi

  if [[ -n "$story_override_norm" && "${local_story,,}" != "$story_override_norm" ]]; then
    continue
  fi
  if [[ -n "$task_override_norm" && "${local_token,,}" != "$task_override_norm" ]]; then
    continue
  fi

  printf '▶ %s :: %s (order #%s)\n' "${local_story:-<no-story>}" "$local_token" "$order"
  ran_any=1

  GC_TASK_ORDER=list \
  STORY_FILTER="${local_story}" \
  TASK_FILTER="${local_token,,}" \
  TASK_FALLBACK="${fallback_token}" \
  bash "${SCRIPT_DIR}/work-on-tasks-retry.sh" --story "${local_story}" --task "$local_token" "${extra_args[@]}" || true
done

if (( ran_any == 0 )); then
  if [[ -n "$task_override" ]]; then
    printf 'No tasks matched override "%s".\n' "$task_override" >&2
    exit 1
  fi
  if [[ -n "$story_override" ]]; then
    printf 'No tasks matched story override "%s".\n' "$story_override" >&2
    exit 1
  fi
fi
