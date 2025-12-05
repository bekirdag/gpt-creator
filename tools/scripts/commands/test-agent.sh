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

  # Resolve the agent using the same path as work-on-tasks so env vars are populated.
  if ! gc_resolve_agent "$name" "$tasks_db" "${PROJECT_ROOT:-$PWD}"; then
    die "Failed to resolve agent '${name}' via work-on-tasks resolver"
  fi

  local summary_helper=""
  summary_helper="$(gc_clone_python_tool "agents_summary_with_registry.py" "${PROJECT_ROOT:-$PWD}")" || summary_helper=""
  local summary=""
  if [[ -n "$summary_helper" ]]; then
    summary="$("${python_bin}" "$summary_helper" "${GC_ACTIVE_AGENT_FILE:-}")" || return 1
  else
    die "Missing agents_summary_with_registry.py helper"
  fi

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
    local ping_helper=""
    ping_helper="$(gc_clone_python_tool "agents_ping_adapter.py" "${PROJECT_ROOT:-$PWD}")" || ping_helper=""
    if [[ -n "$ping_helper" ]]; then
      ping_error="$(SUMMARY="$summary" "$python_bin" "$ping_helper" 2>&1)"
      ping_rc=$?
    else
      ping_error="ping helper missing"
      ping_rc=1
    fi
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

  # Simple workload simulation mirroring work-on-tasks adapter use.
  local project_root="${PROJECT_ROOT:-$PWD}"
  local workload_file="${project_root}/test.txt"
  local -a workload_log=()
  local workload_error=0
  local iteration
  for iteration in 1 2 3; do
    local agent_line=""
    local workload_helper=""
    workload_helper="$(gc_clone_python_tool "agents_workload_iteration.py" "${PROJECT_ROOT:-$PWD}")" || workload_helper=""
    if [[ -z "$workload_helper" ]]; then
      workload_error=1
      workload_log+=("run ${iteration}: workload helper missing")
      continue
    fi
    if ! agent_line="$(SUMMARY="$summary" ITERATION="$iteration" "$python_bin" "$workload_helper" 2>&1)"; then
      workload_error=1
      workload_log+=("run ${iteration}: agent call failed (${agent_line})")
      continue
    fi
    printf '%s\n' "$agent_line" >>"$workload_file"
    workload_log+=("run ${iteration}: appended '${agent_line}' to ${workload_file}")
  done

  printf '\nWorkload simulation:\n'
  for entry in "${workload_log[@]}"; do
    printf '  - %s\n' "$entry"
  done
  if (( workload_error )); then
    printf 'Workload result: incomplete (errors encountered)\n'
  else
    printf 'Workload result: completed successfully\n'
  fi
}
