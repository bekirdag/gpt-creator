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

cat <<'EOF'
gpt-creator — scaffolding & orchestration CLI

Usage:
  gpt-creator create-project /path/to/project
  gpt-creator scan|normalize|plan [options]
  gpt-creator generate (api|web|admin|db|docker) [options]
  gpt-creator db (provision|import|seed) [options]
  gpt-creator run (compose up|logs|open) [options]
  gpt-creator verify [options]
  gpt-creator create-tasks [options]
  gpt-creator backlog [options]
  gpt-creator work-on-tasks [options]
  gpt-creator iterate [options]  # deprecated
  gpt-creator help
  gpt-creator version

Tips:
  • Use 'gpt-creator create-project …' for one-shot discovery → normalize → plan → generate → run.
  • 'verify' pings API/Web/Admin, checks MySQL, and ensures docs are present in staging.
  • 'create-tasks' snapshots Jira markdown; 'work-on-tasks' executes those stories with Codex.
  • 'work-on-tasks' supports batching (`--batch-size`) and pacing (`--sleep-between`) to control resource usage.
  • 'backlog' prints summaries (`--type epics|stories`), drills into hierarchy (`--item-children`), shows overall progress (`--progress`), or dumps a single task (`--task-details`).
  • 'iterate' is deprecated; it runs the legacy loop but prints a warning that suggests the commands above.
EOF
