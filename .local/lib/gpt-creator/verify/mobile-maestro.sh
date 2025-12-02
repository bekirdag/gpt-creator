#!/usr/bin/env bash
# verify/mobile-maestro.sh — run Maestro flows for iOS and Android
set -Eeuo pipefail

ok()   { printf '✅ %s\n' "$*"; }
err()  { printf '❌ %s\n' "$*" >&2; }
warn() { printf '⚠️  %s\n' "$*" >&2; }
info() { printf 'ℹ️  %s\n' "$*"; }

allow_skip="${GC_MOBILE_OPTIONAL:-0}"
if [[ "$allow_skip" == "true" || "$allow_skip" == "yes" ]]; then
  allow_skip=1
elif [[ "$allow_skip" == "false" ]]; then
  allow_skip=0
fi

fail_or_skip() {
  local msg="$1"
  if (( allow_skip )); then
    warn "${msg} (marking Maestro as skipped)"
    exit 3
  else
    err "$msg"
    exit 1
  fi
}

APP_DIR="${GC_MOBILE_APP_DIR:-}"
MAESTRO_FLOWS_DIR="${GC_MAESTRO_FLOWS_DIR:-}"
MAESTRO_DEVICE="${GC_MAESTRO_DEVICE:-}"
MAESTRO_DEVICE_IOS="${GC_MAESTRO_DEVICE_IOS:-}"
MAESTRO_DEVICE_ANDROID="${GC_MAESTRO_DEVICE_ANDROID:-}"
MAESTRO_ARGS="${GC_MAESTRO_ARGS:-}"

if [[ -z "$APP_DIR" ]]; then
  if [[ -n "${PROJECT_ROOT:-}" ]]; then
    if [[ -d "${PROJECT_ROOT}/apps/mobile" ]]; then
      APP_DIR="${PROJECT_ROOT}/apps/mobile"
    elif [[ -d "${PROJECT_ROOT}/mobile" ]]; then
      APP_DIR="${PROJECT_ROOT}/mobile"
    else
      APP_DIR="${PROJECT_ROOT}"
    fi
  else
    APP_DIR="$(pwd)"
  fi
fi

if [[ -z "$MAESTRO_FLOWS_DIR" ]]; then
  if [[ -d "${APP_DIR}/maestro" ]]; then
    MAESTRO_FLOWS_DIR="${APP_DIR}/maestro"
  elif [[ -n "${PROJECT_ROOT:-}" && -d "${PROJECT_ROOT}/maestro" ]]; then
    MAESTRO_FLOWS_DIR="${PROJECT_ROOT}/maestro"
  fi
fi

[[ -d "$APP_DIR" ]] || fail_or_skip "Mobile app directory not found: ${APP_DIR}"
[[ -n "$MAESTRO_FLOWS_DIR" ]] || fail_or_skip "Maestro flows directory not set; provide GC_MAESTRO_FLOWS_DIR or --maestro-flows"
[[ -d "$MAESTRO_FLOWS_DIR" ]] || fail_or_skip "Maestro flows directory not found: ${MAESTRO_FLOWS_DIR}"

if ! command -v maestro >/dev/null 2>&1; then
  fail_or_skip "maestro CLI not found; install it (https://maestro.mobile.dev/) before running mobile flows"
fi

if ! find "$MAESTRO_FLOWS_DIR" -type f \( -name "*.yaml" -o -name "*.yml" \) -print -quit | grep -q .; then
  fail_or_skip "No Maestro flow files (*.yaml) found under ${MAESTRO_FLOWS_DIR}"
fi

extra_args=()
if [[ -n "$MAESTRO_ARGS" ]]; then
  # shellcheck disable=SC2206
  extra_args=($MAESTRO_ARGS)
fi

devices=()
if [[ -n "$MAESTRO_DEVICE_IOS" ]]; then
  devices+=("${MAESTRO_DEVICE_IOS}|iOS")
fi
if [[ -n "$MAESTRO_DEVICE_ANDROID" ]]; then
  devices+=("${MAESTRO_DEVICE_ANDROID}|Android")
fi
if [[ ${#devices[@]} -eq 0 && -n "$MAESTRO_DEVICE" ]]; then
  devices+=("${MAESTRO_DEVICE}|device")
fi

[[ ${#devices[@]} -gt 0 ]] || fail_or_skip "No Maestro device provided; set GC_MAESTRO_DEVICE(_IOS/_ANDROID)"

status=0
for entry in "${devices[@]}"; do
  IFS='|' read -r device label <<<"$entry"
  info "Running Maestro (${label}) using device '${device}' and flows at ${MAESTRO_FLOWS_DIR}"
  if maestro test "${extra_args[@]}" -d "$device" "$MAESTRO_FLOWS_DIR"; then
    ok "Maestro ${label} passed"
  else
    err "Maestro ${label} failed"
    status=1
  fi
done

exit $status
