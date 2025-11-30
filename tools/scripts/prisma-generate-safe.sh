#!/usr/bin/env bash

set -euo pipefail

if [[ "${GC_TRACE:-}" == "1" ]]; then
  set -x
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USAGE_FILE="${SCRIPT_DIR}/usage/prisma-generate-safe.txt"

# ---------------- Helper text & functions -----------------

print_usage() {
  if [[ -f "$USAGE_FILE" ]]; then
    cat "$USAGE_FILE"
  else
    printf '%s\n' \
      'Usage: prisma-generate-safe.sh [project-root] [-- prisma-cli-args...]' \
      '' \
      'Runs `prisma generate` with workspace-independent safeguards.'
  fi
}

# ---------------- Main script -----------------

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  print_usage
  exit 0
fi

project_root="${GC_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
if [[ $# -gt 0 && "${1:-}" != "--" && ! "${1:-}" =~ ^- ]]; then
  project_root="$1"
  shift
fi

if [[ ! -d "$project_root" ]]; then
  printf 'prisma-generate-safe: project root "%s" does not exist.\n' "$project_root" >&2
  exit 1
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

extra_args=("$@")

cd "$project_root"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

declare -a prisma_runners=()
if command_exists pnpm && [[ -f pnpm-lock.yaml || -f pnpm-workspace.yaml ]]; then
  prisma_runners+=("pnpm exec prisma")
fi
if command_exists npx; then
  prisma_runners+=("npx --yes prisma")
fi
if command_exists prisma; then
  prisma_runners+=("prisma")
fi

if ((${#prisma_runners[@]} == 0)); then
  printf 'prisma-generate-safe: no Prisma CLI available (pnpm, npx, or prisma).\n' >&2
  exit 127
fi

# Provide a writable engines cache if the package manager store is immutable.
if [[ -z "${PRISMA_ENGINES_OVERRIDE:-}" ]]; then
  override_root="${project_root}/.gpt-creator/prisma-engines"
  override_tmp="${override_root}/tmp"
  mkdir -p "$override_tmp"
  export PRISMA_ENGINES_OVERRIDE="$override_root"
  export TMPDIR="$override_tmp"
fi

export PRISMA_HIDE_UPDATE_MESSAGE=1
export NO_COLOR=1

status=1
for runner_cmd in "${prisma_runners[@]}"; do
  read -r -a runner_parts <<< "$runner_cmd"
  if [[ "${runner_parts[0]}" == "pnpm" ]]; then
    set +e
    PNPM_IGNORE_NODE_VERSION="${PNPM_IGNORE_NODE_VERSION:-1}" \
      "${runner_parts[@]}" generate "${extra_args[@]}"
    status=$?
    set -e
  else
    set +e
    "${runner_parts[@]}" generate "${extra_args[@]}"
    status=$?
    set -e
  fi
  if (( status == 0 )); then
    break
  fi
done

exit $status
