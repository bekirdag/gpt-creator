#!/usr/bin/env bash
# shellcheck shell=bash

cmd_estimate() {
  local root="" recent_tasks="" scope="project" warn_threshold=""
  local apply_detections=0 no_cache=0 reindex=0 color_flag=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --recent-tasks)
        if [[ $# -lt 2 ]]; then
          die "--recent-tasks requires a value (positive integer or 'all')"
        fi
        recent_tasks="$2"
        shift 2
        ;;
      --scope)
        scope="$2"
        shift 2
        ;;
      --apply-detections)
        apply_detections=1
        shift
        ;;
      --no-cache)
        no_cache=1
        shift
        ;;
      --reindex)
        reindex=1
        shift
        ;;
      --warn-threshold)
        warn_threshold="$2"
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
        if tmpl="$(gc_help_template_for_cmd estimate)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/estimate_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown estimate option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db="${PLAN_DIR}/tasks/tasks.db"
  if [[ ! -f "$tasks_db" ]]; then
    die "Tasks database not found at ${tasks_db}. Run 'gpt-creator create-tasks' first."
  fi

  local helper_path
  helper_path="$(gc_clone_python_tool "estimate_remaining_work.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  local -a helper_args=("$helper_path" "$tasks_db")
  if [[ -n "$recent_tasks" ]]; then
    helper_args+=(--recent-tasks "$recent_tasks")
  fi
  if [[ -n "$scope" ]]; then
    helper_args+=(--scope "$scope")
  fi
  if (( apply_detections )); then
    helper_args+=(--apply-detections)
  fi
  if (( no_cache )); then
    helper_args+=(--no-cache)
  fi
  if (( reindex )); then
    helper_args+=(--reindex)
  fi
  if [[ -n "$warn_threshold" ]]; then
    helper_args+=(--warn-threshold "$warn_threshold")
  fi
  if [[ "$color_flag" == "always" ]]; then
    helper_args+=(--color)
  elif [[ "$color_flag" == "never" ]]; then
    helper_args+=(--no-color)
  fi
  if [[ -n "$color_flag" ]]; then
    GC_COLOR_OUTPUT="$color_flag" gc_render_with_renderer python3 "${helper_args[@]}"
  else
    gc_render_with_renderer python3 "${helper_args[@]}"
  fi
}
