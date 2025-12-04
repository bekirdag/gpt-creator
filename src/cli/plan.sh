#!/usr/bin/env bash
# gpt-creator :: plan — synthesize a build plan from normalized docs using the active adapter (default Codex)
# Usage: gpt-creator plan /path/to/project
set -Eeuo pipefail

__DIR__="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034
GC_TEMPLATE_ROOT="$(cd "${__DIR__}/../.." && pwd)/assets/templates"
# shellcheck disable=SC1091
source "${__DIR__}/../lib/templates.sh"
if [[ -f "${__DIR__}/../constants.sh" ]]; then
  # shellcheck source=../constants.sh
  source "${__DIR__}/../constants.sh"
else
  GC_RUNTIME_SUBDIR=".gpt-creator"
fi

PROJECT_DIR="${1:-${PWD}}"
PROJECT_DIR="$(cd "${PROJECT_DIR}" && pwd)"
RUNTIME_DIR="${PROJECT_DIR}/${GC_RUNTIME_SUBDIR:-.gpt-creator}"
MANIFEST_DIR="${RUNTIME_DIR}/manifests"
STAGING_DIR="${RUNTIME_DIR}/staging"
NORM="${STAGING_DIR}/normalized"
PLAN_OUT="${MANIFEST_DIR}/build-plan_$(date +"%Y%m%d-%H%M%S").md"
PROMPT_FILE="${MANIFEST_DIR}/_plan_prompt.txt"

[[ -d "${NORM}" ]] || { echo "[plan] Normalized inputs not found. Run 'gpt-creator normalize' first." >&2; exit 1; }

# Resolve key inputs if present
PDR="$(ls -1 ${NORM}/docs/pdr.* 2>/dev/null | head -n1 || true)"
SDS="$(ls -1 ${NORM}/docs/sds.* 2>/dev/null | head -n1 || true)"
RFP="$(ls -1 ${NORM}/docs/rfp.* 2>/dev/null | head -n1 || true)"
OPENAPI="$(ls -1 ${NORM}/docs/openapi.* 2>/dev/null | head -n1 || true)"
JIRA="$(ls -1 ${NORM}/tasks/jira.md 2>/dev/null || true)"
MMD_WEB="${NORM}/diagrams/website.mmd"
MMD_BOF="${NORM}/diagrams/backoffice.mmd"
SQL_DIR="${NORM}/db/sql"
UI_WEB_DIR="${NORM}/ui/website"
UI_BOF_DIR="${NORM}/ui/backoffice"
CSS_DIR="${NORM}/ui/styles"

# Compose a compact prompt for the active adapter (file paths + instructions)
gc_cli_render_template "prompts/plan_prompt.txt" > "${PROMPT_FILE}"

# Append the actual resolved paths so Codex can reference them (kept compact)
{
  echo ""
  echo "### Context file paths"
  [[ -n "${PDR}" ]] && echo "- PDR: ${PDR}"
  [[ -n "${SDS}" ]] && echo "- SDS: ${SDS}"
  [[ -n "${RFP}" ]] && echo "- RFP: ${RFP}"
  [[ -n "${OPENAPI}" ]] && echo "- OpenAPI: ${OPENAPI}"
  [[ -f "${MMD_WEB}" ]] && echo "- Mermaid (website): ${MMD_WEB}"
  [[ -f "${MMD_BOF}" ]] && echo "- Mermaid (backoffice): ${MMD_BOF}"
  [[ -d "${SQL_DIR}" ]] && echo "- SQL dir: ${SQL_DIR}"
  [[ -d "${UI_WEB_DIR}" ]] && echo "- UI samples (website): ${UI_WEB_DIR}"
  [[ -d "${UI_BOF_DIR}" ]] && echo "- UI samples (backoffice): ${UI_BOF_DIR}"
  [[ -d "${CSS_DIR}" ]] && echo "- Styles: ${CSS_DIR}"
  [[ -n "${JIRA}" ]] && echo "- Jira tasks: ${JIRA}"
} >> "${PROMPT_FILE}"

# Invoke adapter client if available, else just emit the prompt path.
ADAPTER_BIN="${ADAPTER_CMD:-${CODEX_BIN:-codex}}"
# Align with CLI default to avoid gated SKUs.
MODEL="${GC_ACTIVE_MODEL:-${DEFAULT_LLM:-${GC_CODEX_MODEL:-gpt-4.1}}}"

if command -v "${ADAPTER_BIN}" >/dev/null 2>&1; then
  echo "[plan] Running adapter (${ADAPTER_BIN}) to produce build plan…"
  if "${ADAPTER_BIN}" chat --model "${MODEL}" --system "You are a precise software build planner." --input-file "${PROMPT_FILE}" > "${PLAN_OUT}"; then
    echo "[plan] Build plan written to ${PLAN_OUT}"
    echo "${PLAN_OUT}"
  else
    echo "[plan][ERROR] Adapter invocation failed; prompt left at ${PROMPT_FILE}" >&2
    exit 1
  fi
else
  echo "[plan] Adapter client not found in PATH. Prompt prepared at:"
  echo "${PROMPT_FILE}"
  echo "[plan] Run your client manually, e.g.:"
  echo "  ${ADAPTER_BIN:-codex} chat --model ${MODEL} --system 'You are a precise software build planner.' --input-file '${PROMPT_FILE}' > '${PLAN_OUT}'"
fi
