#!/usr/bin/env bash
# shellcheck shell=bash

cmd_create_jira_tasks() {
  local args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        args+=(--project "$(abs_path "$2")")
        shift 2
        ;;
      --model)
        args+=(--model "$2")
        shift 2
        ;;
      --force|--dry-run)
        args+=("$1")
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd create-jira-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/create_jira_tasks_usage.txt"
        fi
        return 0
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done

  local shell_bin="${BASH:-bash}"
  "$shell_bin" "$CLI_ROOT/src/cli/create-jira-tasks.sh" "${args[@]}"
}
