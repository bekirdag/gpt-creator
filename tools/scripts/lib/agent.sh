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

  # Defaults when no agent is provided.
  local default_model="${DEFAULT_LLM:-${CODEX_MODEL:-gpt-5.1-codex-max}}"
  local default_client="openai"
  local default_adapter="codex_cli"

  unset GC_ACTIVE_AGENT_FILE GC_ACTIVE_AGENT_NAME GC_ACTIVE_AGENT_CLIENT GC_ACTIVE_AGENT_MODEL GC_ACTIVE_AGENT_ADAPTER GC_ACTIVE_AGENT_MAX_CONTEXT GC_ACTIVE_AGENT_MAX_OUTPUT GC_ACTIVE_AGENT_API_BASE GC_ACTIVE_AGENT_API_KEY_ENV GC_ACTIVE_AGENT_API_ORG_ENV GC_ACTIVE_AGENT_API_BASE_ENV
  unset GC_AGENT_FLAG

  if [[ -z "$agent_name" ]]; then
    export GC_ACTIVE_AGENT_CLIENT="$default_client"
    export GC_ACTIVE_AGENT_MODEL="$default_model"
    export GC_ACTIVE_AGENT_ADAPTER="$default_adapter"
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
  info "Resolving agent '${agent_name}' from ${tasks_db}"

  local select_output=""
  # Primary: direct SQLite read (immutable/ro) to avoid env/CLI side effects.
  select_output="$("${PYTHON_BIN:-python3}" - <<'PY' "$tasks_db" "$agent_name"
import json, sqlite3, sys
db_path = sys.argv[1]
name = (sys.argv[2] or "").strip().lower()
if not name:
    sys.exit(2)
uri = f"file:{db_path}?mode=ro&immutable=1"
try:
    conn = sqlite3.connect(uri, uri=True)
except Exception:
    conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM agents WHERE name_normalized = ?", (name,)).fetchone()
conn.close()
if not row:
    sys.exit(1)
agent = dict(row)
agent.setdefault("name", agent.get("name_normalized", ""))
print(json.dumps({"kind": "agent", "agent": agent}))
PY
)" || true
  if [[ -z "$select_output" ]]; then
    warn "agent-resolve: direct SQLite read returned empty payload"
  else
    info "agent-resolve: direct SQLite payload: ${select_output//[$'\n']/ }"
  fi
  # Fallback: CLI in read-only mode if direct read fails.
  if [[ -z "$select_output" || "$select_output" == *'"kind": "model"'* || "$select_output" != *'"kind":'* ]]; then
    warn "agent-resolve: direct SQLite read failed; retrying via agents CLI for '${agent_name}'"
    select_output="$(GC_AGENT_READONLY=1 gc_run_agents_cli "$project_root" "$tasks_db" select --name "$agent_name" 2>/dev/null || true)"
    if [[ -n "$select_output" ]]; then
      info "agent-resolve: CLI payload: ${select_output//[$'\n']/ }"
    else
      warn "agent-resolve: CLI payload empty"
    fi
  fi
  if [[ -z "$select_output" || "$select_output" == *'"kind": "model"'* || "$select_output" != *'"kind":'* ]]; then
    rm -f "$agent_tmp"
    warn "agent-resolve: no agent payload after SQLite + CLI attempts (payload='${select_output//[$'\n']/ }')"
    die "Agent '${agent_name}' not found in tasks database"
  fi

  local parse_output=""
  parse_output="$("${PYTHON_BIN:-python3}" - "$agent_tmp" "$select_output" <<'PY'
import json, sys
tmp_path = sys.argv[1] if len(sys.argv) > 1 else ""
raw = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
try:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected object")
except Exception:
    data = {}
kind = data.get("kind")
if kind == "agent":
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    agent = data.get("agent") or {}
    print("agent")
    print(agent.get("client", ""))
    print(agent.get("model", ""))
    print(agent.get("name", ""))
    print(agent.get("client_api_key", ""))
    print(agent.get("client_api_base", ""))
    print(agent.get("client_api_org", ""))
elif kind == "model":
    print("model")
    print("")
    print(data.get("model", ""))
    print("")
    print("")
    print("")
    print("")
else:
    print("unknown")
    print("")
    print("")
    print("")
    print("")
    print("")
