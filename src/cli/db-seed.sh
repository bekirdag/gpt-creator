#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

# Optional shared helpers
if [[ -f "$ROOT_DIR/src/gpt-creator.sh" ]]; then source "$ROOT_DIR/src/gpt-creator.sh"; fi
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then source "$ROOT_DIR/src/constants.sh"; fi

slugify() {
  local s="${1:-}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

PROJECT_SLUG="${GC_DOCKER_PROJECT_NAME:-$(slugify "$(basename "$ROOT_DIR")")}";
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$PROJECT_SLUG}"

PROJECT_ROOT_DIR="${PROJECT_ROOT:-$ROOT_DIR}"
TMP_DIR="${PROJECT_ROOT_DIR}/.gpt-creator/tmp"

# Fallback helpers if not sourced
gc_cli_log(){ printf "[%s] %s\n" "$(date +'%H:%M:%S')" "$*"; }
gc_cli_warn(){ printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
gc_cli_die(){ printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
gc_cli_heading(){ printf "\n\033[36m== %s ==\033[0m\n" "$*"; }
usage() {
  (
    set -a
    # shellcheck disable=SC2034
    DB_SEED_CMD_NAME="$(basename "$0")"
    set +a
    gc_cli_render_template "help/db_seed_usage.txt"
  )
}

SERVICE="db"
COMPOSE_FILE=""
FROM_SQL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE="${2:-}"; shift 2;;
    --compose) COMPOSE_FILE="${2:-}"; shift 2;;
    --from) FROM_SQL="${2:-}"; shift 2;;
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

CID="$(COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" ps -q "$SERVICE" || true)"
[[ -n "$CID" ]] || gc_cli_die "Service '$SERVICE' not found or not running. Start with: gpt-creator run compose-up"

gc_cli_heading "Seeding database in service '$SERVICE'"

if [[ -n "${FROM_SQL}" ]]; then
  [[ -f "$FROM_SQL" ]] || gc_cli_die "--from file not found: $FROM_SQL"
  PROJECT_ROOT="$PROJECT_ROOT_DIR" "$ROOT_DIR/src/cli/db-import.sh" --service "$SERVICE" --compose "$COMPOSE_FILE" --file "$FROM_SQL" -y
  exit 0
fi

# Default idempotent seed set (safe to re-run)
SEED_FILE="$TMP_DIR/seed-default.sql"
mkdir -p "$TMP_DIR"

gc_cli_render_template "db/seed_default.sql" > "$SEED_FILE"

gc_cli_log "Applying default seeds…"
PROJECT_ROOT="$PROJECT_ROOT_DIR" "$ROOT_DIR/src/cli/db-import.sh" --service "$SERVICE" --compose "$COMPOSE_FILE" --file "$SEED_FILE" -y
gc_cli_log "Seed complete."
