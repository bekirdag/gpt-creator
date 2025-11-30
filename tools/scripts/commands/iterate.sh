#!/usr/bin/env bash
# shellcheck shell=bash

cmd_iterate() {
  warn "'iterate' is deprecated; running 'create-tasks' followed by 'work-on-tasks'. Use those commands directly for finer control."

  local root="" jira="" dry_run=0 force=0
  case "${GC_DRY_RUN:-}" in
    1|true|yes|on) dry_run=1 ;;
  esac
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --jira|--tasks-file)
        jira="$(abs_path "$2")"
        shift 2
        ;;
      --dry-run)
        dry_run=1
        shift
        ;;
      --force)
        force=1
        shift
        ;;
      --no-verify|--verify)
        # Legacy flags kept for compatibility; no-op in the new flow.
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd iterate)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/iterate_usage.txt"
        fi
        return 0
        ;;
      *)
        break
        ;;
    esac
  done

  ensure_ctx "$root"
  [[ -n "$jira" ]] || jira="${INPUT_DIR}/jira.md"
  [[ -f "$jira" ]] || die "Jira tasks file not found: ${jira}"

  gc_load_cmd create-tasks
  gc_load_cmd work-on-tasks

  local -a create_args=(--project "$PROJECT_ROOT" --jira "$jira")
  (( force )) && create_args+=(--force)
  cmd_create_tasks "${create_args[@]}"

  (( dry_run )) && return 0
  cmd_work_on_tasks --project "$PROJECT_ROOT"
}
