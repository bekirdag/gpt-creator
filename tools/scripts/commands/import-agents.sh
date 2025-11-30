#!/usr/bin/env bash
# shellcheck shell=bash

cmd_import_agents() {
  local root="" input=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2 ;;
      --input) input="$2"; shift 2 ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd import-agents)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/import_agents_usage.txt"
        fi
        return 0
        ;;
      *) break ;;
    esac
  done
  [[ -n "$input" ]] || die "--input is required for import-agents"
  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"
  local -a cli_args=("import" "--input" "$input")
  cli_args+=("$@")
  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
}
