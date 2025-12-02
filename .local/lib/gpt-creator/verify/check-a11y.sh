#!/usr/bin/env bash
# verify/check-a11y.sh — run accessibility checks with pa11y
set -Eeuo pipefail

URLS=("$@")
if [[ "${#URLS[@]}" -eq 0 ]]; then
  URLS=("http://localhost:8080/" "http://localhost:8080/admin/")
fi

if command -v npx >/dev/null 2>&1; then
  for u in "${URLS[@]}"; do
    echo "Running pa11y on: $u"
    npx -y pa11y@6.1.1 "$u" --reporter console --timeout 60000
  done
  echo "✅ a11y checks completed (pa11y)."
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  for u in "${URLS[@]}"; do
    echo "Running pa11y in Docker on: $u"
    docker run --rm --network host ghcr.io/pa11y/pa11y:latest "$u" --reporter console --timeout 60000
  done
  echo "✅ a11y checks completed (Docker pa11y)."
  exit 0
fi

echo "⚠️  pa11y unavailable. Install Node (npx) or Docker."
exit 3
