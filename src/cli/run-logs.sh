#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

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
  (
    set -a
    # shellcheck disable=SC2034
    RUN_LOGS_CMD_NAME="$GC_NAME"
    RUN_LOGS_DEFAULT_TAIL="$TAIL"
    set +a
    gc_cli_render_template "help/run_logs_usage.txt"
  )
}

SERVICE=""
FOLLOW=0
TAIL=300
SINCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--project-dir) PROJECT_DIR="$2"; shift 2;;
    -s|--service) SERVICE="$2"; shift 2;;
    --since) SINCE="$2"; shift 2;;
    -n|--tail) TAIL="$2"; shift 2;;
    -f|--follow) FOLLOW=1; shift;;
    -h|--help) usage; exit 0;;
    *) err "Unknown argument: $1"; usage; exit 2;;
  esac
done

[[ -x "$(command -v docker)" ]] || die "Docker is required."
[[ -f "$GC_COMPOSE_FILE" ]] || die "Compose file not found at $GC_COMPOSE_FILE"

args=( compose -f "$GC_COMPOSE_FILE" logs --tail "$TAIL" )
[[ -n "$SINCE" ]] && args+=( --since "$SINCE" )
[[ "$FOLLOW" -eq 1 ]] && args+=( -f )
[[ -n "$SERVICE" ]] && args+=( "$SERVICE" )

info "Streaming logs (compose: $GC_COMPOSE_FILE) ${SERVICE:+service=$SERVICE}"
exec docker "${args[@]}"
