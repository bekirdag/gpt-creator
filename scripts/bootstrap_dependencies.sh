#!/usr/bin/env bash
set -euo pipefail

# Resolves the project root from the first argument (defaults to CWD).
ROOT_DIR="${1:-.}"
if ! ROOT_DIR="$(cd "${ROOT_DIR}" && pwd)"; then
  echo "[bootstrap] Failed to resolve project root: ${1:-.}" >&2
  exit 1
fi

LOG_FILE="${CI_BOOTSTRAP_LOG_FILE:-}"
if [[ -z "${LOG_FILE}" ]]; then
  LOG_FILE="$(mktemp "${TMPDIR:-/tmp}/gpt-bootstrap.XXXXXX.log")"
fi
export CI_BOOTSTRAP_LOG_FILE="$LOG_FILE"

note() {
  printf "[bootstrap] %s\n" "$*" >&2
}

run_attempts() {
  local desc="$1"
  shift
  local attempt success=1

  note "${desc}"
  for attempt in "$@"; do
    [[ -n "$attempt" ]] || continue
    # shellcheck disable=SC2206 # intentional word splitting for command tokens
    local cmd=( $attempt )
    note "  -> ${attempt}"
    if "${cmd[@]}" >>"$LOG_FILE" 2>&1; then
      success=0
      break
    fi
    note "     failed (see ${LOG_FILE})"
  done
  return $success
}

cd "$ROOT_DIR"

status=0
handled=0

if [[ -f pnpm-lock.yaml || -f pnpm-workspace.yaml ]]; then
  handled=1
  if command -v pnpm >/dev/null 2>&1; then
    if run_attempts "Installing dependencies with pnpm (log: ${LOG_FILE})" \
        "pnpm -w install" \
        "pnpm -w install --no-frozen-lockfile"; then
      status=0
    else
      status=1
    fi
  else
    note "pnpm lockfile detected but pnpm is not installed."
    status=1
  fi
elif [[ -f yarn.lock ]]; then
  handled=1
  if command -v yarn >/dev/null 2>&1; then
    if run_attempts "Installing dependencies with yarn (log: ${LOG_FILE})" \
        "yarn install --immutable" \
        "yarn install"; then
      status=0
    else
      status=1
    fi
  else
    note "yarn.lock detected but yarn is not installed."
    status=1
  fi
elif [[ -f package-lock.json ]]; then
  handled=1
  if command -v npm >/dev/null 2>&1; then
    if run_attempts "Installing dependencies with npm (log: ${LOG_FILE})" \
        "npm ci" \
        "npm install"; then
      status=0
    else
      status=1
    fi
  else
    note "package-lock.json detected but npm is not installed."
    status=1
  fi
elif [[ -f requirements.txt ]]; then
  handled=1
  if command -v pip >/dev/null 2>&1; then
    note "Installing Python dependencies with pip (log: ${LOG_FILE})"
    if ! pip install -r requirements.txt >>"$LOG_FILE" 2>&1; then
      note "pip install -r requirements.txt failed (see ${LOG_FILE}) but continuing."
    fi
    status=0
  elif command -v pip3 >/dev/null 2>&1; then
    note "Installing Python dependencies with pip3 (log: ${LOG_FILE})"
    if ! pip3 install -r requirements.txt >>"$LOG_FILE" 2>&1; then
      note "pip3 install -r requirements.txt failed (see ${LOG_FILE}) but continuing."
    fi
    status=0
  else
    note "requirements.txt detected but pip is not installed."
    status=1
  fi
fi

if [[ $handled -eq 0 ]]; then
  note "No recognized dependency lockfile found; skipping bootstrap."
  status=0
fi

if [[ $status -eq 0 ]]; then
  if [[ ! -s "$LOG_FILE" ]]; then
    rm -f "$LOG_FILE"
  fi
  exit 0
fi

note "Dependency bootstrap failed; see ${LOG_FILE} for details."
if [[ "${CI_BOOTSTRAP_BEST_EFFORT:-0}" == "1" ]]; then
  note "Continuing because CI_BOOTSTRAP_BEST_EFFORT=1."
  exit 0
fi

exit 1

