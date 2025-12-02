#!/usr/bin/env bash
# shellcheck shell=bash

cmd_work_on_tasks() {
  if ! declare -F _cmd_work_on_tasks_impl >/dev/null 2>&1; then
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck source=scripts/commands/work_on_tasks_impl.sh
    . "${script_dir}/work_on_tasks_impl.sh"
  fi
  _cmd_work_on_tasks_impl "$@"
}
