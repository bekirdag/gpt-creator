#!/usr/bin/env bash
# shellcheck shell=bash

cmd_review_tasks() {
  local root="" agent="" db_override="" task_filter="" dry_run=0 client_override="" model_override="" max_issues=10 max_output=4000
  case "${GC_DRY_RUN:-}" in
    1|true|yes|on) dry_run=1 ;;
  esac
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|--root)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --db)
        db_override="$(abs_path "$2")"
        shift 2
        ;;
      --db=*)
        db_override="$(abs_path "${1#*=}")"
        shift
        ;;
      --agent)
        agent="${2:-}"
        shift 2
        ;;
      --agent=*)
        agent="${1#*=}"
        shift
        ;;
      --client)
        client_override="${2:-}"
        shift 2
        ;;
      --client=*)
        client_override="${1#*=}"
        shift
        ;;
      --model)
        model_override="${2:-}"
        shift 2
        ;;
      --model=*)
        model_override="${1#*=}"
        shift
        ;;
      --max-issues)
        max_issues="${2:-10}"
        shift 2
        ;;
      --max-issues=*)
        max_issues="${1#*=}"
        shift
        ;;
      --max-output)
        max_output="${2:-4000}"
        shift 2
        ;;
      --max-output=*)
        max_output="${1#*=}"
        shift
        ;;
      --task)
        task_filter="${2:-}"
        shift 2
        ;;
      --task=*)
        task_filter="${1#*=}"
        shift
        ;;
      --dry-run|--dryrun)
        dry_run=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd review-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/review_tasks_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown review-tasks option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db="${db_override:-${PLAN_DIR}/tasks/tasks.db}"
  if [[ ! -f "$tasks_db" ]]; then
    die "Tasks database not found at ${tasks_db}."
  fi

  local helper_path
  gc_clone_python_tool "llm_client_factory.py" "${PROJECT_ROOT:-$PWD}" >/dev/null 2>&1 || true
  gc_clone_python_tool "task_comments.py" "${PROJECT_ROOT:-$PWD}" >/dev/null 2>&1 || true
  gc_clone_python_tool "update_task_state.py" "${PROJECT_ROOT:-$PWD}" >/dev/null 2>&1 || true
  helper_path="$(gc_clone_python_tool "review_tasks.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  local -a args=(--project "${PROJECT_ROOT:-$PWD}" --db "$tasks_db")
  [[ -n "$agent" ]] && args+=(--agent "$agent")
  [[ -n "$client_override" ]] && args+=(--client "$client_override")
  [[ -n "$model_override" ]] && args+=(--model "$model_override")
  [[ -n "$max_issues" ]] && args+=(--max-issues "$max_issues")
  [[ -n "$max_output" ]] && args+=(--max-output "$max_output")
  [[ -n "$task_filter" ]] && args+=(--task "$task_filter")
  (( dry_run )) && args+=(--dry-run)

  python3 "$helper_path" "${args[@]}"
}
