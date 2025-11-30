#!/usr/bin/env bash
# shellcheck shell=bash

cmd_show_agent() {
  local root="" name="" full=0 json=0 verbose=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --name)
        name="${2:-}"
        shift 2
        ;;
      --full)
        full=1
        shift
        ;;
      --json)
        json=1
        shift
        ;;
      --verbose)
        verbose=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd show-agent)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/show_agent_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown show-agent option: $1"
        ;;
    esac
  done

  [[ -n "$name" ]] || die "--name is required for show-agent"

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("show" "--name" "$name")
  (( full )) && cli_args+=("--full")
  (( json )) && cli_args+=("--json")

  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
  return $?
}

