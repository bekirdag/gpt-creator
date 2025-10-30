#!/usr/bin/env bash
# verify/check-traceability.sh — ensure traceability matrix is up to date.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ok()   { printf '✅ %s\n' "$*"; }
bad()  { printf '❌ %s\n' "$*" >&2; }
info() { printf 'ℹ️  %s\n' "$*"; }

info "Validating traceability matrix…"
if ! python3 "${ROOT_DIR}/scripts/python/update_traceability.py" --check; then
  bad "Traceability matrix out of date. Run: pnpm trace:update"
  exit 1
fi

if find "${ROOT_DIR}/docs" -type f -name '*.rej' -print -quit 2>/dev/null | grep -q .; then
  bad "Documentation patch rejects detected under docs/. Resolve *.rej before proceeding."
  exit 2
fi

ok "Traceability guard passed."
