#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

run_if_present() {
  local cmd=("$@")
  if "${cmd[@]}"; then
    return 0
  fi
  return 1
}

cd "$project_root"

if [[ -f "pnpm-lock.yaml" || -f "pnpm-workspace.yaml" ]]; then
  if command_exists pnpm; then
    pnpm install --frozen-lockfile || pnpm install || true
    exit 0
  fi
fi

if [[ -f "package-lock.json" || -f "package.json" ]]; then
  if command_exists npm; then
    npm install --no-fund --no-audit || true
    exit 0
  fi
fi

if [[ -f "requirements.txt" ]]; then
  if command_exists pip3; then
    pip3 install -r requirements.txt || true
    exit 0
  elif command_exists pip; then
    pip install -r requirements.txt || true
    exit 0
  fi
fi

exit 0
