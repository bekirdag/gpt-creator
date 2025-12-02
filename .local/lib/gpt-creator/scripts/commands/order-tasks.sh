#!/usr/bin/env bash
# shellcheck shell=bash

cmd_order_tasks() {
  local root="" force=0
  local skip_refine_preflight=1
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|--root|-p)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --force)
        force=1
        shift
        ;;
      --no-refine-preflight)
        skip_refine_preflight=1
        shift
        ;;
      --refine|--refine-preflight)
        skip_refine_preflight=0
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd order-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/order_tasks_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown argument for order-tasks: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  gc_load_cmd refine-tasks
  local tasks_db="${PLAN_DIR}/tasks/tasks.db"
  [[ -f "$tasks_db" ]] || die "Tasks database not found at ${tasks_db}. Run 'gpt-creator create-tasks' first."
  if [[ "${GC_REFINE_PREFLIGHT:-0}" == "1" ]]; then
    skip_refine_preflight=0
  fi
  if [[ "${GC_SKIP_REFINE_PREFLIGHT:-0}" == "1" ]]; then
    skip_refine_preflight=1
  fi

  if (( ! skip_refine_preflight )); then
    local python_bin="${PYTHON_BIN:-python3}"
    local refine_init_helper refine_summary_helper summary total_tasks=0 refined_tasks=0 pending_tasks=0 _t _s
    if command -v "$python_bin" >/dev/null 2>&1; then
      if refine_init_helper="$(gc_clone_python_tool "refine_tasks_init_db.py" "${PROJECT_ROOT:-$PWD}")"; then
        "$python_bin" "$refine_init_helper" "$tasks_db" >/dev/null 2>&1 || true
      fi
      if refine_summary_helper="$(gc_clone_python_tool "refine_tasks_summary.py" "${PROJECT_ROOT:-$PWD}")"; then
        summary="$($python_bin "$refine_summary_helper" "$tasks_db")" || summary=""
      else
        summary=""
      fi
      read -r total_tasks refined_tasks pending_tasks _t _s <<<"${summary:-0 0 0 0 0}"
      total_tasks=${total_tasks:-0}
      pending_tasks=${pending_tasks:-0}
      if [[ "$pending_tasks" =~ ^[0-9]+$ ]] && (( pending_tasks > 0 )); then
        info "order-tasks: ${pending_tasks} task(s) missing refinement → running 'refine-tasks --force' first."
        if ! cmd_refine_tasks --project "${PROJECT_ROOT:-$PWD}" --force; then
          warn "order-tasks: refine step failed; proceeding with existing metadata."
        fi
      fi
    else
      warn "Python runtime '${python_bin}' not available; skipping refine preflight."
    fi
  fi

  local populate_helper
  populate_helper="$(gc_clone_python_tool "populate_task_dependencies.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  local -a populate_args=("$populate_helper" "$tasks_db")
  if (( force )); then
    populate_args+=("--force")
  else
    populate_args+=("--only-if-empty")
  fi
  python3 "${populate_args[@]}"

  local order_helper=""
  if ! order_helper="$(gc_clone_python_tool "update_global_task_order.py" "${PROJECT_ROOT:-$PWD}")"; then
    return 1
  fi
  python3 "$order_helper" "$tasks_db" --project-root "${PROJECT_ROOT:-$PWD}"
  local order_marker_dir
  order_marker_dir="$(cd "$(dirname "$tasks_db")" && pwd -P)"
  if [[ -n "$order_marker_dir" ]]; then
    local order_marker="${order_marker_dir}/ORDERED.ok"
    if ! date -u +"%Y-%m-%dT%H:%M:%SZ" >"$order_marker" 2>/dev/null; then
      : > "$order_marker" 2>/dev/null || true
    fi
  fi
  info "Task ordering refreshed for ${tasks_db}."
}
