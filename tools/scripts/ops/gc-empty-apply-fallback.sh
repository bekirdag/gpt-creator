#!/usr/bin/env bash
set -euo pipefail

TASK_ID="${1:-unknown-task}"
STORY_ID="${2:-unknown-story}"

ROOT="$(git rev-parse --show-toplevel)"
EVIDE_DIR="$ROOT/docs/qa/evidence/${STORY_ID}/${TASK_ID}"
EVIDE_FILE="$EVIDE_DIR/checkpoint.md"

mkdir -p "$EVIDE_DIR"

if [ ! -s "$EVIDE_FILE" ]; then
  {
    echo "# Checkpoint — ${STORY_ID}/${TASK_ID}"
    echo ""
    echo "Generated because agent reply contained no actionable \`changes\`."
    echo "- Timestamp: $(date -u +%FT%TZ)"
    echo "- Runner: gc-empty-apply-fallback"
    echo ""
    echo "## What was attempted"
    echo "- See raw outputs under .gpt-creator/staging/plan/work/runs/*/${STORY_ID}/out/"
  } > "$EVIDE_FILE"
fi

git add "$EVIDE_FILE"
