#!/usr/bin/env bash
# shellcheck shell=bash

cmd_install_llm() {
  local root="" provider="" adapter="" os_choice="default" json=0 dry_run=0 run=0 yes=0 verbose=0
  case "${GC_DRY_RUN:-}" in
    1|true|yes|on) dry_run=1 ;;
  esac
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
      --os)
        os_choice="${2:-default}"
        shift 2
        ;;
      --run)
        run=1
        shift
        ;;
      --yes)
        yes=1
        shift
        ;;
      --dry-run)
        dry_run=1
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
        if tmpl="$(gc_help_template_for_cmd install-llm)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/install_llm_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown install-llm option: $1"
        ;;
    esac
  done
  [[ -n "$provider" ]] || die "--provider is required for install-llm"

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("install-llm" "--provider" "$provider" "--os" "$os_choice")
  [[ -n "$adapter" ]] && cli_args+=("--adapter" "$adapter")
  (( json )) && cli_args+=("--json")
  (( dry_run )) && cli_args+=("--dry-run")
  (( run )) && cli_args+=("--run")
  (( yes )) && cli_args+=("--yes")

  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
  return $?
}
