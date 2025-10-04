#!/usr/bin/env bash
# gpt-creator :: generate-admin — uses Codex to scaffold Vue 3 Admin (Backoffice) from workflows + docs
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck disable=SC1091
if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  source "${ROOT_DIR}/src/constants.sh"
fi

type log_info >/dev/null 2>&1 || log_info(){ printf "[%s] \033[1mINFO\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_warn >/dev/null 2>&1 || log_warn(){ printf "[%s] \033[33mWARN\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_err  >/dev/null 2>&1 || log_err(){  printf "[%s] \033[31mERROR\033[0m %s\n" "$(date +%H:%M:%S)" "$*" >&2; }
type die      >/dev/null 2>&1 || die(){ log_err "$*"; exit 1; }

resolve_doc() {
  local primary="$1"; shift
  if [[ -f "$primary" ]]; then
    printf '%s\n' "$primary"
    return
  fi
  local pattern candidate
  for pattern in "$@"; do
    candidate="$(find "$PROJECT_ROOT" -maxdepth 2 -type f -iname "$pattern" 2>/dev/null | head -n1)"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '\n'
}

: "${PROJECT_ROOT:=${ROOT_DIR}}"
: "${CODEX_MODEL:=gpt-5-high}"
: "${CODEX_CMD:=codex}"
: "${STAGING_DIR:=${PROJECT_ROOT}/.gpt-creator/staged}"
: "${WORK_DIR:=${PROJECT_ROOT}/.gpt-creator/work}"
: "${ADMIN_DIR:=${PROJECT_ROOT}/apps/admin}"

mkdir -p "${WORK_DIR}/prompts" "${ADMIN_DIR}"

BACKOFFICE_MMD="${BACKOFFICE_MMD:-}"
PDR="$(resolve_doc "${STAGING_DIR}/pdr.md" '*pdr*.md')"; PDR="${PDR:-<missing>}"
SDS="$(resolve_doc "${STAGING_DIR}/sds.md" '*sds*.md' '*system*design*spec*.md')"; SDS="${SDS:-<missing>}"
JIRA="$(resolve_doc "${STAGING_DIR}/jira.md" '*jira*task*.md' '*jira*.md')"; JIRA="${JIRA:-<missing>}"

INSTALL_DEPS=1

show_help() {
  cat <<EOF
generate-admin — scaffold Vue 3 Admin backoffice

Usage:
  gpt-creator generate admin [options]

Options:
  --mmd <file>         Mermaid workflow for backoffice (auto-discover if omitted)
  --out <dir>          Output directory (default: ${ADMIN_DIR})
  --no-install         Skip pnpm install/build
  -n, --dry-run        Create prompt only; do not call Codex
  -h, --help           Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mmd) BACKOFFICE_MMD="$2"; shift 2 ;;
    --out) ADMIN_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --no-install) INSTALL_DEPS=0; shift ;;
    -n|--dry-run) GC_DRY_RUN=1; shift ;;
    -h|--help) show_help; exit 0 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

# Discover Mermaid workflow diagram
if [[ -z "$BACKOFFICE_MMD" ]]; then
  for cand in \
    "${STAGING_DIR}/backoffice.mmd" \
    "${PROJECT_ROOT}/Backoffice pages workflow _ Mermaid Diagram.mmd" \
    "${PROJECT_ROOT}/Website workflow _ Mermaid  Diagram.mmd"
  do
    [[ -f "$cand" ]] && BACKOFFICE_MMD="$cand" && break
  done
fi

[[ -f "$BACKOFFICE_MMD" ]] || log_warn "Backoffice Mermaid diagram not found; proceeding without."

PROMPT_FILE="${WORK_DIR}/prompts/generate-admin.prompt.md"

cat > "$PROMPT_FILE" <<'PROMPT'
System:
You are Codex (gpt-5-high) generating a Vue 3 + Vite Admin SPA for role-based management of content, instructors, membership tiles, schedule ingestion (upload/validate/publish), events, users (assist), and audit logs. Follow PDR/SDS acceptance and secure admin routes.

Context:
- SDS: {{SDS}}
- PDR: {{PDR}}
- Backoffice workflow (Mermaid): {{BACKOFFICE_MMD}}
- Jira tasks (acceptance & task names): {{JIRA}}

Deliverables (write to ADMIN_DIR):
- Vite + Vue 3 (Pinia, Vue Router) Admin app under /admin/* routes; login gate via session API; RBAC.
- Sections: Dashboard, Pages, Instructors (CRUD + reorder), Membership Tiles (CRUD + reorder + publish window), Program Ingestion (upload → validate row errors → publish), Events (CRUD + archive), Users (send reset link), Audit Log (list).
- Tables with inline filters, pagination; accessible modals; destructive confirmations.
- API client bindings to /api/v1/admin/* per SDS.
- Dockerfile + compose fragment for 'admin'.
- README with environment, run/build, and smoke test steps.

Write files only—no commentary.
PROMPT

sed -i \
  -e "s#{{SDS}}#${SDS}#g" \
  -e "s#{{PDR}}#${PDR}#g" \
  -e "s#{{BACKOFFICE_MMD}}#${BACKOFFICE_MMD:-<none>}#g" \
  -e "s#{{JIRA}}#${JIRA}#g" \
  "$PROMPT_FILE"

log_info "Prepared Codex prompt → $PROMPT_FILE"
log_info "Output directory         → $ADMIN_DIR"

mkdir -p "$ADMIN_DIR"

run_codex() {
  local prompt="$1"
  local out="$2"
  if [[ -n "${GC_DRY_RUN:-}" ]]; then
    log_info "[dry-run] Would call Codex ${CODEX_CMD} --model ${CODEX_MODEL}"
    return 0
  fi
  if command -v "${CODEX_CMD}" >/dev/null 2>&1; then
    if "${CODEX_CMD}" --help 2>/dev/null | grep -qi "chat"; then
      "${CODEX_CMD}" chat --model "${CODEX_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
    else
      "${CODEX_CMD}" generate --model "${CODEX_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
    fi
  else
    die "Codex CLI not found: ${CODEX_CMD}. Set CODEX_CMD or install client."
  fi
}

run_codex "$PROMPT_FILE" "$ADMIN_DIR"

if [[ "${INSTALL_DEPS}" -eq 1 && -z "${GC_DRY_RUN:-}" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$ADMIN_DIR" && pnpm install)
    (cd "$ADMIN_DIR" && pnpm build || true)
  else
    log_warn "pnpm not found; skipping install/build."
  fi
fi

log_info "Admin generation script finished."
