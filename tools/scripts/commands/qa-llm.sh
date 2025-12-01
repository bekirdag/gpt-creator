#!/usr/bin/env bash
# shellcheck shell=bash

cmd_qa_llm() {
  local root=""
  local db_path=""
  local agent_name=""
  local client_override=""
  local model_override=""
  local task_ref=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --db) db_path="$2"; shift 2;;
      --agent) agent_name="$2"; shift 2;;
      --client) client_override="$2"; shift 2;;
      --model) model_override="$2"; shift 2;;
      --task) task_ref="$2"; shift 2;;
      *) break;;
    esac
  done

  ensure_ctx "$root"
  local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
  local helper="${scripts_root}/python/qa_llm.py"
  [[ -f "$helper" ]] || die "qa-llm helper missing at ${helper}"
  local -a cmd=("${PYTHON_BIN:-python3}" "$helper" --project "${PROJECT_ROOT}")
  [[ -n "$db_path" ]] && cmd+=("--db" "$db_path")
  [[ -n "$agent_name" ]] && cmd+=("--agent" "$agent_name")
  [[ -n "$client_override" ]] && cmd+=("--client" "$client_override")
  [[ -n "$model_override" ]] && cmd+=("--model" "$model_override")
  [[ -n "$task_ref" ]] && cmd+=("--task" "$task_ref")
  "${cmd[@]}"
}

