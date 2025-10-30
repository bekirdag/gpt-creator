#!/usr/bin/env bash
# verify/check-telemetry.sh — non-invasive telemetry instrumentation checklist
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$ROOT_DIR}"

ok()   { printf '✅ %s\n' "$*"; }
bad()  { printf '❌ %s\n' "$*" >&2; }
warn() { printf '⚠️  %s\n' "$*"; }
info() { printf 'ℹ️  %s\n' "$*"; }

check_pattern() {
  local rel_path="$1"; shift || true
  local description="$1"; shift || true
  local pattern="$1"; shift || true
  local path="${PROJECT_ROOT%/}/$rel_path"
  if [[ ! -f "$path" ]]; then
    warn "$description missing (file not found: $rel_path)."
    return 0
  fi
  if LC_ALL=C grep -q "$pattern" -- "$path"; then
    ok "$description present in $rel_path"
  else
    warn "$description not detected in $rel_path"
  fi
}

info "Telemetry sanity checks (static)"
info "Project root: ${PROJECT_ROOT}";

check_pattern "apps/api/src/auth/auth.service.ts" \
  "AUTH_LOCKOUT security event dispatch" "AUTH_LOCKOUT"

check_pattern "apps/api/src/auth/admin-login.metrics.ts" \
  "Prometheus login lockout metric" "auth_login_lockout"

check_pattern "apps/api/src/auth/admin-lockout.metrics.ts" \
  "Lockout Redis fallback metric" "auth_redis_fallback_total"

check_pattern "apps/api/src/security-events/security-event.dispatcher.ts" \
  "Security event dispatcher hash payload" "hash_session_telemetry"

check_pattern "apps/admin/src/pages/Login.vue" \
  "Admin login remaining attempts banner" "remainingAttempts"

check_pattern "apps/admin/src/services/analytics.ts" \
  "Admin GA4 lockout event emission" "emitAdminLoginLockout"

info "Verifying GA4 lockout payload structure (if present)"
analytics_path="${PROJECT_ROOT%/}/apps/admin/src/services/analytics.ts"
if [[ -f "$analytics_path" ]]; then
  helper_path="$(gc_clone_python_tool "check_ga4_lockout_snippet.py" "${PROJECT_ROOT:-$PWD}")" || helper_path=""
  if [[ -z "$helper_path" ]]; then
    warn "Unable to prepare GA4 lockout snippet helper; skipping check"
  elif python3 "$helper_path" "$analytics_path"; then
    ok "GA4 lockout payload reference detected"
  else
    warn "GA4 lockout payload reference not found (manual review recommended)"
  fi
else
  warn "apps/admin/src/services/analytics.ts unavailable; skipping GA4 payload check"
fi

info "Telemetry checks completed (static analysis only)."
exit 0
