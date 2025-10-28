#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "[bootstrap] starting in $ROOT"

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: Node.js not found" >&2
  exit 1
fi

NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]")"
if [[ "${NODE_MAJOR}" -lt 20 ]]; then
  echo "ERROR: Node >=20 required (found $(node -v))" >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  if command -v corepack >/dev/null 2>&1; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare pnpm@8 --activate || true
  else
    echo "ERROR: Corepack not available; install pnpm manually" >&2
    exit 1
  fi
fi

cd "$ROOT"
pnpm install --frozen-lockfile

if [[ -f "apps/api/prisma/schema.prisma" ]]; then
  pnpm --filter ./apps/api exec prisma generate || true
fi

pnpm -r run build --if-present || true
pnpm -r run typecheck --if-present || true

echo "[bootstrap] complete."
