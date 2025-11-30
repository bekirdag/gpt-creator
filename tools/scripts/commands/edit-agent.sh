#!/usr/bin/env bash
# shellcheck shell=bash

cmd_edit_agent() {
  local root="" name="" new_name="" client="" model="" job_doc="" character_doc="" tags="" active="" resummarize=0 summarize=0 json=0 verbose=0 allow_missing_key=0 guardrails=""
  local summarize_model="" summarize_client=""
  local -a guardrails_files=() guardrails_dirs=()
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
      --new-name)
        new_name="${2:-}"
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
      --job-doc)
        job_doc="${2:-}"
        shift 2
        ;;
      --character-doc)
        character_doc="${2:-}"
        shift 2
        ;;
      --tags)
        tags="${2:-}"
        shift 2
        ;;
      --active)
        active="${2:-}"
        shift 2
        ;;
      --resummarize)
        resummarize=1
        shift
        ;;
      --summarize)
        summarize=1
        shift
        ;;
      --summarize-model)
        summarize_model="${2:-}"
        shift 2
        ;;
      --summarize-client)
        summarize_client="${2:-}"
        shift 2
        ;;
      --guardrails)
        guardrails="${2:-}"
        shift 2
        ;;
      --guardrails-file)
        guardrails_files+=("${2:-}")
        shift 2
        ;;
      --guardrails-dir)
        guardrails_dirs+=("${2:-}")
        shift 2
        ;;
      --json)
        json=1
        shift
        ;;
      --allow-missing-key)
        allow_missing_key=1
        shift
        ;;
      --verbose)
        verbose=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd edit-agent)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/edit_agent_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown edit-agent option: $1"
        ;;
    esac
  done

  [[ -n "$name" ]] || die "--name is required for edit-agent"

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local -a cli_args=()
  (( verbose )) && cli_args+=("--verbose")
  cli_args+=("edit" "--name" "$name")
  [[ -n "$new_name" ]] && cli_args+=("--new-name" "$new_name")
  [[ -n "$client" ]] && cli_args+=("--client" "$client")
  [[ -n "$model" ]] && cli_args+=("--model" "$model")
  [[ -n "$job_doc" ]] && cli_args+=("--job-doc" "$job_doc")
  [[ -n "$character_doc" ]] && cli_args+=("--character-doc" "$character_doc")
  [[ -n "$tags" ]] && cli_args+=("--tags" "$tags")
  [[ -n "$guardrails" ]] && cli_args+=("--guardrails" "$guardrails")
  if ((${#guardrails_files[@]})); then
    for file in "${guardrails_files[@]}"; do
      cli_args+=("--guardrails-file" "$file")
    done
  fi
  if ((${#guardrails_dirs[@]})); then
    for dir in "${guardrails_dirs[@]}"; do
      cli_args+=("--guardrails-dir" "$dir")
    done
  fi
  [[ -n "$active" ]] && cli_args+=("--active" "$active")
  (( resummarize )) && cli_args+=("--resummarize")
  (( summarize )) && cli_args+=("--summarize")
  [[ -n "$summarize_model" ]] && cli_args+=("--summarize-model" "$summarize_model")
  [[ -n "$summarize_client" ]] && cli_args+=("--summarize-client" "$summarize_client")
  (( json )) && cli_args+=("--json")
  (( allow_missing_key )) && cli_args+=("--allow-missing-key")

  if (( json )); then
    local output status
    if ! output="$(gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}")"; then
      status=$?
      if [[ -n "$output" ]]; then
        printf '%s\n' "$output"
      fi
      return "$status"
    fi
    printf '%s\n' "$output" | gc_agents_emit_agent_json 2
    return 0
  fi

  gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" "${cli_args[@]}"
  return $?
}

