#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# Optional shared helpers
if [[ -f "$ROOT_DIR/src/gpt-creator.sh" ]]; then source "$ROOT_DIR/src/gpt-creator.sh"; fi
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then source "$ROOT_DIR/src/constants.sh"; fi

# Fallback helpers if not sourced
type log >/dev/null 2>&1 || log(){ printf "[%s] %s\n" "$(date +'%H:%M:%S')" "$*"; }
type warn >/dev/null 2>&1 || warn(){ printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
type die >/dev/null 2>&1 || die(){ printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
type heading >/dev/null 2>&1 || heading(){ printf "\n\033[36m== %s ==\033[0m\n" "$*"; }
usage() {
  cat <<EOF
Usage: $(basename "$0") [--compose <file>] [--open]
   --compose   Path to docker compose file (default: ./docker/compose.yaml or ./docker-compose.yml)
   --open      Open web UI after start (uses APP_WEB_URL or http://localhost:5173)
EOF
}

COMPOSE_FILE=""
OPEN_AFTER="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose) COMPOSE_FILE="${2:-}"; shift 2;;
    --open) OPEN_AFTER="true"; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1 (see --help)";;
  esac
done

if [[ -z "${COMPOSE_FILE}" ]]; then
  if [[ -f "$ROOT_DIR/docker/compose.yaml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker/compose.yaml";
  elif [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker-compose.yml";
  else
    die "No docker compose file found (expected docker/compose.yaml or docker-compose.yml)"
  fi
fi

heading "Starting Docker stack"
docker compose -f "$COMPOSE_FILE" up -d --build

# Wait for DB readiness (best-effort)
DB_ID="$(docker compose -f "$COMPOSE_FILE" ps -q db || true)"
if [[ -n "$DB_ID" ]]; then
  log "Waiting for MySQL to be ready…"
  for i in {1..60}; do
    if docker exec -i "$DB_ID" sh -lc 'mysqladmin ping -h 127.0.0.1 --silent' >/dev/null 2>&1; then
      log "MySQL is ready."; break
    fi
    sleep 1
    [[ $i -eq 60 ]] && warn "MySQL readiness timeout (continuing)…"
  done
fi

# Show status
docker compose -f "$COMPOSE_FILE" ps

if [[ "$OPEN_AFTER" == "true" ]]; then
  URL="${APP_WEB_URL:-http://localhost:5173}"
  log "Opening $URL"
  open "$URL" >/dev/null 2>&1 || xdg-open "$URL" || echo "$URL"
fi

log "Stack is up."
