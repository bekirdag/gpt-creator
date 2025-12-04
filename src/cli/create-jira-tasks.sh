#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"
source "${ROOT_DIR}/src/cli/lib/agents.sh"

source "$ROOT_DIR/src/lib/create-jira-tasks/pipeline.sh"

usage() {
  gc_cli_render_template "help/create_jira_tasks_usage.txt"
}

PROJECT_PATH="$PWD"
# Default model/agent from env for easy overrides; align with CLI default.
DEFAULT_MODEL="${DEFAULT_LLM:-${GC_ACTIVE_MODEL:-${CODEX_MODEL_NON_CODE:-${CODEX_MODEL_LOW:-${CODEX_MODEL:-gpt-5.1-codex}}}}}"
MODEL="$DEFAULT_MODEL"
FORCE=0
DRY_RUN=0
AGENT_NAME=""
# Allow default agent from env without explicit flag
if [[ -z "$AGENT_NAME" && -n "${DEFAULT_AGENT:-}" ]]; then
  AGENT_NAME="$DEFAULT_AGENT"
fi
if [[ -n "${DEFAULT_AGENT_REASONING:-}" ]]; then
  export CODEX_REASONING_EFFORT="${DEFAULT_AGENT_REASONING}"
  export CODEX_REASONING_EFFORT_NON_CODE="${DEFAULT_AGENT_REASONING}"
fi
case "${GC_DRY_RUN:-}" in
  1|true|yes|on) DRY_RUN=1 ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT_PATH="${2:?--project requires a path}"
      shift 2
      ;;
    --model)
      MODEL="${2:?--model requires a value}"
      shift 2
      ;;
    --agent)
      AGENT_NAME="${2:?--agent requires a name}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -n "$AGENT_NAME" ]]; then
  if resolved_model="$(gc_cli_resolve_agent_model "$PROJECT_PATH" "$AGENT_NAME")"; then
    MODEL="$resolved_model"
    echo "[agents] create-jira-tasks using agent '${AGENT_NAME}' (model ${MODEL})"
  else
    echo "[agents] create-jira-tasks agent '${AGENT_NAME}' missing; treating argument as raw model id (reasoning settings cleared)" >&2
    MODEL="$AGENT_NAME"
    unset CODEX_REASONING_EFFORT CODEX_REASONING_EFFORT_NON_CODE
  fi
fi

cjt::init "$PROJECT_PATH" "$MODEL" "$FORCE" 0 "$DRY_RUN"
cjt::run_pipeline

if [[ "${CJT_DRY_RUN:-0}" == "1" ]]; then
  cjt::warn "Dry-run mode: no Jira tasks were generated."
elif [[ -s "${CJT_TASKS_DB_PATH:-}" && -d "${CJT_JSON_TASKS_DIR:-}" && "$(find "${CJT_JSON_TASKS_DIR:-/dev/null}" -maxdepth 1 -type f | head -n1)" ]]; then
  cjt::log "create-jira-tasks completed successfully"
else
  cjt::die "create-jira-tasks finished without generating tasks artifacts; see logs above."
fi
