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

  local project_root=""
  if [[ -n "$root" ]]; then
    project_root="$root"
  elif [[ -n "${PROJECT_ROOT:-}" ]]; then
    project_root="$PROJECT_ROOT"
  else
    project_root="$PWD"
  fi

  local usage_file="${project_root}/.gpt-creator/logs/codex-usage.ndjson"
  if [[ ! -f "$usage_file" ]]; then
    warn "No Codex usage data found at ${usage_file}. Run a codex-enabled command first."
    return 1
  fi
  local helper_path
  helper_path="$(gc_clone_python_tool "tokens_report.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$usage_file" "$details" "$json_output"
}


