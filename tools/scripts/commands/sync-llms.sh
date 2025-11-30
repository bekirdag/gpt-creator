#!/usr/bin/env bash
# shellcheck shell=bash

cmd_sync_llms() {
  local root="" provider="" model="" refresh=0 json=0 verbose=0 require_adapters=0 require_keys=0 ci_mode=0
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
      --model)
        model="${2:-}"
        shift 2
        ;;
      --refresh)
        refresh=1
        shift
        ;;
      --require-adapters)
        require_adapters=1
        shift
        ;;
      --require-keys)
        require_keys=1
        shift
        ;;
      --ci)
        ci_mode=1
        json=1
        require_adapters=1
        require_keys=1
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
        if tmpl="$(gc_help_template_for_cmd sync-llms)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/sync_llms_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown sync-llms option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("llms-sync")
  [[ -n "$provider" ]] && cli_args+=("--provider" "$provider")
  [[ -n "$model" ]] && cli_args+=("--model" "$model")
  (( refresh )) && cli_args+=("--refresh")
  (( require_adapters )) && cli_args+=("--require-adapters")
  (( require_keys )) && cli_args+=("--require-keys")
  (( ci_mode )) && cli_args+=("--ci")
  (( json )) && cli_args+=("--json")

  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
  return $?
}

