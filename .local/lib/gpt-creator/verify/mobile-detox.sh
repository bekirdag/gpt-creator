#!/usr/bin/env bash
# verify/mobile-detox.sh — run Detox suites for iOS and Android
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
    warn "${msg} (marking Detox as skipped)"
    exit 3
  else
    err "$msg"
    exit 1
  fi
}

APP_DIR="${GC_MOBILE_APP_DIR:-}"
CONFIG_IOS="${GC_DETOX_CONFIG_IOS:-}"
CONFIG_ANDROID="${GC_DETOX_CONFIG_ANDROID:-}"
DETOX_ARGS="${GC_DETOX_ARGS:-}"

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

[[ -d "$APP_DIR" ]] || fail_or_skip "Mobile app directory not found: ${APP_DIR}"
cd "$APP_DIR"

detox_cmd=()
if command -v detox >/dev/null 2>&1; then
  detox_cmd=("detox")
elif [[ -x "./node_modules/.bin/detox" ]]; then
  detox_cmd=("./node_modules/.bin/detox")
elif command -v npx >/dev/null 2>&1; then
  detox_cmd=("npx" "detox")
fi
[[ ${#detox_cmd[@]} -gt 0 ]] || fail_or_skip "detox CLI not found; install it (npm/yarn/pnpm) or expose ./node_modules/.bin/detox"

detect_config() {
  local platform="$1" result=""
  if command -v python3 >/dev/null 2>&1; then
    if result="$(
      python3 - <<'PY' "$APP_DIR" "$platform" 2>/dev/null
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
platform = sys.argv[2].lower()
pkg = root / "package.json"
if not pkg.exists():
    sys.exit(1)
try:
    data = json.loads(pkg.read_text())
except Exception:
    sys.exit(1)
configs = data.get("detox", {}).get("configurations", {}) or {}
if not configs:
    sys.exit(1)
for name in configs:
    if platform in name.lower():
        print(name)
        sys.exit(0)
print(next(iter(configs)))
PY
    )"; then
      :
    else
      result=""
    fi
  fi
  printf '%s' "$result"
}

if [[ -z "$CONFIG_IOS" ]]; then
  CONFIG_IOS="$(detect_config ios)"
fi
if [[ -z "$CONFIG_ANDROID" ]]; then
  CONFIG_ANDROID="$(detect_config android)"
fi

if [[ -z "$CONFIG_IOS" && -z "$CONFIG_ANDROID" ]]; then
  fail_or_skip "No Detox configurations found; set GC_DETOX_CONFIG_IOS/GC_DETOX_CONFIG_ANDROID or add configs under detox.configurations in package.json"
fi

extra_args=()
if [[ -n "$DETOX_ARGS" ]]; then
  # shellcheck disable=SC2206
  extra_args=($DETOX_ARGS)
fi

status=0

run_detox() {
  local platform="$1" config="$2"
  info "Running Detox (${platform}) with config '${config}' from ${APP_DIR}"
  if DETOX_PLATFORM="$platform" "${detox_cmd[@]}" test -c "$config" "${extra_args[@]}"; then
    ok "Detox ${platform} passed"
  else
    err "Detox ${platform} failed"
    status=1
  fi
}

[[ -n "$CONFIG_IOS" ]] && run_detox ios "$CONFIG_IOS"
[[ -n "$CONFIG_ANDROID" ]] && run_detox android "$CONFIG_ANDROID"

exit $status
