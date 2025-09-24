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
  [[ "$code" == "200" || "$code" == "204" ]] && return 0 || return 1
}

info "Checking Docker services (if docker-compose is present)…"
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose ps || true
else
  info "docker-compose not found (skipping)"
fi

info "API health: ${API_URL%/}/health"
if curl_ok "${API_URL%/}/health"; then
  ok "API /health reachable."
else
  bad "API /health check failed at ${API_URL%/}/health"
  FAIL=1
fi

info "Web root: ${WEB_URL}"
if curl_ok "${WEB_URL}"; then
  ok "Web is serving."
else
  bad "Web check failed at ${WEB_URL}"
  FAIL=1
fi

info "Admin root: ${ADMIN_URL}"
if curl_ok "${ADMIN_URL}"; then
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
