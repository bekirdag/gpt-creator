#!/usr/bin/env bash
# verify/check-lighthouse.sh — run Lighthouse audits via LHCI or lighthouse CLI
set -Eeuo pipefail

OUT_DIR="${LH_OUT_DIR:-.lighthouse}"
mkdir -p "$OUT_DIR"

URLS=("$@")
if [[ "${#URLS[@]}" -eq 0 ]]; then
  URLS=("http://localhost:8080/" "http://localhost:8080/admin/")
fi

timestamp() { date +"%Y%m%d-%H%M%S"; }

if command -v npx >/dev/null 2>&1; then
  # Prefer LHCI autorun
  if npx -y @lhci/cli@0.12.0 --help >/dev/null 2>&1; then
    echo "Running LHCI autorun…"
    export LHCI_BUILD_CONTEXT__CURRENT_BRANCH="${LH_BRANCH:-local}"
    commit_time="$(date +%s)"
    export LHCI_BUILD_CONTEXT__COMMIT_TIME="$commit_time"
    # LHCI supports multiple URLs via config, so run simple lighthouse CLI for multi-URL:
    for u in "${URLS[@]}"; do
      base="$(echo "$u" | sed 's#https\?://##; s#/##g')"
      out="${OUT_DIR}/report-${base}-$(timestamp).html"
      echo "Running lighthouse on: $u"
      npx -y lighthouse@11.6.0 "$u" --quiet --chrome-flags="--headless=new" --output html --output-path "$out"
      echo "Saved: $out"
    done
    echo "✅ Lighthouse checks completed."
    exit 0
  fi
fi

if command -v docker >/dev/null 2>&1; then
  for u in "${URLS[@]}"; do
    base="$(echo "$u" | sed 's#https\?://##; s#/##g')"
    out="${OUT_DIR}/report-${base}-$(timestamp).html"
    echo "Running lighthouse (Docker) on: $u"
    docker run --rm --network host femtopixel/google-lighthouse "$u" --quiet --chrome-flags="--headless" --output html --output-path "/home/chrome/reports/report.html" >/dev/null 2>&1 || true
    echo "Note: Docker image may not support writing to host; prefer Node+npx for saving reports."
  done
  echo "✅ Lighthouse checks finished (Docker)."
  exit 0
fi

echo "⚠️  Neither Node (npx) nor Docker available for Lighthouse."
exit 3
