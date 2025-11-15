#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"
source "${ROOT_DIR}/src/cli/lib/agents.sh"

source "$ROOT_DIR/src/lib/create-pdr/pipeline.sh"

usage() {
  gc_cli_render_template "help/create_pdr_usage.txt"
}

PROJECT_PATH="$PWD"
MODEL="${CODEX_MODEL_NON_CODE:-${CODEX_MODEL_LOW:-${CODEX_MODEL:-gpt-5.1-codex}}}"
DRY_RUN=0
FORCE=0
AGENT_NAME=""

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
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --force)
      FORCE=1
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
    echo "[agents] create-pdr using agent '${AGENT_NAME}' (model ${MODEL})"
  else
    echo "[agents] create-pdr agent '${AGENT_NAME}' missing; treating argument as raw model id" >&2
    MODEL="$AGENT_NAME"
  fi
fi

cpdr::init "$PROJECT_PATH" "$MODEL" "$DRY_RUN" "$FORCE"
cpdr::run_pipeline

cpdr::log "create-pdr completed successfully"
