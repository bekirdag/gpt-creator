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
  local registry_defaults
  registry_defaults="$(${PYTHON_BIN:-python3} - <<'PY' 2>/dev/null
try:
    from agents_registry import AgentRegistry
    reg = AgentRegistry.load()
    clients = reg.list_clients()
    if clients:
        first = clients[0]
        client = (first.get("name") or "").strip()
        adapter = (first.get("adapter") or "").strip()
        model = (first.get("defaultModel") or (first.get("models") or [None])[0] or "").strip()
        print(client)
        print(adapter)
        print(model)
        raise SystemExit
except Exception:
    pass
print("")
print("")
print("")
PY
)" || true
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
    select_output="$(
      "${PYTHON_BIN:-python3}" - "$tasks_db" "$agent_name" <<'PY'
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
    )"
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
  local parsed_output
  parsed_output="$(
    "${PYTHON_BIN:-python3}" - "$agent_tmp" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)
kind = data.get("kind") or ""
agent = data.get("agent") or {}
if not isinstance(agent, dict):
    agent = {}
resolved = data.get("resolved") or {}
if not isinstance(resolved, dict):
    resolved = {}
def pick(*values):
    for value in values:
        if value:
            return value
    return ""
client = pick(resolved.get("client"), agent.get("client"))
model = pick(resolved.get("model"), agent.get("model"))
name = pick(agent.get("name"), agent.get("name_normalized"))
api_key = pick(agent.get("client_api_key"))
api_base = pick(agent.get("client_api_base"), resolved.get("apiBase"))
api_org = pick(agent.get("client_api_org"), agent.get("client_api_org_env"), resolved.get("orgEnv"))
adapter = pick(resolved.get("adapter"), agent.get("adapter"))
max_ctx = pick(resolved.get("maxContextTokens"), agent.get("maxContextTokens"))
max_out = pick(resolved.get("maxOutputTokens"), agent.get("maxOutputTokens"))
api_key_env = pick(agent.get("client_api_key_env"), resolved.get("apiKeyEnv"))
api_base_env = pick(agent.get("client_api_base_env"), resolved.get("apiBaseEnv"))
api_org_env = pick(agent.get("client_api_org_env"), resolved.get("orgEnv"))
print("\t".join([
    kind,
    client,
    model,
    name,
    api_key,
    api_base,
    api_org,
    adapter,
    max_ctx,
    max_out,
    api_key_env,
    api_base_env,
    api_org_env,
]))
PY
  )" || true
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
print(data.get("model") or "")
PY
)"
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
