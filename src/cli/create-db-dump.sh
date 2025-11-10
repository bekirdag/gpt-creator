#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

# shellcheck source=src/lib/create-db-dump/pipeline.sh
source "$ROOT_DIR/src/lib/create-db-dump/pipeline.sh"

usage() {
  gc_cli_render_template "help/create_db_dump_usage.txt"
}

PROJECT_PATH="$PWD"
MODEL="${CODEX_MODEL:-gpt-5-codex-mini}"
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
