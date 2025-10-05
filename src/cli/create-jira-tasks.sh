#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

source "$ROOT_DIR/src/lib/create-jira-tasks/pipeline.sh"

usage() {
  cat <<'USAGE'
Usage: gpt-creator create-jira-tasks [options]

Generate Jira epics, user stories, and tasks directly from project documentation.

Options:
  --project PATH     Project root (defaults to current directory)
  --model NAME       Codex model to use (default: gpt-5-high)
  --force            Rebuild tasks.db from scratch (ignore saved progress)
  --dry-run          Prepare prompts but do not call Codex
  -h, --help         Show this help message
USAGE
}

PROJECT_PATH="$PWD"
MODEL="${CODEX_MODEL:-gpt-5-codex}"
FORCE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT_PATH="${2:?--project requires a path}"
      shift 2
      ;;
    --model)
      MODEL="${2:?--model requires a value}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

cjt::init "$PROJECT_PATH" "$MODEL" "$FORCE" 0 "$DRY_RUN"
cjt::run_pipeline

cjt::log "create-jira-tasks completed successfully"