PY
)" || {
    rm -f "$agent_tmp"
    die "Failed to parse agent selection for '${agent_name}'"
  }

  local resolved_kind resolved_client resolved_model resolved_name resolved_api_key resolved_api_base resolved_api_org
  IFS=$'\n' read -r resolved_kind resolved_client resolved_model resolved_name resolved_api_key resolved_api_base resolved_api_org <<<"$parse_output"

  if [[ "$resolved_kind" != "agent" || -z "$resolved_model" ]]; then
    rm -f "$agent_tmp"
    die "Agent '${agent_name}' not found in tasks database"
  fi

  export GC_ACTIVE_AGENT_FILE="$agent_tmp"
  export GC_ACTIVE_AGENT_NAME="$resolved_name"
  export GC_ACTIVE_AGENT_CLIENT="$resolved_client"
  export GC_ACTIVE_AGENT_MODEL="$resolved_model"
  export GC_AGENT_FLAG=1

  # Fill adapter metadata from registry.
  local registry_info adapter_parse_output agent_adapter="" agent_ctx="" agent_out="" agent_api_base="" agent_api_key_env="" agent_org_env="" agent_api_base_env=""
  # Primary: shell helper (may be unavailable in some contexts)
  if registry_info="$(gc_agents_registry_cmd validate --client "$resolved_client" --model "$resolved_model" 2>/dev/null)"; then
    :
  else
    # Fallback: call agents_registry.py directly with provided client/model
    registry_info="$("${PYTHON_BIN:-python3}" - <<'PY' "$resolved_client" "$resolved_model"
import json, sys
from agents_registry import AgentRegistry
client = sys.argv[1]
model = sys.argv[2]
try:
    data = AgentRegistry.load().validate_pair(client, model)
    print(json.dumps(data))
except Exception:
    print("")
PY
)"
  fi
  if [[ -n "$registry_info" ]]; then
    adapter_parse_output="$("${PYTHON_BIN:-python3}" - <<'PY' "$registry_info"
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("adapter", ""))
print(data.get("maxContextTokens") or "")
print(data.get("maxOutputTokens") or "")
print(data.get("apiBase") or "")
print(data.get("apiKeyEnv") or "")
print(data.get("orgEnv") or "")
print(data.get("apiBaseEnv") or "")
PY
)"
    IFS=$'\n' read -r agent_adapter agent_ctx agent_out agent_api_base agent_api_key_env agent_org_env agent_api_base_env <<<"$adapter_parse_output"
    [[ -n "$agent_adapter" ]] && export GC_ACTIVE_AGENT_ADAPTER="$agent_adapter"
    [[ -n "$agent_ctx" ]] && export GC_ACTIVE_AGENT_MAX_CONTEXT="$agent_ctx"
    [[ -n "$agent_out" ]] && export GC_ACTIVE_AGENT_MAX_OUTPUT="$agent_out"
    [[ -n "$agent_api_base" ]] && export GC_ACTIVE_AGENT_API_BASE="$agent_api_base"
    [[ -n "$agent_api_key_env" ]] && export GC_ACTIVE_AGENT_API_KEY_ENV="$agent_api_key_env"
    [[ -n "$agent_org_env" ]] && export GC_ACTIVE_AGENT_API_ORG_ENV="$agent_org_env"
    [[ -n "$agent_api_base_env" ]] && export GC_ACTIVE_AGENT_API_BASE_ENV="$agent_api_base_env"
  fi

  # Enrich the agent file with registry defaults (adapter/config/limits), mirroring test-agent.
  if [[ -n "$agent_tmp" && -f "$agent_tmp" ]]; then
    "${PYTHON_BIN:-python3}" - "$agent_tmp" "$registry_info" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
registry_raw = sys.argv[2] if len(sys.argv) > 2 else ""
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
agent = data.get("agent")
if not isinstance(agent, dict):
    agent = {}
    data["agent"] = agent
registry = {}
if registry_raw:
    try:
        registry = json.loads(registry_raw)
    except Exception:
        registry = {}

def first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
        else:
            return value
    return None

adapter = first_non_empty(agent.get("adapter"), registry.get("adapter"))
if adapter:
    agent["adapter"] = adapter

adapter_cfg = agent.get("adapterConfig")
reg_cfg = registry.get("adapterConfig") if isinstance(registry, dict) else None
if not adapter_cfg and reg_cfg:
    agent["adapterConfig"] = reg_cfg

for key, reg_key in (("maxContextTokens", "maxContextTokens"), ("maxOutputTokens", "maxOutputTokens")):
    if agent.get(key) is None and isinstance(registry, dict) and registry.get(reg_key) is not None:
        agent[key] = registry[reg_key]

if isinstance(registry, dict):
    if not agent.get("client_api_base") and registry.get("apiBase"):
        agent["client_api_base"] = registry.get("apiBase")
    if not agent.get("client_api_key_env") and registry.get("apiKeyEnv"):
        agent["client_api_key_env"] = registry.get("apiKeyEnv")
    if not agent.get("client_api_org_env") and registry.get("orgEnv"):
        agent["client_api_org_env"] = registry.get("orgEnv")
    if not agent.get("client_api_base_env") and registry.get("apiBaseEnv"):
        agent["client_api_base_env"] = registry.get("apiBaseEnv")

try:
    path.write_text(json.dumps(data), encoding="utf-8")
except Exception:
    pass
PY
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
