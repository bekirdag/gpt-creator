#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
CHECK_SCRIPT="${SCRIPT_DIR}/i18n-check.js"

locales_root="${PROJECT_ROOT}/apps"
if [[ ! -d "$locales_root" ]]; then
  printf 'ok\n'
  exit 0
fi

if find "$locales_root" -type f -path '*/locales/*.rej' -print -quit | grep -q .; then
  printf 'blocked-merge-conflict\n'
  exit 3
fi

if [[ ! -f "$CHECK_SCRIPT" ]]; then
  printf 'ok\n'
  exit 0
fi

if ! command -v node >/dev/null 2>&1; then
  printf 'blocked-i18n-guard-error\n'
  exit 7
fi

set +e
guard_output="$(node "$CHECK_SCRIPT" 2>&1)"
guard_code=$?
set -e

case "$guard_code" in
  0)
    printf 'ok\n'
    exit 0
    ;;
  2)
    if [[ -n "$guard_output" ]]; then
      printf '%s\n' "$guard_output" >&2
    fi
    printf 'blocked-dependency(i18n_sync_required)\n'
    exit 6
    ;;
  *)
    if [[ -n "$guard_output" ]]; then
      printf '%s\n' "$guard_output" >&2
    fi
    printf 'blocked-i18n-guard-error\n'
    exit 7
    ;;
esac
