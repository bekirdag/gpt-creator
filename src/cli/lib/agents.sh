#!/usr/bin/env bash

# Agent helpers for CLI commands that want to resolve --agent NAME into a model.

gc_cli_agent_db_path() {
  local project="${1:-$PWD}"
  local abs_path
  abs_path="$(cd "$project" && pwd)"
  printf '%s/.gpt-creator/staging/plan/tasks/tasks.db' "$abs_path"
}

gc_cli__log() {
  printf '[agents] %s\n' "$1"
}

gc_cli__registry_validate() {
  local client="$1" model="$2"
  local scripts_root="${GC_SCRIPTS_ROOT:-${ROOT_DIR}/scripts}"
  local registry_script="${scripts_root}/python/agents_registry.py"
  [[ -f "$registry_script" ]] || return 1
  "${PYTHON_BIN:-python3}" "$registry_script" validate --client "$client" --model "$model"
}

gc_cli__agents_helper_path() {
  local helper="${1:?python helper name required}"
  local project="${2:-${PROJECT_ROOT:-$PWD}}"
  if declare -f gc_clone_python_tool >/dev/null 2>&1; then
    gc_clone_python_tool "$helper" "$project"
    return
  fi
  if declare -f gc::clone_python_tool >/dev/null 2>&1; then
    gc::clone_python_tool "$helper" "$project"
    return
  fi
  local cli_root="${GC_ROOT:-${CLI_ROOT:-${ROOT_DIR:-}}}"
  local scripts_root="${GC_SCRIPTS_ROOT:-${cli_root}/scripts}"
  if [[ -n "$cli_root" && -f "${scripts_root}/python/${helper}" ]]; then
    printf '%s/python/%s\n' "$scripts_root" "$helper"
    return 0
  fi
  return 1
}

gc_cli__registry_adapter_helper() {
  local project="${1:-${PROJECT_ROOT:-$PWD}}"
  local helper="agents_registry_adapter_info.py"
  gc_cli__agents_helper_path "$helper" "$project"
}

gc_cli__apply_agent_env() {
  local project="${1:-${PROJECT_ROOT:-$PWD}}"
  local client="$2" model="$3" name="$4" agent_file="$5"
  local stored_key="$6" stored_base="$7" stored_org="$8"
  export GC_ACTIVE_AGENT_FILE="$agent_file"
  export GC_ACTIVE_AGENT_NAME="$name"
  export GC_ACTIVE_AGENT_CLIENT="$client"
  export GC_ACTIVE_AGENT_MODEL="$model"
  local registry_json adapter_info
  registry_json="$(
    gc_cli__registry_validate "$client" "$model" 2>/dev/null
  )"
  local agent_adapter="" agent_ctx="" agent_out="" agent_api_base="" agent_api_key_env="" agent_org_env="" agent_api_base_env=""
  if [[ -n "$registry_json" ]]; then
    local helper_path
    helper_path="$(gc_cli__registry_adapter_helper "$project")" || helper_path=""
    if [[ -n "$helper_path" ]]; then
      adapter_info="$(${PYTHON_BIN:-python3} "$helper_path" <<<"$registry_json")" || adapter_info=""
    fi
    IFS=$'\n' read -r agent_adapter agent_ctx agent_out agent_api_base agent_api_key_env agent_org_env agent_api_base_env <<<"$adapter_info"
    [[ -n "$agent_adapter" ]] && export GC_ACTIVE_AGENT_ADAPTER="$agent_adapter"
    [[ -n "$agent_ctx" ]] && export GC_ACTIVE_AGENT_MAX_CONTEXT="$agent_ctx"
    [[ -n "$agent_out" ]] && export GC_ACTIVE_AGENT_MAX_OUTPUT="$agent_out"
    [[ -n "$agent_api_base" ]] && export GC_ACTIVE_AGENT_API_BASE="$agent_api_base"
    [[ -n "$agent_api_key_env" ]] && export GC_ACTIVE_AGENT_API_KEY_ENV="$agent_api_key_env"
    [[ -n "$agent_org_env" ]] && export GC_ACTIVE_AGENT_API_ORG_ENV="$agent_org_env"
    [[ -n "$agent_api_base_env" ]] && export GC_ACTIVE_AGENT_API_BASE_ENV="$agent_api_base_env"
  fi
  if [[ -n "$stored_base" ]]; then
    export GC_ACTIVE_AGENT_API_BASE="$stored_base"
    if [[ -n "$agent_api_base_env" ]]; then
      export "$agent_api_base_env"="$stored_base"
    fi
  fi
  if [[ -n "$agent_api_key_env" && -n "$stored_key" ]]; then
    export "$agent_api_key_env"="$stored_key"
  fi
  if [[ -n "$agent_org_env" && -n "$stored_org" ]]; then
    export "$agent_org_env"="$stored_org"
  fi
  gc_cli__log "Agent '${name}' active (client=${client}, model=${model}${agent_adapter:+, adapter=${agent_adapter}})."
}

gc_cli_resolve_agent_model() {
  local project="${1:?project path required}" agent_name="${2:?agent name required}"
  local db_path helper output tmp_root tmp_dir agent_tmp parse_output
  db_path="$(gc_cli_agent_db_path "$project")"
  if [[ ! -f "$db_path" ]]; then
    printf ''
    return 1
  fi
  helper="${GC_SCRIPTS_ROOT:-${ROOT_DIR}/scripts}/python/agents_cli.py"
  if [[ ! -f "$helper" ]]; then
    printf ''
    return 1
  fi
  if ! output="$(${PYTHON_BIN:-python3} "$helper" --project "$project" --db-path "$db_path" select --name "$agent_name" 2>/dev/null)"; then
    printf ''
    return 1
  fi
  tmp_root="${GC_DIR:-$project/.gpt-creator}"
  tmp_dir="$tmp_root/tmp"
  mkdir -p "$tmp_dir"
  agent_tmp="$(mktemp "$tmp_dir/agent-select.XXXXXX.json" 2>/dev/null || mktemp)"
  local parse_helper
  if ! parse_helper="$(gc_cli__agents_helper_path "agents_cli_parse_selection.py" "$project")"; then
    rm -f "$agent_tmp"
    printf ''
    return 1
  fi
  if ! parse_output="$(${PYTHON_BIN:-python3} "$parse_helper" "$agent_tmp" <<<"$output")"; then
    rm -f "$agent_tmp"
    printf ''
    return 1
  fi
  local resolved_kind resolved_client resolved_model resolved_name resolved_api_key resolved_api_base resolved_api_org
  IFS=$'\n' read -r resolved_kind resolved_client resolved_model resolved_name resolved_api_key resolved_api_base resolved_api_org <<<"$parse_output"
  if [[ "$resolved_kind" == "agent" && -n "$resolved_model" ]]; then
    gc_cli__apply_agent_env "$project" "$resolved_client" "$resolved_model" "$resolved_name" "$agent_tmp" "$resolved_api_key" "$resolved_api_base" "$resolved_api_org"
    printf '%s\n' "$resolved_model"
    return 0
  fi
  rm -f "$agent_tmp"
  if [[ "$resolved_kind" == "model" && -n "$resolved_model" ]]; then
    printf '%s\n' "$resolved_model"
    return 0
  fi
  printf ''
  return 1
}
