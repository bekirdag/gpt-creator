#!/usr/bin/env bash
# shellcheck shell=bash

cmd_list_llms() {
  local root="" provider="" adapter="" source="" model="" name_like="" limit="" json=0 verbose=0 warn_keys=1 needs_key=0
  local -a statuses=()
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
      --source)
        source="${2:-}"
        shift 2
        ;;
      --model)
        model="${2:-}"
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
      --status)
        statuses+=("${2:-}")
        shift 2
        ;;
      --needs-key)
        needs_key=1
        shift
        ;;
      --warn-keys)
        warn_keys=1
        shift
        ;;
      --no-warn-keys)
        warn_keys=0
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
        if tmpl="$(gc_help_template_for_cmd list-llms)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/list_llms_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown list-llms option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("llms")
  [[ -n "$provider" ]] && cli_args+=("--provider" "$provider")
  [[ -n "$adapter" ]] && cli_args+=("--adapter" "$adapter")
  [[ -n "$source" ]] && cli_args+=("--source" "$source")
  [[ -n "$model" ]] && cli_args+=("--model" "$model")
  [[ -n "$name_like" ]] && cli_args+=("--name-like" "$name_like")
  [[ -n "$limit" ]] && cli_args+=("--limit" "$limit")
  if ((${#statuses[@]})); then
    for status in "${statuses[@]}"; do
      [[ -n "$status" ]] && cli_args+=("--status" "$status")
    done
  fi
  if (( needs_key )); then
    cli_args+=("--needs-key")
    (( warn_keys )) || cli_args+=("--no-warn-keys")
  else
    (( warn_keys )) || cli_args+=("--no-warn-keys")
  fi
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
  if printf '%s\n' "$output" | gc_render_with_renderer column -ts $'\t'; then
    return 0
  fi
  return 1
}
