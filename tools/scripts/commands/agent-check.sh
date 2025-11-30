#!/usr/bin/env bash
# shellcheck shell=bash

cmd_agent_check() {
  local root="" name="" prompt="" client="" model="" json=0 verbose=0
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
      --prompt)
        prompt="${2:-}"
        shift 2
        ;;
      --client)
        client="${2:-}"
        shift 2
        ;;
      --model)
        model="${2:-}"
        shift 2
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
        if tmpl="$(gc_help_template_for_cmd agent-check)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/agent_check_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown agent-check option: $1"
        ;;
    esac
  done

  [[ -n "$name" ]] || die "--name is required for agent-check"
  [[ -n "$prompt" ]] || die "--prompt is required for agent-check"

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("agent-check" "--name" "$name" "--prompt" "$prompt")
  [[ -n "$client" ]] && cli_args+=("--client" "$client")
  [[ -n "$model" ]] && cli_args+=("--model" "$model")
  (( json )) && cli_args+=("--json")

  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
  return $?
}

