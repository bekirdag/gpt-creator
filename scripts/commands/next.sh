#!/usr/bin/env bash
# shellcheck shell=bash

cmd_next() {
  local root="" story=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|-p)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --story)
        story="$2"
        shift 2
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd next)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/next_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown argument for next: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db="${PLAN_DIR}/tasks/tasks.db"
  [[ -f "$tasks_db" ]] || die "Tasks database not found at ${tasks_db}. Run 'gpt-creator create-tasks' first."

  local story_plan_helper
  story_plan_helper="$(gc_clone_python_tool "story_scheduler.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  "$python_bin" "$story_plan_helper" "$tasks_db" "${story:-}" "1" >/dev/null 2>&1 || true

  local dag_helper
  dag_helper="$(gc_clone_python_tool "dag_inspect.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  local -a helper_args=(next --project-root "${PROJECT_ROOT:-$PWD}" --db "$tasks_db")
  if [[ -n "$story" ]]; then
    helper_args+=(--story "$story")
  fi
  python3 "$dag_helper" "${helper_args[@]}"
}

