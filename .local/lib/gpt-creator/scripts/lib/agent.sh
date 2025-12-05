#!/usr/bin/env bash
# shellcheck shell=bash

# Resolve an agent into environment variables used by work-on-tasks/apply.
# Arguments:
#   $1 - agent name (may be empty to use defaults)
#   $2 - tasks.db path
#   $3 - project root (optional, defaults to $PROJECT_ROOT or $PWD)
gc_resolve_agent() {
  local agent_name="${1:-}"
  local tasks_db="${2:-}"
  local project_root="${3:-${PROJECT_ROOT:-$PWD}}"

  # Discover defaults from the registry or env (avoid hard-coded adapters/clients).
  local registry_defaults_helper=""
  registry_defaults_helper="$(gc_clone_python_tool "agents_registry_defaults.py" "$project_root" 2>/dev/null)" || registry_defaults_helper=""
  local registry_defaults=""
  if [[ -n "$registry_defaults_helper" ]]; then
    registry_defaults="$(${PYTHON_BIN:-python3} "$registry_defaults_helper" 2>/dev/null)" || registry_defaults=""
  fi
  local registry_default_client="" registry_default_adapter="" registry_default_model=""
  IFS=$'\n' read -r registry_default_client registry_default_adapter registry_default_model <<<"$registry_defaults"

  local default_model="${DEFAULT_LLM:-${registry_default_model:-}}"
  local default_client="${DEFAULT_AGENT_CLIENT:-${registry_default_client:-}}"
  local default_adapter="${DEFAULT_AGENT_ADAPTER:-${registry_default_adapter:-}}"

  unset GC_ACTIVE_AGENT_FILE GC_ACTIVE_AGENT_NAME GC_ACTIVE_AGENT_CLIENT GC_ACTIVE_AGENT_MODEL GC_ACTIVE_AGENT_ADAPTER GC_ACTIVE_AGENT_MAX_CONTEXT GC_ACTIVE_AGENT_MAX_OUTPUT GC_ACTIVE_AGENT_API_BASE GC_ACTIVE_AGENT_API_KEY_ENV GC_ACTIVE_AGENT_API_ORG_ENV GC_ACTIVE_AGENT_API_BASE_ENV
  unset GC_AGENT_FLAG

  if [[ -z "$agent_name" ]]; then
    if [[ -z "$default_model" || -z "$default_client" ]]; then
      die "No agent provided and no default client/model resolved (set DEFAULT_LLM/DEFAULT_AGENT_CLIENT or define a registry default)."
    fi
    export GC_ACTIVE_AGENT_CLIENT="$default_client"
    export GC_ACTIVE_AGENT_MODEL="$default_model"
    [[ -n "$default_adapter" ]] && export GC_ACTIVE_AGENT_ADAPTER="$default_adapter"
    export GC_AGENT_FLAG=0
    return 0
  fi

  [[ -f "$tasks_db" ]] || die "Tasks database not found at ${tasks_db}"

  local tmp_base="${GC_TMP_DIR:-${TMPDIR:-/tmp}}"
  mkdir -p "$tmp_base" 2>/dev/null || true
  local agent_tmp=""
  if ! agent_tmp="$(mktemp "${tmp_base%/}/agent-select.XXXXXX.json" 2>/dev/null)"; then
    agent_tmp="$(mktemp /tmp/agent-select.XXXXXX.json)"
  fi
  info "Resolving agent '${agent_name}' from ${tasks_db} [agent-resolve:v11]"

  # Ensure Python helpers (agents_registry, etc.) are discoverable.
  if [[ -n "${CLI_ROOT:-${GC_CLI_ROOT:-}}" ]]; then
    local _py_paths=("${CLI_ROOT:-${GC_CLI_ROOT}}/scripts/python" "${CLI_ROOT:-${GC_CLI_ROOT}}/tools/scripts/python")
    local _py_path
    for _py_path in "${_py_paths[@]}"; do
      if [[ -d "$_py_path" ]]; then
        if [[ -z "${PYTHONPATH:-}" ]]; then
          PYTHONPATH="$_py_path"
        else
          PYTHONPATH="$_py_path:${PYTHONPATH}"
        fi
      fi
    done
    export PYTHONPATH
  fi

  local select_output=""
  # Primary: CLI (includes composed prompt/adapter metadata).
  select_output="$(GC_AGENT_READONLY=1 gc_run_agents_cli "$project_root" "$tasks_db" select --name "$agent_name" 2>/dev/null || true)"
  if [[ -n "$select_output" ]]; then
    info "agent-resolve: CLI payload: ${select_output//[$'\n']/ }"
  else
    warn "agent-resolve: CLI payload empty; attempting direct SQLite read for '${agent_name}'"
  fi

  # Fallback: direct SQLite read (minimal payload).
  if [[ -z "$select_output" || "$select_output" != *'"kind": "agent"'* ]]; then
    local sqlite_helper=""
    sqlite_helper="$(gc_clone_python_tool "agents_sqlite_fetch.py" "$project_root" 2>/dev/null)" || sqlite_helper=""
    if [[ -n "$sqlite_helper" ]]; then
      select_output="$("${PYTHON_BIN:-python3}" "$sqlite_helper" "$tasks_db" "$agent_name" 2>/dev/null)" || true
    fi
    if [[ -n "$select_output" ]]; then
      warn "agent-resolve: using fallback SQLite payload (prompt/adapter metadata may be missing)"
      info "agent-resolve: SQLite payload: ${select_output//[$'\n']/ }"
    else
      warn "agent-resolve: direct SQLite read returned empty payload"
    fi
  fi

  if [[ -z "$select_output" || "$select_output" != *'"kind": "agent"'* ]]; then
    rm -f "$agent_tmp"
    warn "agent-resolve: no agent payload after CLI/SQLite attempts (payload='${select_output//[$'\n']/ }')"
    die "Agent '${agent_name}' not found in tasks database"
  fi

  # Persist the raw payload for downstream consumers.
  printf '%s\n' "$select_output" >"$agent_tmp"

  # Resolve fields from the JSON payload (prefer CLI prompt-enriched data).
  local resolved_kind="" resolved_client="" resolved_model="" resolved_name="" resolved_api_key="" resolved_api_base="" resolved_api_org="" resolved_adapter="" resolved_ctx="" resolved_out="" resolved_api_key_env="" resolved_api_base_env="" resolved_api_org_env=""
  local parsed_output=""
  local parse_helper=""
  parse_helper="$(gc_clone_python_tool "agents_parse_payload.py" "$project_root" 2>/dev/null)" || parse_helper=""
  if [[ -n "$parse_helper" ]]; then
    parsed_output="$(${PYTHON_BIN:-python3} "$parse_helper" "$agent_tmp" 2>/dev/null)" || true
  fi
  IFS=$'\t' read -r resolved_kind resolved_client resolved_model resolved_name resolved_api_key resolved_api_base resolved_api_org resolved_adapter resolved_ctx resolved_out resolved_api_key_env resolved_api_base_env resolved_api_org_env <<<"$parsed_output"

  info "agent-resolve: parsed client=${resolved_client:-<empty>} model=${resolved_model:-<empty>} name=${resolved_name:-<empty>}"

  if [[ "$resolved_kind" != "agent" || -z "$resolved_model" || -z "$resolved_client" || -z "$resolved_name" ]]; then
    rm -f "$agent_tmp"
    warn "agent-resolve: parsed payload invalid (kind='${resolved_kind:-<empty>}' client='${resolved_client:-<empty>}' model='${resolved_model:-<empty>}' name='${resolved_name:-<empty>}')"
    die "Agent '${agent_name}' not found in tasks database"
  fi

  # Fill adapter metadata from registry.
  local registry_info adapter_parse_output agent_adapter="" agent_ctx="" agent_out="" agent_api_base="" agent_api_key_env="" agent_org_env="" agent_api_base_env="" agent_registry_model=""
  if registry_info="$(gc_agents_registry_cmd validate --client "$resolved_client" --model "$resolved_model" 2>/dev/null)"; then
    :
  else
    local registry_helper=""
    registry_helper="$(gc_clone_python_tool "agents_registry.py" "$project_root" 2>/dev/null)" || registry_helper=""
    if [[ -n "$registry_helper" ]]; then
      registry_info="$("${PYTHON_BIN:-python3}" "$registry_helper" validate --client "$resolved_client" --model "$resolved_model" 2>/dev/null)" || registry_info=""
    fi
  fi
  if [[ -n "$registry_info" ]]; then
    local registry_parse_helper=""
    registry_parse_helper="$(gc_clone_python_tool "agents_parse_registry_info.py" "$project_root" 2>/dev/null)" || registry_parse_helper=""
    if [[ -n "$registry_parse_helper" ]]; then
      adapter_parse_output="$("${PYTHON_BIN:-python3}" "$registry_parse_helper" "$registry_info" 2>/dev/null)"
    fi
    IFS=$'\n' read -r agent_adapter agent_ctx agent_out agent_api_base agent_api_key_env agent_org_env agent_api_base_env agent_registry_model <<<"$adapter_parse_output"
    if [[ -n "$agent_registry_model" ]]; then
      resolved_model="$agent_registry_model"
    fi
    [[ -n "$agent_adapter" ]] && export GC_ACTIVE_AGENT_ADAPTER="$agent_adapter"
    [[ -n "$agent_ctx" ]] && export GC_ACTIVE_AGENT_MAX_CONTEXT="$agent_ctx"
    [[ -n "$agent_out" ]] && export GC_ACTIVE_AGENT_MAX_OUTPUT="$agent_out"
    [[ -n "$agent_api_base" ]] && export GC_ACTIVE_AGENT_API_BASE="$agent_api_base"
    [[ -n "$agent_api_key_env" ]] && export GC_ACTIVE_AGENT_API_KEY_ENV="$agent_api_key_env"
    [[ -n "$agent_org_env" ]] && export GC_ACTIVE_AGENT_API_ORG_ENV="$agent_org_env"
    [[ -n "$agent_api_base_env" ]] && export GC_ACTIVE_AGENT_API_BASE_ENV="$agent_api_base_env"
  fi

  export GC_ACTIVE_AGENT_FILE="$agent_tmp"
  export GC_ACTIVE_AGENT_NAME="$resolved_name"
  export GC_ACTIVE_AGENT_CLIENT="$resolved_client"
  export GC_ACTIVE_AGENT_MODEL="$resolved_model"
  export GC_AGENT_FLAG=1
  [[ -z "${GC_ACTIVE_AGENT_ADAPTER:-}" && -n "$resolved_adapter" ]] && export GC_ACTIVE_AGENT_ADAPTER="$resolved_adapter"
  [[ -z "${GC_ACTIVE_AGENT_MAX_CONTEXT:-}" && -n "$resolved_ctx" ]] && export GC_ACTIVE_AGENT_MAX_CONTEXT="$resolved_ctx"
  [[ -z "${GC_ACTIVE_AGENT_MAX_OUTPUT:-}" && -n "$resolved_out" ]] && export GC_ACTIVE_AGENT_MAX_OUTPUT="$resolved_out"
  [[ -z "${GC_ACTIVE_AGENT_API_BASE:-}" && -n "$resolved_api_base" ]] && export GC_ACTIVE_AGENT_API_BASE="$resolved_api_base"
  [[ -z "${GC_ACTIVE_AGENT_API_KEY_ENV:-}" && -n "$resolved_api_key_env" ]] && export GC_ACTIVE_AGENT_API_KEY_ENV="$resolved_api_key_env"
  [[ -z "${GC_ACTIVE_AGENT_API_ORG_ENV:-}" && -n "$resolved_api_org_env" ]] && export GC_ACTIVE_AGENT_API_ORG_ENV="$resolved_api_org_env"
  [[ -z "${GC_ACTIVE_AGENT_API_BASE_ENV:-}" && -n "$resolved_api_base_env" ]] && export GC_ACTIVE_AGENT_API_BASE_ENV="$resolved_api_base_env"
  if [[ -z "${GC_ACTIVE_AGENT_ADAPTER:-}" && -n "$default_adapter" ]]; then
    export GC_ACTIVE_AGENT_ADAPTER="$default_adapter"
  fi

  # Enrich the agent file with registry defaults (adapter/config/limits), mirroring test-agent.
  if [[ -n "$agent_tmp" && -f "$agent_tmp" ]]; then
    local enrich_helper=""
    enrich_helper="$(gc_clone_python_tool "agents_enrich_file.py" "$project_root" 2>/dev/null)" || enrich_helper=""
    if [[ -n "$enrich_helper" ]]; then
      "${PYTHON_BIN:-python3}" "$enrich_helper" "$agent_tmp" "$registry_info" || true
    fi
  fi

  # Apply any inline values from the agent record.
  if [[ -n "$resolved_api_base" ]]; then
    export GC_ACTIVE_AGENT_API_BASE="$resolved_api_base"
    if [[ -n "${GC_ACTIVE_AGENT_API_BASE_ENV:-}" ]]; then
      export "${GC_ACTIVE_AGENT_API_BASE_ENV}"="$resolved_api_base"
    fi
  fi
  if [[ -n "${GC_ACTIVE_AGENT_API_KEY_ENV:-}" && -n "$resolved_api_key" ]]; then
    export "${GC_ACTIVE_AGENT_API_KEY_ENV}"="$resolved_api_key"
  fi
  if [[ -n "${GC_ACTIVE_AGENT_API_ORG_ENV:-}" && -n "$resolved_api_org" ]]; then
    export "${GC_ACTIVE_AGENT_API_ORG_ENV}"="$resolved_api_org"
  fi

  # Fallback to default adapter if registry lacks one.
  if [[ -z "${GC_ACTIVE_AGENT_ADAPTER:-}" ]]; then
    export GC_ACTIVE_AGENT_ADAPTER="$default_adapter"
  fi
  return 0
}
