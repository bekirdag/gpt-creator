#!/usr/bin/env bash
# gpt-creator :: plan — synthesize a build plan from normalized docs using Codex
# Usage: gpt-creator plan /path/to/project
set -Eeuo pipefail

__DIR__="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${__DIR__}/../constants.sh" ]]; then
  # shellcheck source=../constants.sh
  source "${__DIR__}/../constants.sh"
else
  GC_RUNTIME_SUBDIR=".gpt-creator"
  GC_CODEX_BIN="${GC_CODEX_BIN:-codex}"
  GC_CODEX_MODEL="${GC_CODEX_MODEL:-gpt-5-high}"
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

# Compose a compact prompt for Codex (file paths + instructions)
cat > "${PROMPT_FILE}" <<'PROMPT'
You are **Codex Build Orchestrator**. Produce a **step‑by‑step, dependency‑ordered build plan** for a full-stack product using:
- Backend: NestJS (Node 20, TypeScript), MySQL 8, Prisma (or TypeORM), SMTP, reCAPTCHA.
- Frontend: Vue 3 + Vite (website + admin), Tailwind optional, AA accessibility.
- Infra: Docker (dev), Nginx/Traefik reverse proxy, Hetzner Ubuntu (single box).

**Inputs available on disk** (paths will follow below):
- PDR / SDS / RFP markdown
- OpenAPI spec (yaml/json)
- Mermaid diagrams (website/admin flows)
- SQL dump(s) / schema
- UI page samples (HTML/CSS)
- Jira tasks (markdown)

**Deliver a plan** that includes:
1) Repo layout (monorepo), package.json workspaces.
2) DB: schemas, migrations, seeds; import of SQL dump if present.
3) API: NestJS modules, DTOs, validation, Problem+JSON errors, rate limits, auth, reCAPTCHA verification, newsletter, contact.
4) Frontend: Vue routes/components for all pages; Program (filters Tür/Uzman) table/cards; Events + Past; Auth; Member dashboard; Admin modules.
5) Dev containers: docker-compose.yml (MySQL, API, Website, Admin, Proxy), .env structure.
6) Scripts: `gpt-creator generate api|web|admin|db|docker` tasks list with acceptance criteria checks.
7) Verification: Lighthouse, axe, /health checks; UAT scenarios mapped to acceptance IDs.
8) Explicit TODOs when inputs are missing (e.g., no OpenAPI).

Output format:
- Markdown with sections, numbered steps, checklists (acceptance). Keep concise but complete.
PROMPT

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

# Invoke Codex client if available, else just emit the prompt path to help the user run it.
CODEX_BIN="${GC_CODEX_BIN:-${GC_CODEX_BIN:-codex}}"
MODEL="${GC_CODEX_MODEL:-${GC_CODEX_MODEL:-gpt-5-high}}"

if command -v "${CODEX_BIN}" >/dev/null 2>&1; then
  echo "[plan] Running Codex to produce build plan…"
  # Generic CLI invocation (adjust if your client uses different flags)
  "${CODEX_BIN}" chat --model "${MODEL}" --system "You are a precise software build planner." --input-file "${PROMPT_FILE}" > "${PLAN_OUT}"
  echo "[plan] Build plan written to ${PLAN_OUT}"
  echo "${PLAN_OUT}"
else
  echo "[plan] Codex client not found in PATH. Prompt prepared at:"
  echo "${PROMPT_FILE}"
  echo "[plan] Run your client manually, e.g.:"
  echo "  codex chat --model ${MODEL} --system 'You are a precise software build planner.' --input-file '${PROMPT_FILE}' > '${PLAN_OUT}'"
fi
