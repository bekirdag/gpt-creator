#!/usr/bin/env bash
# verify/check-consent.sh — best‑effort cookie/consent banner verification
# Usage: verify/check-consent.sh [URL ...]
# Env:
#   CONSENT_PATTERNS   — regex of keywords to search in HTML (default: cookie|consent|privacy)
#   CONSENT_SELECTORS  — regex of selector/id/class markers (default includes cookie-consent variants)
set -Eeuo pipefail

URLS=("$@")
if [[ "${#URLS[@]}" -eq 0 ]]; then
  URLS=("http://localhost:8080/")
fi

PATTERNS="${CONSENT_PATTERNS:-cookie|consent|privacy}"
SELECTORS="${CONSENT_SELECTORS:-cookie-consent|cookie_banner|cookie-banner|data-testid=\"cookie-consent\"|id=\"cookie-consent\"|class=\"cookie-consent\"}"

ok()   { printf '✅ %s\n' "$*"; }
bad()  { printf '❌ %s\n' "$*" >&2; }
info() { printf 'ℹ️  %s\n' "$*"; }

curl_get() {
  local url="$1"
  curl -fsSL --retry 2 --retry-delay 1 "$url"
}

FAIL=0
for u in "${URLS[@]}"; do
  info "Checking consent banner on: $u"
  html="$(curl_get "$u" || true)"
  if [[ -z "${html}" ]]; then
    bad "Failed to fetch $u"
    FAIL=1
    continue
  fi

  if printf '%s' "$html" | grep -Eiq "$PATTERNS"; then
    ok "Found consent-related keywords: /$PATTERNS/"
  else
    bad "No consent/cookie/privacy keywords detected on page."
    FAIL=1
  fi

  if printf '%s' "$html" | grep -Eiq "$SELECTORS"; then
    ok "Detected consent UI selector/id/class markers."
  else
    info "No explicit consent selectors found (may be loaded dynamically)."
  fi

  if printf '%s' "$html" | grep -Eiq 'href=[^>]*(privacy|cookies)'; then
    ok "Found link to privacy/cookie policy."
  else
    info "No obvious privacy/cookie policy link detected."
  fi
done

if [[ "$FAIL" -eq 0 ]]; then
  ok "Consent checks completed (best‑effort)."
else
  bad "Consent checks failed."
  exit 1
fi
