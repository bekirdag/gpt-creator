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
: "${GC_DEFAULT_MODEL:=gpt-5.1-codex-max}"
: "${PROJECT_DIR:=${PWD}}"
: "${GC_STATE_DIR:=${PROJECT_DIR}/.gpt-creator}"
: "${GC_STAGING_DIR:=${GC_STATE_DIR}/staging}"
: "${GC_DOCKER_DIR:=${PROJECT_DIR}/docker}"
: "${GC_COMPOSE_FILE:=${GC_DOCKER_DIR}/docker-compose.yml}"

info(){ printf "[%s] %s\n" "$GC_NAME" "$*"; }
warn(){ printf "\033[33m[%s][WARN]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
err(){  printf "\033[31m[%s][ERROR]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
die(){ err "$*"; exit 1; }

gc_cli_render_template "help/global_cli_help.txt"
