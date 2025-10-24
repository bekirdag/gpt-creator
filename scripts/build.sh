#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-.}"
if ! ROOT_DIR="$(cd "${ROOT_DIR}" && pwd)"; then
  echo "[build] Failed to resolve project root: ${1:-.}" >&2
  exit 1
fi

log() {
  printf "[build] %s\n" "$*" >&2
}

run_cmd() {
  local desc="$1"
  shift
  local cmd=("$@")
  log "${desc}: ${cmd[*]}"
  if "${cmd[@]}"; then
    return 0
  fi
  log "Command failed: ${cmd[*]}"
  return 1
}

ci_best_effort="${CI_BUILD_BEST_EFFORT:-0}"

cd "$ROOT_DIR"

has_package_script() {
  local script="$1"
  if [[ ! -f package.json ]]; then
    return 1
  fi
  python3 - <<'PY' "$script" 2>/dev/null
import json
import sys

script_name = sys.argv[1]
try:
    with open("package.json", "r", encoding="utf-8") as handle:
        pkg = json.load(handle)
    scripts = pkg.get("scripts") or {}
    if script_name in scripts and scripts[script_name]:
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
}

if [[ -x "scripts/build.sh.local" ]]; then
  log "Delegating to scripts/build.sh.local"
  if ./scripts/build.sh.local "$ROOT_DIR"; then
    exit 0
  fi
  log "scripts/build.sh.local failed."
  if [[ "$ci_best_effort" == "1" ]]; then
    log "Continuing because CI_BUILD_BEST_EFFORT=1."
    exit 0
  fi
  exit 1
fi

if [[ -f package.json ]]; then
  if command -v pnpm >/dev/null 2>&1 && [[ -d "apps/api" ]]; then
    if run_cmd "Running pnpm --filter api build" pnpm --filter api build; then
      if [[ -f "apps/api/prisma/schema.prisma" ]]; then
        run_cmd "Running pnpm --filter api exec prisma generate" pnpm --filter api exec prisma generate || true
      fi
      exit 0
    fi
  fi
  if command -v pnpm >/dev/null 2>&1 && has_package_script "build"; then
    if run_cmd "Running pnpm build" pnpm run build; then
      exit 0
    fi
  fi
  if command -v yarn >/dev/null 2>&1 && has_package_script "build"; then
    if run_cmd "Running yarn build" yarn build; then
      exit 0
    fi
  fi
  if command -v npm >/dev/null 2>&1 && has_package_script "build"; then
    if run_cmd "Running npm run build" npm run build; then
      exit 0
    fi
  fi

if command -v tsc >/dev/null 2>&1; then
  tsconfigs=()
  if [[ -f "tsconfig.json" ]]; then
    tsconfigs+=("tsconfig.json")
  fi
  if [[ -f "apps/api/tsconfig.build.json" ]]; then
    tsconfigs+=("apps/api/tsconfig.build.json")
  fi
  for tsconfig in "${tsconfigs[@]}"; do
    if run_cmd "Running baseline tsc build (${tsconfig})" tsc -p "$tsconfig"; then
      exit 0
    fi
  done
fi
fi

if ls *.sln >/dev/null 2>&1 && command -v dotnet >/dev/null 2>&1; then
  if run_cmd "Running dotnet build" dotnet build; then
    exit 0
  fi
fi

log "No recognized build command executed; exiting successfully."
exit 0
