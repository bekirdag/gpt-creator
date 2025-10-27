#!/usr/bin/env bash
# Robust, idempotent patch applier for git repos.

set -Eeuo pipefail

PATCH="${1:-}"
if [[ -z "$PATCH" || ! -f "$PATCH" ]]; then
  echo "patch not found: ${PATCH:-<none>}" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$root" ]]; then
  echo "not a git repo" >&2
  exit 2
fi
cd "$root"

if command -v dos2unix >/dev/null 2>&1; then
  dos2unix -q "$PATCH" || true
fi

if grep -qE '^From [0-9a-f]{40}\b' "$PATCH"; then
  git am --3way --keep-cr --signoff < "$PATCH"
  exit 0
fi

try_apply() {
  git apply --index --3way --whitespace=fix "$@" "$PATCH"
}

if try_apply; then
  ok=1
elif try_apply -p1; then
  ok=1
elif try_apply -p2; then
  ok=1
else
  git apply --reject --whitespace=fix "$PATCH" || true
  if git ls-files -o --exclude-standard | grep -q '\.rej$'; then
    echo "[patch] conflicts (.rej) present; manual/agent resolution needed." >&2
    exit 3
  fi
fi

if git diff --cached --quiet; then
  echo "[patch] no staged changes (already applied or no-op)."
  exit 0
fi

git commit -m "auto-apply patch: $(basename "$PATCH")" --no-verify
echo "[patch] applied and committed."
