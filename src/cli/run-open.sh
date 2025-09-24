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
Usage: $GC_NAME run-open [--web] [--admin] [--api] [--all] [--web-url URL] [--admin-url URL] [--api-url URL]

Defaults:
  --web-url   ${GC_WEB_URL:-http://localhost:5173}
  --admin-url ${GC_ADMIN_URL:-http://localhost:5174}
  --api-url   ${GC_API_HEALTH_URL:-http://localhost:3000/health}

Examples:
  $GC_NAME run-open --web --admin
  $GC_NAME run-open --api --api-url http://localhost:3000/health
EOF
}

open_cmd() {
  if command -v open >/dev/null 2>&1; then echo "open"; return 0; fi
  if command -v xdg-open >/dev/null 2>&1; then echo "xdg-open"; return 0; fi
  die "No opener command found (need 'open' on macOS or 'xdg-open' on Linux)."
}

: "${GC_WEB_URL:=http://localhost:5173}"
: "${GC_ADMIN_URL:=http://localhost:5174}"
: "${GC_API_HEALTH_URL:=http://localhost:3000/health}"

DO_WEB=0; DO_ADMIN=0; DO_API=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --web) DO_WEB=1; shift;;
    --admin) DO_ADMIN=1; shift;;
    --api) DO_API=1; shift;;
    --all) DO_WEB=1; DO_ADMIN=1; DO_API=1; shift;;
    --web-url) GC_WEB_URL="$2"; shift 2;;
    --admin-url) GC_ADMIN_URL="$2"; shift 2;;
    --api-url) GC_API_HEALTH_URL="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) err "Unknown argument: $1"; usage; exit 2;;
  esac
done

# Default to web+admin if nothing specified
if [[ $DO_WEB -eq 0 && $DO_ADMIN -eq 0 && $DO_API -eq 0 ]]; then
  DO_WEB=1; DO_ADMIN=1;
fi

OPENER="$(open_cmd)"

if [[ $DO_WEB -eq 1 ]]; then
  info "Opening Web at $GC_WEB_URL"
  "$OPENER" "$GC_WEB_URL" >/dev/null 2>&1 &
fi
if [[ $DO_ADMIN -eq 1 ]]; then
  info "Opening Admin at $GC_ADMIN_URL"
  "$OPENER" "$GC_ADMIN_URL" >/dev/null 2>&1 &
fi
if [[ $DO_API -eq 1 ]]; then
  info "Opening API health at $GC_API_HEALTH_URL"
  "$OPENER" "$GC_API_HEALTH_URL" >/dev/null 2>&1 &
fi

wait || true
