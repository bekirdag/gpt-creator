#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# Optional shared helpers
if [[ -f "$ROOT_DIR/src/gpt-creator.sh" ]]; then source "$ROOT_DIR/src/gpt-creator.sh"; fi
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then source "$ROOT_DIR/src/constants.sh"; fi

# Fallback helpers if not sourced
gc_cli_log(){ printf "[%s] %s\n" "$(date +'%H:%M:%S')" "$*"; }
gc_cli_warn(){ printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
gc_cli_die(){ printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
gc_cli_heading(){ printf "\n\033[36m== %s ==\033[0m\n" "$*"; }

slugify() {
  local s="${1:-}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

PROJECT_SLUG="${GC_DOCKER_PROJECT_NAME:-$(slugify "$(basename "$ROOT_DIR")")}";
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$PROJECT_SLUG}"
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
        *) gc_cli_die "Unknown arg: $1 (see --help)";;
  esac
done

if [[ -z "${COMPOSE_FILE}" ]]; then
  if [[ -f "$ROOT_DIR/docker/compose.yaml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker/compose.yaml";
  elif [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker-compose.yml";
  else
    gc_cli_die "No docker compose file found (expected docker/compose.yaml or docker-compose.yml)"
  fi
fi

gc_cli_heading "Starting Docker stack"
COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" up -d --build

# Wait for DB readiness (best-effort)
DB_ID="$(COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" ps -q db || true)"
if [[ -n "$DB_ID" ]]; then
  gc_cli_log "Waiting for MySQL to be ready…"
  HEALTH_TIMEOUT="${GC_DOCKER_HEALTH_TIMEOUT:-10}"
  HEALTH_INTERVAL="${GC_DOCKER_HEALTH_INTERVAL:-1}"
  [[ "$HEALTH_TIMEOUT" -le 0 ]] && HEALTH_TIMEOUT=1
  [[ "$HEALTH_INTERVAL" -le 0 ]] && HEALTH_INTERVAL=1
  waited=0
  while (( waited < HEALTH_TIMEOUT )); do
    if docker exec -i "$DB_ID" sh -lc 'mysqladmin ping -h 127.0.0.1 --silent' >/dev/null 2>&1; then
      gc_cli_log "MySQL is ready."; break
    fi
    sleep "$HEALTH_INTERVAL"
    (( waited += HEALTH_INTERVAL )) || true
  done
  if (( waited >= HEALTH_TIMEOUT )); then
    gc_cli_warn "MySQL readiness timeout after ${HEALTH_TIMEOUT}s (continuing)…"
  fi
fi

# Show status
COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" ps

if [[ "$OPEN_AFTER" == "true" ]]; then
  URL="${APP_WEB_URL:-http://localhost:5173}"
  gc_cli_log "Opening $URL"
  open "$URL" >/dev/null 2>&1 || xdg-open "$URL" || echo "$URL"
fi

gc_cli_log "Stack is up."
