#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LOG_FILE=""
TEE="1"

usage() {
  echo "Usage: run-and-filter.sh [--log FILE] [--no-tee] -- <command> [args...]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log)
      LOG_FILE="$2"; shift 2;;
    --no-tee)
      TEE="0"; shift;;
    --)
      shift; break;;
    *)
      usage;;
  esac
done

if [[ $# -lt 1 ]]; then
  usage
fi

if [[ -z "${LOG_FILE}" ]]; then
  LOG_FILE="$(mktemp -t gc_cmd_XXXX.log)"
fi

# Run the child and capture output
set +e
"$@" >"${LOG_FILE}" 2>&1
status=$?
set -e

# Apply exit code policy
POLICY="${SCRIPT_DIR}/python/exitcode_policy.py"
if [[ -x "${POLICY}" ]]; then
  if new_status=$("${POLICY}" --status "${status}" --log "${LOG_FILE}"); then
    status="${new_status}"
  fi
fi

# Stream output
if [[ "${TEE}" == "1" ]]; then
  cat "${LOG_FILE}"
fi

# Keep log for callers that want to inspect; don't delete
exit "${status}"
