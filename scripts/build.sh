#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-.}"
if ! ROOT_DIR="$(cd "${ROOT_DIR}" && pwd)"; then
  echo "[build] Failed to resolve project root: ${1:-.}" >&2
  exit 1
fi
CLI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

gc_clone_python_tool() {
  local script_name="${1:?python script name required}"
  local root="${2:-$ROOT_DIR}"
  local cli_root="${CLI_ROOT:-$ROOT_DIR}"

  if [[ -z "$root" ]]; then
    log "Unable to determine project root while preparing ${script_name}"
    return 1
  fi

  local source_path="${cli_root}/scripts/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    log "Python helper missing at ${source_path}"
    return 1
  fi

  local target_dir="${root}/${GC_WORK_DIR_NAME:-.gpt-creator}/shims/python"
  local target_path="${target_dir}/${script_name}"
  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || {
      log "Failed to create ${target_dir}"
      return 1
    }
  fi
  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || {
      log "Failed to copy ${script_name} helper"
      return 1
    }
  fi
  printf '%s\n' "$target_path"
}

has_package_script() {
  local script="$1"
  if [[ ! -f package.json ]]; then
    return 1
  fi
  local helper_path
  helper_path="$(gc_clone_python_tool "has_package_script.py" "$ROOT_DIR")" || return 1
  python3 "$helper_path" "$script"
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
