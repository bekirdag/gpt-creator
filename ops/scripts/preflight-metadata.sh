#!/usr/bin/env bash
# Hydrate backlog metadata and doc indexes before running work-on-tasks.
set -euo pipefail

PROJECT=${1:-"$PWD"}

if ! command -v gpt-creator >/dev/null 2>&1; then
  echo "gpt-creator not on PATH" >&2
  exit 127
fi

gpt-creator normalize --project "$PROJECT" || true
gpt-creator refine-tasks --project "$PROJECT" --force
gpt-creator migrate-tasks --project "$PROJECT" --force || true

MANIFEST="$PROJECT/.gpt-creator/staging/plan/tasks/manifest.json"
if [[ -s "$MANIFEST" ]]; then
  echo "Metadata manifest present: $(wc -c < "$MANIFEST") bytes"
fi
