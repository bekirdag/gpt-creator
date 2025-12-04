#!/usr/bin/env bash
# shellcheck shell=bash

cmd_tokens() {
  local root="" details=0 json_output=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --details)
        details=1
        shift
        ;;
      --json)
        json_output=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd tokens)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/tokens_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown tokens option: $1"
        ;;
    esac
  done

  ensure_ctx "$root"
  local project_root="${PROJECT_ROOT:-$PWD}"

  local log_dir="${project_root}/.gpt-creator/logs"
  local default_usage="${log_dir}/usage.ndjson"
  local legacy_usage="${log_dir}/codex-usage.ndjson"
  local usage_file="${GC_USAGE_FILE:-$default_usage}"
  if [[ ! -f "$usage_file" && -f "$legacy_usage" ]]; then
    usage_file="$legacy_usage"
  fi
  if [[ ! -f "$usage_file" ]]; then
    warn "No usage data found at ${usage_file}. Set GC_USAGE_FILE to point at a usage log or run an adapter task first."
    return 1
  fi
  local helper_path
  helper_path="$(gc_clone_python_tool "tokens_report.py" "$project_root")" || return 1
  if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 not found; cannot render token report."
    return 1
  fi
  python3 "$helper_path" "$usage_file" "$details" "$json_output"
}
