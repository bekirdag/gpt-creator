#!/usr/bin/env bash
# gpt-creator :: generate-api — uses Codex to scaffold NestJS API from OpenAPI + docs
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
: "${API_DIR:=${PROJECT_ROOT}/apps/api}"

mkdir -p "${WORK_DIR}/prompts" "${API_DIR}"

OPENAPI_PATH="${OPENAPI_PATH:-}"
OUT_DIR="${API_DIR}"
INSTALL_DEPS=1

show_help() {
  cat <<EOF
generate-api — scaffold NestJS API

Usage:
  gpt-creator generate api [options]

Options:
  --openapi <file>     Path to OpenAPI spec (auto-discover if omitted)
  --out <dir>          Output directory for API (default: ${OUT_DIR})
  --no-install         Skip pnpm install/build
  -n, --dry-run        Create prompt only; do not call Codex
  -h, --help           Show help
EOF
}

# Arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --openapi) OPENAPI_PATH="$2"; shift 2 ;;
    --out) OUT_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --no-install) INSTALL_DEPS=0; shift ;;
    -n|--dry-run) GC_DRY_RUN=1; shift ;;
    -h|--help) show_help; exit 0 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

# Discover OpenAPI spec if not provided
if [[ -z "${OPENAPI_PATH}" ]]; then
  for cand in \
      "${STAGING_DIR}/openapi.yaml" \
      "${STAGING_DIR}/openapi.yml" \
      "${STAGING_DIR}/openapi.json" \
      "${STAGING_DIR}/openAPI.txt" \
      "${PROJECT_ROOT}/openapi.yaml" \
      "${PROJECT_ROOT}/openAPI.txt"
  do
    [[ -f "$cand" ]] && OPENAPI_PATH="$cand" && break
  done
fi

[[ -f "${OPENAPI_PATH}" ]] || die "OpenAPI not found. Looked for staged openapi.*; set --openapi."

# Collect context document paths (best-effort)
PDR="$(resolve_doc "${STAGING_DIR}/pdr.md" '*pdr*.md')"; PDR="${PDR:-<missing>}"
SDS="$(resolve_doc "${STAGING_DIR}/sds.md" '*sds*.md' '*system*design*spec*.md')"; SDS="${SDS:-<missing>}"
RFP="$(resolve_doc "${STAGING_DIR}/rfp.md" '*rfp*.md' '*request*for*proposal*.md')"; RFP="${RFP:-<missing>}"
IA="$(resolve_doc "${STAGING_DIR}/ui-pages.md" '*ui*pages*.md' '*website*ui*pages*.md')"; IA="${IA:-<missing>}"
SQL="$(resolve_doc "${STAGING_DIR}/schema.sql" '*schema.sql' '*sql_dump*.sql' '*.sql')"; SQL="${SQL:-<missing>}"

PROMPT_FILE="${WORK_DIR}/prompts/generate-api.prompt.md"

cat > "$PROMPT_FILE" <<'PROMPT'
System:
You are Codex (gpt-5-high) generating a production-grade NestJS 10 API (TypeScript 5) with MySQL 8 using Prisma, aligned to the project's PDR/SDS. Honor OWASP, consent logging, reCAPTCHA verify at signup, and Problem+JSON errors. Emit a complete, runnable codebase.

Context (files to read and obey):
- OPENAPI: {{OPENAPI_PATH}}
- PDR: {{PDR}}
- SDS: {{SDS}}
- IA/UI Pages: {{IA}}
- RFP: {{RFP}}
- SQL baseline (for naming/seed guidance): {{SQL}}

Deliverables (write to filesystem under OUT_DIR):
- NestJS project (pnpm) with modules: auth, members, program (schedule), events, pages, newsletter, admin (ingestion CRUD, audit).
- DTOs & validators per OpenAPI; controllers/services; guards; filters.
- Prisma schema (MySQL) + migrations and seed aligned to SDS tables (users, consents, instructors, class_types, classes, reservations, events, newsletter_subscriptions, ingestion_runs/errors, audit_logs, policy_versions).
- reCAPTCHA verification in POST /auth/signup; consent versions persisted.
- Rate limits, Helmet headers, CSRF on state-change routes.
- Health endpoint /health.
- Dockerfile (Node 20) and docker-compose service fragment for api + mysql.
- README with local run, env vars, and curl smoke tests.

Conventions:
- Base path /api/v1; cookie-based sessions (HttpOnly, Secure, SameSite).
- Problem+JSON error format.
- Time in UTC; display Europe/Istanbul handled by frontend.
- Env via @nestjs/config; include .env.sample.

Tasks:
1) Scaffold project structure with pnpm + Nest CLI layout.
2) Implement endpoints/types from OpenAPI, filling any missing details from SDS/PDR.
3) Implement Prisma schema & migrations; seeds for class_types and instructors.
4) Implement auth (Argon2id hash), signup with reCAPTCHA + consent logging, login/logout, profile update, password reset.
5) Implement Program read with filters; Events read with upcoming/past split.
6) Implement Admin ingestion endpoints and audit logging skeletons.
7) Add Docker artifacts and compose snippet.
8) Include minimal unit tests for 2–3 endpoints.

Write files only—no commentary.
PROMPT

# Interpolate paths into the prompt (lightweight)
sed -i \
  -e "s#{{OPENAPI_PATH}}#${OPENAPI_PATH}#g" \
  -e "s#{{PDR}}#${PDR}#g" \
  -e "s#{{SDS}}#${SDS}#g" \
  -e "s#{{IA}}#${IA}#g" \
  -e "s#{{RFP}}#${RFP}#g" \
  -e "s#{{SQL}}#${SQL}#g" \
  "$PROMPT_FILE"

log_info "Prepared Codex prompt → $PROMPT_FILE"
log_info "Output directory         → $OUT_DIR"

mkdir -p "$OUT_DIR"

# Wrapper to invoke the local Codex client (best-effort; adjust if your CLI differs)
run_codex() {
  local prompt="$1"
  local out="$2"
  if [[ -n "${GC_DRY_RUN:-}" ]]; then
    log_info "[dry-run] Would call Codex ${CODEX_CMD} --model ${CODEX_MODEL}"
    return 0
  fi
  if command -v "${CODEX_CMD}" >/dev/null 2>&1; then
    # Try a couple of common CLI shapes; customize if your client differs
    if "${CODEX_CMD}" --help 2>/dev/null | grep -qi "chat"; then
      "${CODEX_CMD}" chat --model "${CODEX_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
    else
      "${CODEX_CMD}" generate --model "${CODEX_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
    fi
  else
    die "Codex CLI not found: ${CODEX_CMD}. Set CODEX_CMD or install client."
  fi
}

run_codex "$PROMPT_FILE" "$OUT_DIR"

if [[ "${INSTALL_DEPS}" -eq 1 && -z "${GC_DRY_RUN:-}" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$OUT_DIR" && pnpm install)
    (cd "$OUT_DIR" && pnpm build || true)
  else
    log_warn "pnpm not found; skipping install/build."
  fi
fi

log_info "API generation script finished."
