#!/usr/bin/env bash
# shellcheck shell=bash

cmd_migrate_tasks_json() {
  local root="" force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --force) force=1; shift;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd migrate-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/migrate_tasks_usage.txt"
        fi
        return 0
        ;;
      *) break;;
    esac
  done

  ensure_ctx "$root"

  local pipeline_dir="${PLAN_DIR}/create-jira-tasks"
  local json_dir="${pipeline_dir}/json"
  local epics_json="${json_dir}/epics.json"
  local stories_dir="${json_dir}/stories"
  local tasks_dir="${json_dir}/tasks"

  [[ -f "$epics_json" ]] || die "Epics JSON not found: ${epics_json}"
  [[ -d "$stories_dir" ]] || die "Stories JSON directory not found: ${stories_dir}"
  [[ -d "$tasks_dir" ]] || die "Tasks JSON directory not found: ${tasks_dir}"

  local payload="${json_dir}/tasks_payload.json"
  local tasks_workspace="${PLAN_DIR}/tasks"
  mkdir -p "$tasks_workspace"
  local db_path="${tasks_workspace}/tasks.db"
  local intake_lock_path="${tasks_workspace}/.intake-frozen"
  if [[ -f "$intake_lock_path" && "$force" -ne 1 ]]; then
    warn "Backlog intake frozen (see ${intake_lock_path#${PROJECT_ROOT:-$PWD}/}); rerun with --force after resolving duplicates."
    return 1
  fi

  info "Building tasks payload from JSON → ${payload}"
  info "Updating tasks database → ${db_path}"

  if ! gc_rebuild_tasks_db_from_json "$force"; then
    die "Failed to rebuild tasks database from JSON payload"
  fi

  ok "Tasks database updated → ${db_path}"
}
