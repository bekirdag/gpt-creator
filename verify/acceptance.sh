#!/usr/bin/env bash
# verify/acceptance.sh — quick acceptance checks for the stack
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DEFAULTS="${ROOT_DIR}/config/defaults.sh"
[[ -f "$CONFIG_DEFAULTS" ]] && source "$CONFIG_DEFAULTS"

API_URL="${1:-${GC_DEFAULT_API_URL:-http://localhost:3000/api/v1}}"
WEB_URL="${2:-http://localhost:8080/}"
ADMIN_URL="${3:-http://localhost:8080/admin/}"

ok()   { printf '✅ %s\n' "$*"; }
bad()  { printf '❌ %s\n' "$*" >&2; }
info() { printf 'ℹ️  %s\n' "$*"; }

curl_ok() {
  local url="$1"
  local code
  code=$(curl -fsS -o /dev/null -w "%{http_code}" "$url" || true)
  [[ "$code" =~ ^2[0-9][0-9]$ || "$code" =~ ^3[0-9][0-9]$ ]] && return 0 || return 1
}

PROJECT_ROOT_ENV="${PROJECT_ROOT:-}"
COMPOSE_FILE_HINT="${GC_COMPOSE_FILE:-}"

slugify() {
  local s="${1:-}"
  s="${s,,}"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

PROJECT_SLUG="${GC_DOCKER_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"
if [[ -z "$PROJECT_SLUG" ]]; then
  if [[ -n "$PROJECT_ROOT_ENV" ]]; then
    PROJECT_SLUG="$(slugify "$(basename "$PROJECT_ROOT_ENV")")"
  else
    PROJECT_SLUG="$(slugify "$(basename "$ROOT_DIR")")"
  fi
fi

if [[ -z "$COMPOSE_FILE_HINT" && -n "$PROJECT_ROOT_ENV" ]]; then
  COMPOSE_FILE_HINT="${PROJECT_ROOT_ENV}/docker/docker-compose.yml"
fi

info "Checking Docker services (if docker compose is available)…"
if [[ -n "$COMPOSE_FILE_HINT" && -f "$COMPOSE_FILE_HINT" ]]; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE_HINT" ps || true
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -p "$PROJECT_SLUG" -f "$COMPOSE_FILE_HINT" ps || true
  else
    info "Docker compose CLI not available (skipping)"
  fi
else
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose ps || true
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -p "$PROJECT_SLUG" ps || true
  else
    info "docker-compose not found (skipping)"
  fi
fi

info "API health: ${API_URL%/}/health"
if curl_ok "${API_URL%/}/health"; then
  ok "API /health reachable."
else
  bad "API /health check failed at ${API_URL%/}/health"
  FAIL=1
fi

web_ping="${WEB_URL%/}/__vite_ping"
if curl_ok "$web_ping" || curl_ok "${WEB_URL}"; then
  ok "Web is serving."
else
  bad "Web check failed at ${WEB_URL}"
  FAIL=1
fi

admin_ping="${ADMIN_URL%/}/__vite_ping"
if curl_ok "$admin_ping" || curl_ok "${ADMIN_URL}"; then
  ok "Admin is serving."
else
  bad "Admin check failed at ${ADMIN_URL}"
  FAIL=1
fi

if [[ "${FAIL:-0}" -eq 0 ]]; then
  ok "Acceptance checks passed."
  exit 0
else
  bad "Acceptance checks failed."
  exit 1
fi
