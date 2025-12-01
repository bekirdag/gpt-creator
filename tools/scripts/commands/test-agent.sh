#!/usr/bin/env bash
# shellcheck shell=bash

cmd_test_agent() {
  local root="" name="" json=0 verbose=0
  local python_bin="${PYTHON_BIN:-python3}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --name)
        name="${2:-}"
        shift 2
        ;;
      --json)
        json=1
        shift
        ;;
      --verbose)
        verbose=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd test-agent)"; then
          gc_render_template "${tmpl}"
        else
          cat <<'EOF'
Usage: gpt-creator test-agent --name <agent-name> [--project <path>] [--json]

Resolves an agent from the tasks database and prints the client/model/adapter
that work-on-tasks would use when invoked with --agent.
EOF
        fi
        return 0
        ;;
      *)
        die "Unknown test-agent option: $1"
        ;;
    esac
  done

  [[ -n "$name" ]] || die "--name is required for test-agent"

  ensure_ctx "$root"
  local tasks_db
  tasks_db="$(_gc_agents_require_db)" || return "$GC_AGENT_EXIT_DB"

  local select_output=""
  if ! select_output="$(GC_AGENT_READONLY=1 gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$tasks_db" select --name "$name")"; then
    die "Failed to resolve agent '${name}' from tasks DB"
  fi

  local summary=""
  summary="$(
    "$python_bin" - <<'PY' "$select_output"
import json, sys
agent_raw = sys.argv[1]
try:
    data = json.loads(agent_raw)
except Exception:
    sys.stderr.write("invalid agent selection JSON\n")
    sys.exit(1)
if data.get("kind") != "agent":
    sys.stderr.write("no agent found\n")
    sys.exit(1)
agent = data.get("agent") or {}
client = agent.get("client", "")
model = agent.get("model", "")
name = agent.get("name", "")
agent_adapter = (agent.get("adapter") or "").strip()
agent_cfg = agent.get("adapterConfig") or {}
max_ctx = agent.get("maxContextTokens")
max_out = agent.get("maxOutputTokens")
api_base = agent.get("client_api_base") or ""
api_key_env = agent.get("client_api_key_env") or ""
org_env = agent.get("client_api_org_env") or ""
api_base_env = agent.get("client_api_base_env") or ""

adapter = agent_adapter
adapter_cfg = agent_cfg
try:
    import os
    from pathlib import Path
    root = os.environ.get("GC_CLI_ROOT") or os.environ.get("CLI_ROOT") or ""
    if root:
        sys.path.insert(0, str(Path(root) / "tools" / "scripts" / "python"))
        sys.path.insert(0, str(Path(root) / "scripts" / "python"))
    from agents_registry import AgentRegistry  # type: ignore
    reg = AgentRegistry.load().validate_pair(client, model)
    adapter = adapter or (reg.get("adapter") or "").strip()
    adapter_cfg = adapter_cfg or (reg.get("adapterConfig") or {})
    max_ctx = max_ctx or reg.get("maxContextTokens")
    max_out = max_out or reg.get("maxOutputTokens")
    api_base = api_base or reg.get("apiBase") or ""
    api_key_env = api_key_env or reg.get("apiKeyEnv") or ""
    org_env = org_env or reg.get("orgEnv") or ""
    api_base_env = api_base_env or reg.get("apiBaseEnv") or ""
except Exception:
    pass

result = {
    "agent": name,
    "client": client,
    "model": model,
    "adapter": adapter,
    "adapterConfig": adapter_cfg,
    "maxContextTokens": max_ctx,
    "maxOutputTokens": max_out,
    "apiBase": api_base,
    "apiKeyEnv": api_key_env,
    "apiBaseEnv": api_base_env,
    "orgEnv": org_env,
}
print(json.dumps(result))
PY
  )" || return 1

  if (( json )); then
    printf '%s\n' "$summary"
    return 0
  fi

  local adapter_val
  adapter_val="$(jq -r '.adapter // ""' <<<"$summary")"
  local ping_status="skipped"
  local ping_error=""
  if [[ -n "$adapter_val" ]]; then
    ping_status="ok"
    set +e
    ping_error="$(
