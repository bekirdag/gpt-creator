#!/usr/bin/env bash
# shellcheck shell=bash

cmd_create_tasks() {
  local root="" jira="" force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --jira) jira="$(abs_path "$2")"; shift 2;;
      --force) force=1; shift;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd create-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/create_tasks_usage.txt"
        fi
        return 0
        ;;
      *) break;;
    esac
  done

  ensure_ctx "$root"
  [[ -n "$jira" ]] || jira="${INPUT_DIR}/jira.md"
  [[ -f "$jira" ]] || die "Jira tasks file not found: ${jira}"

  local tasks_dir="${PLAN_DIR}/tasks"
  local parsed_local="${tasks_dir}/parsed.local.json"
  local tasks_db="${tasks_dir}/tasks.db"
  mkdir -p "$tasks_dir"
  local intake_lock_path="${tasks_dir}/.intake-frozen"
  if [[ -f "$intake_lock_path" && "$force" -ne 1 ]]; then
    warn "Backlog intake frozen (see ${intake_lock_path#${PROJECT_ROOT:-$PWD}/}); rerun with --force after resolving duplicates."
    return 1
  fi

  info "Parsing Jira backlog → ${parsed_local}"
  gc_parse_jira_tasks "$jira" "$parsed_local"

  info "Building tasks database → ${tasks_db}"
  local db_stats
  if ! db_stats="$(gc_build_tasks_db "$parsed_local" "$tasks_db" "$force")"; then
    die "Failed to build Jira tasks SQLite database"
  fi

  local story_count=0 task_count=0 restored_stories=0 restored_tasks=0
  while IFS= read -r line; do
    case "$line" in
      STORIES\ *) story_count="${line#STORIES }" ;;
      TASKS\ *) task_count="${line#TASKS }" ;;
      RESTORED_STORIES\ *) restored_stories="${line#RESTORED_STORIES }" ;;
      RESTORED_TASKS\ *) restored_tasks="${line#RESTORED_TASKS }" ;;
    esac
  done <<<"$db_stats"

  info "Stories: ${story_count:-0} (restored: ${restored_stories:-0})"
  info "Tasks: ${task_count:-0} (restored statuses: ${restored_tasks:-0})"
  ok "Tasks database updated → ${tasks_db}"

  local legacy_manifest="${tasks_dir}/manifest.json"
  local legacy_stories="${tasks_dir}/stories"
  if [[ -f "$legacy_manifest" || -d "$legacy_stories" ]]; then
    warn "Legacy task manifest/JSON artifacts detected under ${tasks_dir}; they are no longer used now that tasks live in SQLite. Remove them when convenient to avoid confusion."
  fi
}
