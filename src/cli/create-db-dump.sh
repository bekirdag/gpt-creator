#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=src/lib/create-db-dump/pipeline.sh
source "$ROOT_DIR/src/lib/create-db-dump/pipeline.sh"

usage() {
  cat <<'USAGE'
Usage: gpt-creator create-db-dump [options]

Generate MySQL schema and seed dumps directly from the SDS.

Options:
  --project PATH   Project root (defaults to current directory)
  --model NAME     Codex model to use (default: gpt-5-codex)
  --dry-run        Prepare prompts but do not invoke Codex
  --force          Regenerate outputs even if they already exist
  -h, --help       Show this help message
USAGE
}

PROJECT_PATH="$PWD"
MODEL="${CODEX_MODEL:-gpt-5-codex}"
DRY_RUN=0
FORCE=0

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
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --force)
      FORCE=1
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

cddb::init "$PROJECT_PATH" "$MODEL" "$DRY_RUN" "$FORCE"
cddb::run_pipeline

cddb::log "create-db-dump completed successfully"
