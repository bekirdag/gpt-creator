#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

source "$ROOT_DIR/src/lib/create-sds/pipeline.sh"

usage() {
  cat <<'USAGE'
Usage: gpt-creator create-sds [options]

Generate a System Design Specification (SDS) from the staged Product Requirements Document (PDR) using Codex.

Options:
  --project PATH   Project root (defaults to current directory)
  --model NAME     Codex model to use (default: gpt-5-codex)
  --dry-run        Skip Codex calls but emit the derived prompts
  --force          Regenerate all stages even if outputs already exist
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

csds::init "$PROJECT_PATH" "$MODEL" "$DRY_RUN" "$FORCE"
csds::run_pipeline

csds::log "create-sds completed successfully"
