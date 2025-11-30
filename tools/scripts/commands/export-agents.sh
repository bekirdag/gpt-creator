#!/usr/bin/env bash
# shellcheck shell=bash

cmd_export_agents() {
  local root="" output=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2 ;;
      --output) output="$2"; shift 2 ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd export-agents)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/export_agents_usage.txt"
        fi
        return 0
        ;;
      *) break ;;
    esac
  done
  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"
  local -a cli_args=("export")
  [[ -n "$output" ]] && cli_args+=("--output" "$output")
  cli_args+=("$@")
  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
}

