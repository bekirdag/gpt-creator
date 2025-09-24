#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load shared constants if present
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  . "$ROOT_DIR/src/constants.sh"
fi

# Sensible defaults if constants are missing
: "${GC_NAME:=gpt-creator}"
: "${GC_VERSION:=0.1.0}"
: "${GC_DEFAULT_MODEL:=gpt-5-high}"
: "${PROJECT_DIR:=${PWD}}"
: "${GC_STATE_DIR:=${PROJECT_DIR}/.gpt-creator}"
: "${GC_STAGING_DIR:=${GC_STATE_DIR}/staging}"
: "${GC_DOCKER_DIR:=${PROJECT_DIR}/docker}"
: "${GC_COMPOSE_FILE:=${GC_DOCKER_DIR}/docker-compose.yml}"

info(){ printf "[%s] %s\n" "$GC_NAME" "$*"; }
warn(){ printf "\033[33m[%s][WARN]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
err(){  printf "\033[31m[%s][ERROR]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
die(){ err "$*"; exit 1; }

usage() {
  cat <<EOF
Usage: $GC_NAME verify [options]

Service URLs:
  --api-url URL     API health URL (default: ${GC_API_HEALTH_URL:-http://localhost:3000/health})
  --web-url URL     Web URL (default: ${GC_WEB_URL:-http://localhost:5173})
  --admin-url URL   Admin URL (default: ${GC_ADMIN_URL:-http://localhost:5174})

Database (optional, uses mysql client):
  --db-host HOST    MySQL host (default: ${MYSQL_HOST:-localhost})
  --db-port PORT    MySQL port (default: ${MYSQL_PORT:-3306})
  --db-user USER    MySQL user (default: ${MYSQL_USER:-root})
  --db-pass PASS    MySQL password (default: \$MYSQL_PASSWORD)
  --db-name NAME    Database name (default: ${MYSQL_DATABASE:-app})

Other:
  --compose-file PATH  docker-compose.yml path (default: $GC_COMPOSE_FILE)
  -h, --help           Show help

Exits non-zero on any failure.
EOF
}

: "${GC_API_HEALTH_URL:=http://localhost:3000/health}"
: "${GC_WEB_URL:=http://localhost:5173}"
: "${GC_ADMIN_URL:=http://localhost:5174}"

: "${MYSQL_HOST:=localhost}"
: "${MYSQL_PORT:=3306}"
: "${MYSQL_USER:=root}"
: "${MYSQL_PASSWORD:=}"
: "${MYSQL_DATABASE:=app}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-url) GC_API_HEALTH_URL="$2"; shift 2;;
    --web-url) GC_WEB_URL="$2"; shift 2;;
    --admin-url) GC_ADMIN_URL="$2"; shift 2;;
    --db-host) MYSQL_HOST="$2"; shift 2;;
    --db-port) MYSQL_PORT="$2"; shift 2;;
    --db-user) MYSQL_USER="$2"; shift 2;;
    --db-pass) MYSQL_PASSWORD="$2"; shift 2;;
    --db-name) MYSQL_DATABASE="$2"; shift 2;;
    --compose-file) GC_COMPOSE_FILE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) err "Unknown argument: $1"; usage; exit 2;;
  esac
done

pass=0; fail=0

check_url() {
  local name="$1" url="$2"
  if curl -fsS --max-time 5 "$url" >/dev/null; then
    ok "URL OK: $name → $url"
    ((pass++)) || true
  else
    err "URL FAIL: $name → $url"
    ((fail++)) || true
  fi
}

ok(){ printf "\\033[32m[%s][OK]\\033[0m %s\\n" "$GC_NAME" "$*"; }

info "== Compose status =="
if [[ -f "$GC_COMPOSE_FILE" ]]; then
  if docker compose -f "$GC_COMPOSE_FILE" ps; then
    ok "docker compose ps succeeded"
    ((pass++)) || true
  else
    err "docker compose ps failed"
    ((fail++)) || true
  fi
else
  warn "Compose file not found at $GC_COMPOSE_FILE — skipping compose check"
fi

info "== HTTP checks =="
check_url "API /health" "$GC_API_HEALTH_URL"
check_url "Web" "$GC_WEB_URL"
check_url "Admin" "$GC_ADMIN_URL"

info "== MySQL check =="
if command -v mysql >/dev/null 2>&1; then
  if MYSQL_PWD="$MYSQL_PASSWORD" mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -e "SELECT 1;" "$MYSQL_DATABASE" >/dev/null 2>&1; then
    ok "MySQL connection OK (${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE})"
    ((pass++)) || true
  else
    err "MySQL connection FAILED (${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE})"
    ((fail++)) || true
  fi
else
  warn "mysql client not found — skipping DB check"
fi

info "== Docs presence (staging) =="
missing=0
for f in pdr.* sds.* openapi.* *.mmd *.sql "*JIRA*".md "*Jira*".md "*jira*".md; do
  if ls "$GC_STAGING_DIR"/$f >/dev/null 2>&1; then
    ok "Found: $f"
    ((pass++)) || true
  else
    warn "Missing in staging: $f"
    ((missing++)) || true
  fi
done

echo ""
if [[ $fail -gt 0 ]]; then
  err "VERIFY FAILED — pass=$pass fail=$fail"
  exit 1
else
  ok "VERIFY PASSED — pass=$pass fail=$fail"
fi
