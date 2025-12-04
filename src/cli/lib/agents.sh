#!/usr/bin/env bash

# Agent helpers for CLI commands that want to resolve --agent NAME into a model.

gc_cli_agent_db_path() {
  local project="${1:-$PWD}"
  local override="${GC_TASKS_DB_PATH:-${GC_TASKS_DB:-}}"
  local abs_project
  abs_project="$(cd "$project" && pwd)"
  if [[ -n "$override" ]]; then
    if [[ "$override" = /* ]]; then
      printf '%s' "$override"
    else
      printf '%s/%s' "$abs_project" "$override"
    fi
    return
  fi
  local dir_base="${GC_DIR:-${abs_project}/.gpt-creator}"
  printf '%s/staging/plan/tasks/tasks.db' "$dir_base"
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
  # Fallback: hydrate adapter/limits/api hints from the agent file when registry data is missing.
  if [[ -f "$agent_file" ]]; then
    local file_meta
    file_meta="$(${PYTHON_BIN:-python3} - <<'PY' "$agent_file"
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
agent = data.get("agent") or {}
if not isinstance(agent, dict):
    agent = data
resolved = data.get("resolved") or {}
def pick(*values):
    for value in values:
        if value:
            return value
    return ""
adapter = pick(resolved.get("adapter"), agent.get("adapter"))
max_ctx = pick(resolved.get("maxContextTokens"), agent.get("maxContextTokens"))
max_out = pick(resolved.get("maxOutputTokens"), agent.get("maxOutputTokens"))
api_base = pick(resolved.get("apiBase"), agent.get("client_api_base"))
api_key_env = pick(agent.get("client_api_key_env"), resolved.get("apiKeyEnv"))
org_env = pick(agent.get("client_api_org_env"), resolved.get("orgEnv"))
api_base_env = pick(agent.get("client_api_base_env"), resolved.get("apiBaseEnv"))
print("\\n".join([adapter or "", str(max_ctx or ""), str(max_out or ""), api_base or "", api_key_env or "", org_env or "", api_base_env or ""]))
PY
)"
    local file_adapter file_ctx file_out file_api_base file_api_key_env file_org_env file_api_base_env
    IFS=$'\n' read -r file_adapter file_ctx file_out file_api_base file_api_key_env file_org_env file_api_base_env <<<"$file_meta"
    [[ -z "${GC_ACTIVE_AGENT_ADAPTER:-}" && -n "$file_adapter" ]] && export GC_ACTIVE_AGENT_ADAPTER="$file_adapter"
    [[ -z "${GC_ACTIVE_AGENT_MAX_CONTEXT:-}" && -n "$file_ctx" ]] && export GC_ACTIVE_AGENT_MAX_CONTEXT="$file_ctx"
    [[ -z "${GC_ACTIVE_AGENT_MAX_OUTPUT:-}" && -n "$file_out" ]] && export GC_ACTIVE_AGENT_MAX_OUTPUT="$file_out"
    [[ -z "${GC_ACTIVE_AGENT_API_BASE:-}" && -n "$file_api_base" ]] && export GC_ACTIVE_AGENT_API_BASE="$file_api_base"
    [[ -z "${GC_ACTIVE_AGENT_API_KEY_ENV:-}" && -n "$file_api_key_env" ]] && export GC_ACTIVE_AGENT_API_KEY_ENV="$file_api_key_env"
    [[ -z "${GC_ACTIVE_AGENT_API_ORG_ENV:-}" && -n "$file_org_env" ]] && export GC_ACTIVE_AGENT_API_ORG_ENV="$file_org_env"
    [[ -z "${GC_ACTIVE_AGENT_API_BASE_ENV:-}" && -n "$file_api_base_env" ]] && export GC_ACTIVE_AGENT_API_BASE_ENV="$file_api_base_env"
  fi
  local log_adapter="${GC_ACTIVE_AGENT_ADAPTER:-$agent_adapter}"
  gc_cli__log "Agent '${name}' active (client=${client}, model=${model}${log_adapter:+, adapter=${log_adapter}})."
}

gc_cli_resolve_agent_model() {
  local project="${1:?project path required}" agent_name="${2:?agent name required}"
  local db_path helper output tmp_root tmp_dir agent_tmp parse_output
  db_path="$(gc_cli_agent_db_path "$project")"
  if [[ ! -f "$db_path" ]]; then
    printf ''
    return 1
  fi
  local scripts_root="${GC_SCRIPTS_ROOT:-${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}/scripts}"
  helper="${scripts_root}/python/agents_cli.py"
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
    rm -f "$agent_tmp"
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
