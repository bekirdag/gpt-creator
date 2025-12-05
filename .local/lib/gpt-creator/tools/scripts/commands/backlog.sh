#!/usr/bin/env bash
# shellcheck shell=bash

cmd_backlog() {
  local root="" type_arg="" item_children="" show_progress=0 task_details="" dag_limit="" color_flag=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|--root)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --type)
        type_arg="$2"
        shift 2
        ;;
      --item-children)
        item_children="$2"
        shift 2
        ;;
      --progress)
        show_progress=1
        shift
        ;;
      --task-details)
        task_details="$2"
        shift 2
        ;;
      --dag-limit)
        dag_limit="$2"
        shift 2
        ;;
      --color)
        if [[ "$color_flag" == "never" ]]; then
          die "--color and --no-color are mutually exclusive"
        fi
        color_flag="always"
        shift
        ;;
      --no-color)
        if [[ "$color_flag" == "always" ]]; then
          die "--color and --no-color are mutually exclusive"
        fi
        color_flag="never"
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd backlog)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/backlog_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown argument for backlog: $1"
        ;;
    esac
  done

  if [[ -z "$type_arg" && -z "$item_children" && "$show_progress" -eq 0 && -z "$task_details" ]]; then
    type_arg="epics"
  fi

  ensure_ctx "$root"
  local tasks_db="${PLAN_DIR}/tasks/tasks.db"
  if [[ ! -f "$tasks_db" ]]; then
    die "Tasks database not found at ${tasks_db}. Run 'gpt-creator create-tasks' first."
  fi
  local check_helper=""
  if ! check_helper="$(gc_clone_python_tool "check_tasks_db_tables.py" "${PROJECT_ROOT:-$PWD}")"; then
    die "Failed to prepare tasks DB checker helper"
  fi
  python3 "$check_helper" "$tasks_db" epics stories tasks || return $?

  local backlog_helper
  backlog_helper="$(gc_clone_python_tool "fetch_stories.py" "${PROJECT_ROOT:-$PWD}")" || die "Failed to prepare backlog helper script"
  local output
  if [[ -n "$color_flag" ]]; then
    if ! output="$(GC_RENDER_EPIC_TSV=1 GC_COLOR_OUTPUT="$color_flag" python3 "$backlog_helper" "$tasks_db" "${type_arg:-}" "${item_children:-}" "$show_progress" "${task_details:-}" "${dag_limit:-}")"; then
      return 1
    fi
  else
    if ! output="$(GC_RENDER_EPIC_TSV=1 python3 "$backlog_helper" "$tasks_db" "${type_arg:-}" "${item_children:-}" "$show_progress" "${task_details:-}" "${dag_limit:-}")"; then
      return 1
    fi
  fi
  local gc_render_strict_restore="__unset__"
  if [[ -n "${GC_RENDER_GPT_CREATOR_STRICT+x}" ]]; then
    gc_render_strict_restore="$GC_RENDER_GPT_CREATOR_STRICT"
  fi
  GC_RENDER_GPT_CREATOR_STRICT=1
  printf "%s" "$output" | gc_render_with_renderer cat
  local render_status=$?
  if [[ "$gc_render_strict_restore" == "__unset__" ]]; then
    unset GC_RENDER_GPT_CREATOR_STRICT
  else
    GC_RENDER_GPT_CREATOR_STRICT="$gc_render_strict_restore"
  fi
  return $render_status
}
