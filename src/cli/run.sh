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

slugify() {
  local s="${1:-}"
  s="${s,,}"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

PROJECT_SLUG="${GC_DOCKER_PROJECT_NAME:-$(slugify "$(basename "$ROOT_DIR")")}";
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$PROJECT_SLUG}"
usage() {
  cat <<EOF
Usage: gpt-creator run <command> [options]

Commands:
  compose-up        Bring up Docker stack (build + up -d). See: run-compose-up.sh
  logs [svc]        Tail logs (default: api). Uses docker compose.
  ps                Show service status.
  open [site]       Open local URLs (web|admin|api), default: web.
  stop              Stop services (docker compose stop).
  down              Stop & remove services (docker compose down).

Examples:
  gpt-creator run compose-up --open
  gpt-creator run logs api
  gpt-creator run open admin
EOF
}

[[ $# -lt 1 ]] && { usage; exit 1; }
CMD="$1"; shift || true

# Resolve compose file
if [[ -f "$ROOT_DIR/docker/compose.yaml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker/compose.yaml";
elif [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker-compose.yml";
else COMPOSE_FILE=""; fi

case "$CMD" in
  compose-up)
    "$ROOT_DIR/src/cli/run-compose-up.sh" "$@"
    ;;
  logs)
    SVC="${1:-api}"; shift || true
    [[ -n "$COMPOSE_FILE" ]] || die "Compose file not found"
    exec env COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" logs -f --tail=200 "$SVC"
    ;;
  ps)
    [[ -n "$COMPOSE_FILE" ]] || die "Compose file not found"
    exec env COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" ps
    ;;
  open)
    TARGET="${1:-web}"
    URL_WEB="${APP_WEB_URL:-http://localhost:5173}"
    URL_ADMIN="${APP_ADMIN_URL:-http://localhost:5174}"
    URL_API="${APP_API_URL:-http://localhost:3000/health}"
    case "$TARGET" in
      web) open "$URL_WEB" >/dev/null 2>&1 || xdg-open "$URL_WEB" || echo "$URL_WEB";;
      admin) open "$URL_ADMIN" >/dev/null 2>&1 || xdg-open "$URL_ADMIN" || echo "$URL_ADMIN";;
      api) open "$URL_API" >/dev/null 2>&1 || xdg-open "$URL_API" || echo "$URL_API";;
      *) die "Unknown target: $TARGET (web|admin|api)";;
    esac
    ;;
  stop)
    [[ -n "$COMPOSE_FILE" ]] || die "Compose file not found"
    exec env COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" stop
    ;;
  down)
    [[ -n "$COMPOSE_FILE" ]] || die "Compose file not found"
    exec env COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" down
    ;;
  -h|--help)
    usage;;
  *)
    die "Unknown run command: $CMD"
    ;;
esac
