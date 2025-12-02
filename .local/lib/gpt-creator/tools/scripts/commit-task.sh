#!/usr/bin/env bash
set -euo pipefail

TASK_ID="${1:-}"
if [[ -z "$TASK_ID" ]]; then
  echo "commit-task: task id missing" >&2
  exit 1
fi

RUN_ID="${2:-unknown-run}"
COMMIT_MESSAGE="${3:-}"

PROJECT_ROOT="${GC_PROJECT_ROOT:-${PROJECT_ROOT:-}}"
if [[ -z "$PROJECT_ROOT" ]]; then
  PROJECT_ROOT="$(pwd)"
else
  PROJECT_ROOT="${PROJECT_ROOT%/}"
fi

if [[ ! -d "$PROJECT_ROOT/.git" ]]; then
  echo "commit-task: git repository not found at ${PROJECT_ROOT}" >&2
  exit 0
fi

cd "$PROJECT_ROOT"

git config user.name  "${GC_GIT_USER_NAME:-gc-bot}"
git config user.email "${GC_GIT_USER_EMAIL:-gc-bot@wodo}"

# Stage relevant paths, excluding noisy caches and transient directories.
if ! git add -A :/ \
  -- ':!node_modules/**' \
     ':!.gpt-creator/tmp/**' \
     ':!.gpt-creator/logs/**' \
     ':!.gpt-creator/staging/plan/.runtime/**' \
     ':!.gpt-creator/state/**' \
     ':!*.rej'
then
  echo "commit-task: git add failed" >&2
  exit 1
fi

if git diff --cached --quiet --exit-code; then
  # Nothing staged — treat as clean exit.
  exit 0
fi

if [[ -z "$COMMIT_MESSAGE" ]]; then
  COMMIT_MESSAGE="chore(tasks): apply changes for ${TASK_ID}
Refs: ${TASK_ID}
GC-Run: ${RUN_ID}"
fi

git commit -m "$COMMIT_MESSAGE"

commit_hash="$(git rev-parse HEAD 2>/dev/null || printf '')"
if [[ -n "$commit_hash" ]]; then
  printf 'COMMIT_HASH\t%s\n' "$commit_hash"
fi

if [[ "${GC_AUTO_PUSH:-0}" == "1" ]]; then
  git push -u origin HEAD
fi
