#!/usr/bin/env bash
# scripts/bootstrap_dependencies.sh
# Purpose: Ensure Node/PNPM are ready and install workspace deps once, idempotently.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[err]\033[0m  %s\n' "$*"; }

# --- Node version hygiene ----------------------------------------------------
EXPECTED_NODE_MAJOR="20"
if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node -v | sed 's/^v//')"
  NODE_MAJOR="${NODE_VER%%.*}"
  if [[ "$NODE_MAJOR" != "$EXPECTED_NODE_MAJOR" ]]; then
    warn "Node $NODE_VER detected; expected major $EXPECTED_NODE_MAJOR (log-only, continuing)"
  fi
else
  err "Node.js not found on PATH. Please install Node ${EXPECTED_NODE_MAJOR}.x and re-run."
  exit 1
fi

# --- Corepack/PNPM setup ------------------------------------------------------
PNPM_SPEC_DEFAULT="9"
discover_pnpm_spec() {
  local spec=""
  if [[ -f "$REPO_ROOT/package.json" ]]; then
    spec="$(grep -oE '"packageManager"\s*:\s*"pnpm@[^"]+"' "$REPO_ROOT/package.json" \
            | head -n1 | sed -E 's/.*"pnpm@([^"]+)".*/\1/')"
  fi
  if [[ -n "$spec" ]]; then
    printf '%s\n' "$spec"
  else
    printf '%s\n' "$PNPM_SPEC_DEFAULT"
  fi
}

activate_pnpm() {
  local pnpm_spec
  pnpm_spec="$(discover_pnpm_spec)"
  if command -v corepack >/dev/null 2>&1; then
    log "Enabling corepack and activating pnpm@$pnpm_spec"
    corepack enable >/dev/null 2>&1 || true
    corepack prepare "pnpm@${pnpm_spec}" --activate
  else
    warn "corepack not available; installing pnpm@$pnpm_spec globally via npm"
    npm i -g "pnpm@${pnpm_spec}"
  fi
  if ! command -v pnpm >/dev/null 2>&1; then
    err "pnpm not found after activation/installation."
    exit 1
  fi
  log "PNPM version: $(pnpm -v)"
}

activate_pnpm

# --- Install options & store --------------------------------------------------
STORE_DIR="${STORE_DIR:-$REPO_ROOT/.pnpm-store}"
export PNPM_HOME="${PNPM_HOME:-$REPO_ROOT/.pnpm}"
export PATH="$PNPM_HOME:$PATH"

INSTALL_ARGS=(
  "--store-dir=$STORE_DIR"
  "--prefer-offline"
)

if [[ "${CI:-}" == "true" || "${BOOTSTRAP_STRICT:-0}" == "1" ]]; then
  INSTALL_ARGS+=("--frozen-lockfile")
fi

if [[ "${PNPM_OFFLINE:-0}" == "1" ]]; then
  INSTALL_ARGS+=("--offline")
fi

cd "$REPO_ROOT"

if [[ -f "pnpm-lock.yaml" ]]; then
  log "Installing workspace dependencies with pnpm ${INSTALL_ARGS[*]}"
  pnpm install "${INSTALL_ARGS[@]}"
else
  warn "pnpm-lock.yaml not found; running non-frozen install (generates a new lockfile)"
  pnpm install "--store-dir=$STORE_DIR"
fi

if [[ -d ".husky" && "${CI:-}" != "true" ]]; then
  pnpm dlx husky install .husky >/dev/null 2>&1 || true
fi

log "Dependency bootstrap complete."
