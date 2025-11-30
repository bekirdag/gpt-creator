#!/usr/bin/env bash
# shellcheck shell=bash

cmd_qa_tasks() {
  local root="" db_override="" task_filter="" url="" head_mode="headless" dry_run=0 allow_console=0 allow_network=0 retry_mobile=1 fallback_cmd=""
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
      --task)
        task_filter="${2:-}"
        shift 2
        ;;
      --task=*)
        task_filter="${1#*=}"
        shift
        ;;
      --url)
        url="${2:-}"
        shift 2
        ;;
      --url=*)
        url="${1#*=}"
        shift
        ;;
      --headed)
        head_mode="headed"
        shift
        ;;
      --headless)
        head_mode="headless"
        shift
        ;;
      --strict-http)
        shift
        ;;
      --allow-console)
        allow_console=1
        shift
        ;;
      --allow-network)
        allow_network=1
        shift
        ;;
      --dry-run|--dryrun)
        dry_run=1
        shift
        ;;
      --retry-mobile)
        retry_mobile=1
        shift
        ;;
      --no-retry-mobile)
        retry_mobile=0
        shift
        ;;
      --fallback-cmd)
        fallback_cmd="${2:-}"
        shift 2
        ;;
      --fallback-cmd=*)
        fallback_cmd="${1#*=}"
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd qa-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/qa_tasks_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown qa-tasks option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  [[ -n "$url" ]] || die "--url is required for qa-tasks"
  local tasks_db="${db_override:-${PLAN_DIR}/tasks/tasks.db}"
  if [[ ! -f "$tasks_db" ]]; then
    die "Tasks database not found at ${tasks_db}."
  fi

  local helper_path
  gc_clone_python_tool "task_comments.py" "${PROJECT_ROOT:-$PWD}" >/dev/null 2>&1 || true
  gc_clone_python_tool "update_task_state.py" "${PROJECT_ROOT:-$PWD}" >/dev/null 2>&1 || true
  helper_path="$(gc_clone_python_tool "qa_tasks.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  local -a args=(--project "${PROJECT_ROOT:-$PWD}" --db "$tasks_db" --url "$url")
  [[ -n "$task_filter" ]] && args+=(--task "$task_filter")
  if [[ "$head_mode" == "headed" ]]; then
    args+=(--headed)
  else
    args+=(--headless)
  fi
  (( allow_console )) && args+=(--allow-console)
  (( allow_network )) && args+=(--allow-network)
  (( retry_mobile )) && args+=(--retry-mobile)
  (( retry_mobile == 0 )) && args+=(--no-retry-mobile)
  [[ -n "$fallback_cmd" ]] && args+=(--fallback-cmd "$fallback_cmd")
  (( dry_run )) && args+=(--dry-run)
  python3 "$helper_path" "${args[@]}"
}
