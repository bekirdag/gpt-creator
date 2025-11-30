#!/usr/bin/env bash
# shellcheck shell=bash

cmd_check_llms() {
  local root="" provider="" adapter="" json=0 dry_run=0 verbose=0 install_missing=0 health_check=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --provider)
        provider="${2:-}"
        shift 2
        ;;
      --adapter)
        adapter="${2:-}"
        shift 2
        ;;
      --json)
        json=1
        shift
        ;;
      --dry-run)
        dry_run=1
        shift
        ;;
      --install-missing)
        install_missing=1
        shift
        ;;
      --health-check)
        health_check=1
        shift
        ;;
      --verbose)
        verbose=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd check-llms)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/check_llms_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown check-llms option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"
  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("llms-check")
  [[ -n "$provider" ]] && cli_args+=("--provider" "$provider")
  [[ -n "$adapter" ]] && cli_args+=("--adapter" "$adapter")
  (( json )) && cli_args+=("--json")
  (( dry_run )) && cli_args+=("--dry-run")
  (( install_missing )) && cli_args+=("--install-missing")
   (( health_check )) && cli_args+=("--health-check")

  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
  return $?
}