SUMMARY="$summary" "$python_bin" - <<'PY' 2>&1
import json, os, sys
from pathlib import Path

root = os.environ.get("GC_CLI_ROOT") or os.environ.get("CLI_ROOT") or ""
if root:
    sys.path.insert(0, str(Path(root) / "tools" / "scripts" / "python"))
    sys.path.insert(0, str(Path(root) / "scripts" / "python"))

from llm_client_factory import create_llm_client
try:
    data = json.loads(os.environ.get("SUMMARY", "{}"))
    adapter = (data.get("adapter") or "").strip()
    model = (data.get("model") or "").strip()
    cfg = data.get("adapterConfig") or {}
    if not adapter or not model:
        sys.exit(2)
    # Pass the full config shape expected by create_llm_client
    config = {
        "adapterConfig": cfg,
        "apiKeyEnv": data.get("apiKeyEnv"),
        "apiBaseEnv": data.get("apiBaseEnv"),
        "apiBase": data.get("apiBase"),
        "orgEnv": data.get("orgEnv"),
        "maxContextTokens": data.get("maxContextTokens"),
        "maxOutputTokens": data.get("maxOutputTokens"),
    }
    client = create_llm_client(adapter, config)
    result = client.send_chat(["ping"], model=model)
    print(result.content)
except Exception as exc:
    print(str(exc))
    sys.exit(1)
PY
)"
    ping_rc=$?
    set -e
    if [[ $ping_rc -ne 0 ]]; then
      ping_status="failed"
    fi
  fi

  local agent_name client_name model_name adapter_disp cmd_disp prompt_tmpl_disp joiner_disp timeout_disp
  local max_ctx_disp max_out_disp api_base_disp api_key_env_disp api_base_env_disp org_env_disp
  agent_name="$(jq -r '.agent' <<<"$summary" 2>/dev/null || echo '<error>')"
  client_name="$(jq -r '.client' <<<"$summary" 2>/dev/null || echo '<error>')"
  model_name="$(jq -r '.model' <<<"$summary" 2>/dev/null || echo '<error>')"
  adapter_disp="$(jq -r '.adapter // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  cmd_disp="$(jq -r '.adapterConfig.command // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  prompt_tmpl_disp="$(jq -r '.adapterConfig.promptTemplate // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  joiner_disp="$(jq -r '.adapterConfig.messageJoiner // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  timeout_disp="$(jq -r '.adapterConfig.timeoutSeconds // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  max_ctx_disp="$(jq -r '.maxContextTokens // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  max_out_disp="$(jq -r '.maxOutputTokens // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  api_base_disp="$(jq -r '.apiBase // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  api_key_env_disp="$(jq -r '.apiKeyEnv // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  api_base_env_disp="$(jq -r '.apiBaseEnv // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"
  org_env_disp="$(jq -r '.orgEnv // "<unset>"' <<<"$summary" 2>/dev/null || echo '<error>')"

  printf 'Agent:           %s\n' "$agent_name"
  printf 'Client:          %s\n' "$client_name"
  printf 'Model:           %s\n' "$model_name"
  printf 'Adapter:         %s\n' "$adapter_disp"
  printf 'Command:         %s\n' "$cmd_disp"
  printf 'PromptTemplate:  %s\n' "$prompt_tmpl_disp"
  printf 'Joiner:          %s\n' "$joiner_disp"
  printf 'TimeoutSeconds:  %s\n' "$timeout_disp"
  printf 'MaxContext:      %s\n' "$max_ctx_disp"
  printf 'MaxOutput:       %s\n' "$max_out_disp"
  printf 'API Base:        %s\n' "$api_base_disp"
  printf 'API Key Env:     %s\n' "$api_key_env_disp"
  printf 'API Base Env:    %s\n' "$api_base_env_disp"
  printf 'Org Env:         %s\n' "$org_env_disp"
  printf 'Ping:            %s\n' "$ping_status"
  if [[ "$ping_status" == "failed" ]]; then
    printf 'Ping error:      %s\n' "$ping_error"
  fi
}
