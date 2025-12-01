#!/usr/bin/env bash
# shellcheck shell=bash

cmd_list_agents() {
  local root="" client="" model="" active="" name_like="" limit="" json=0 verbose=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
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
      --active)
        active="${2:-}"
        shift 2
        ;;
      --name-like)
        name_like="${2:-}"
        shift 2
        ;;
      --limit)
        limit="${2:-}"
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
        if tmpl="$(gc_help_template_for_cmd list-agents)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/list_agents_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown list-agents option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("list")
  [[ -n "$client" ]] && cli_args+=("--client" "$client")
  [[ -n "$model" ]] && cli_args+=("--model" "$model")
  [[ -n "$active" ]] && cli_args+=("--active" "$active")
  [[ -n "$name_like" ]] && cli_args+=("--name-like" "$name_like")
  [[ -n "$limit" ]] && cli_args+=("--limit" "$limit")
  (( json )) && cli_args+=("--json")

  if (( json )); then
    gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
    return $?
  fi

  local output status
  if ! output="$(gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}")"; then
    status=$?
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
    return "$status"
  fi
  # The renderer only understands backlog/estimate payloads; disable it here to avoid noisy errors.
  if printf '%s\n' "$output" | GC_RENDERER_DISABLED=1 gc_render_with_renderer column -ts $'\t'; then
    return 0
  fi
  return 1
}
