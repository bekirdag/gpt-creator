#!/usr/bin/env bash
# Run shellcheck across core gpt-creator shell scripts.

set -euo pipefail

if ! command -v shellcheck >/dev/null 2>&1; then
  printf 'shellcheck not installed; skipping shell lint.\n' >&2
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

shopt -s nullglob
targets=(
  "${REPO_ROOT}/scripts/commands/"*.sh
  "${REPO_ROOT}/scripts/lib/"*.sh
)
shopt -u nullglob

if ((${#targets[@]} == 0)); then
  printf 'No shell targets found.\n' >&2
  exit 0
fi

shellcheck "${targets[@]}"
