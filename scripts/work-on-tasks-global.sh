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

needs_update="$(
  python3 - "$DB_PATH" <<'PY'
import sqlite3, sys
from pathlib import Path

TERMINAL = {
    "complete",
    "completed",
    "completed-no-changes",
    "done",
    "skipped",
    "skipped-already-complete",
}
PREFIXES = ("completed-", "done-", "skipped-")

db_path = Path(sys.argv[1])
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

needs = False
try:
    info = cur.execute("PRAGMA table_info(tasks)").fetchall()
except sqlite3.DatabaseError:
    print("update")
    sys.exit(0)

has_column = any(row[1] == "global_order" for row in info)
if not has_column:
    print("update")
    sys.exit(0)

rows = cur.execute("SELECT status, global_order FROM tasks").fetchall()
pending_found = False
for row in rows:
    status = (row["status"] or "").strip().lower().replace("_", "-")
    is_terminal = bool(status) and (status in TERMINAL or any(status.startswith(prefix) for prefix in PREFIXES))
    if is_terminal:
        continue
    pending_found = True
    order = row["global_order"] if row["global_order"] is not None else 0
    if int(order or 0) <= 0:
        needs = True
        break

if needs:
    print("update")
elif not pending_found:
    print("idle")
else:
    print("ready")
PY
)"

if [[ "$needs_update" == "update" ]]; then
  (cd "$ROOT_DIR" && python3 "${SCRIPT_DIR}/python/update_global_task_order.py" "$DB_PATH" --project-root "$PROJECT_ROOT_DIR" >/dev/null)
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
  IFS=$'\t' read -r order story_slug task_token position <<<"$entry"
  [[ -n "$story_slug" && -n "$task_token" ]] || continue
  local_story="${story_slug}"
  local_token="${task_token}"

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
