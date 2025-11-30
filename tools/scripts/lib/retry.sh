#!/usr/bin/env bash
# Retry and timeout utilities.

gc_is_transient_status() {
  local status="${1:-0}"
  [[ "$status" == "124" || "$status" == "137" || "$status" == "143" || "$status" == "255" ]]
}

gc_is_transient_message() {
  local msg
  msg="$(cat | tr -d '\r' || true)"
  [[ "$msg" =~ (rate[- ]?limit|429|5[0-9]{2}|ECONNRESET|ECONNREFUSED|ETIMEDOUT|ETIMEOUT|socket\ hang\ up|TLS\ handshake\ timeout|temporary\ failure) ]]
}

gc_classify_error() {
  local status="${1:-0}"
  local cmd="${2:-}"
  local class="PERMANENT"
  local reason=""
  if gc_is_transient_status "$status"; then
    class="TRANSIENT"
    reason="Exit code ${status} considered transient."
  fi
  if [[ "$cmd" =~ (curl|wget|http|fetch|git[[:space:]]+(fetch|push)|pnpm|npm|node) ]]; then
    class="TRANSIENT"
    reason="Network/IO command '${cmd}' failed with ${status}."
  fi
  GC_LAST_ERROR_CLASS="$class"
  GC_LAST_ERROR_REASON="${reason:-Command '${cmd}' exited with status ${status}.}"
  if [[ -n "$GC_LAST_ERROR_REASON" ]]; then
    gc_error_summary_add "$GC_LAST_ERROR_REASON"
  fi
}

gc_msleep() {
  local ms="${1:-0}"
  local seconds="0.05"
  if command -v awk >/dev/null 2>&1; then
    seconds="$(awk -v ms="$ms" 'BEGIN { printf "%.3f", (ms/1000.0) }' 2>/dev/null || echo "0.05")"
  fi
  sleep "$seconds"
}

gc_backoff_sleep() {
  local attempt="${1:-1}"
  local base_ms="${GC_RETRY_BASE_MS:-500}"
  local max_ms="${GC_RETRY_MAX_MS:-8000}"
  local jitter_ms="${GC_RETRY_JITTER_MS:-250}"
  local pow=$(( 1 << (attempt - 1) ))
  local wait=$(( base_ms * pow ))
  (( wait > max_ms )) && wait="$max_ms"
  local jitter=$(( RANDOM % (jitter_ms + 1) ))
  gc_msleep "$(( wait + jitter ))"
}

gc__timeout_bin() {
  if command -v timeout >/dev/null 2>&1; then
    echo timeout
    return 0
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    echo gtimeout
    return 0
  fi
  echo ""
}

gc_run_with_timeout() {
  local seconds="${1:-}"
  shift || true
  if [[ "${1:-}" == "--" ]]; then
    shift || true
  fi
  local timeout_bin
  timeout_bin="$(gc__timeout_bin)"
  if [[ -n "$timeout_bin" && -n "$seconds" && "$seconds" != "0" ]]; then
    "$timeout_bin" -k 5s "${seconds}s" "$@"
  else
    "$@"
  fi
}

gc_with_retries() {
  local max="${1:-3}"
  shift || true
  local timeout_sec="${GC_STEP_TIMEOUT_SEC:-}"
  while (($#)); do
    case "$1" in
      --timeout|--timeout-sec)
        timeout_sec="${2:-}"
        shift 2 || true
        ;;
      --)
        shift || true
        break
        ;;
      *)
        break
        ;;
    esac
  done
  if [[ "${1:-}" == "--" ]]; then
    shift || true
  fi
  if (($# == 0)); then
    printf 'gc_with_retries: command required\n' >&2
    return 1
  fi
  local attempt=1 status=0 tmp=""
  : "${GC_RETRY_ATTEMPTS:=0}"
  while :; do
    tmp="$(mktemp "${TMPDIR:-/tmp}/gc.try.XXXXXX" 2>/dev/null || mktemp)"
    if [[ -n "$timeout_sec" && "$timeout_sec" != "0" ]]; then
      {
        gc_run_with_timeout "$timeout_sec" -- "$@" 2>"$tmp"
        status=$?
      } || true
      if (( status == 124 )); then
        GC_LAST_TIMEOUT_SECONDS="$timeout_sec"
        GC_LAST_ERROR_REASON="Timed out after ${timeout_sec}s (attempt ${attempt}/${max})."
        GC_LAST_ERROR_CLASS="TRANSIENT"
        gc_error_summary_add "$GC_LAST_ERROR_REASON for: $*"
      fi
    else
      {
        "$@" 2>"$tmp"
        status=$?
      } || true
    fi
    if (( status == 0 )); then
      rm -f "$tmp"
      GC_RETRY_ATTEMPTS="$attempt"
      GC_LAST_TIMEOUT_SECONDS=0
      return 0
    fi
    if gc_is_transient_status "$status" || gc_is_transient_message <"$tmp"; then
      if (( attempt < max )); then
        gc_backoff_sleep "$attempt"
        (( attempt++ ))
        rm -f "$tmp"
        continue
      fi
    fi
    GC_RETRY_ATTEMPTS="$attempt"
    GC_LAST_ERROR_STATUS="$status"
    GC_LAST_ERROR_CMD="$*"
    gc_classify_error "$status" "$*"
    if (( status == 124 )) && [[ -n "${GC_LAST_TIMEOUT_SECONDS:-}" ]]; then
      GC_LAST_ERROR_REASON="Timed out after ${GC_LAST_TIMEOUT_SECONDS}s (attempts exhausted: ${attempt}/${max})."
      GC_LAST_ERROR_CLASS="TRANSIENT"
      gc_error_summary_add "$GC_LAST_ERROR_REASON for: $*"
    fi
    cat "$tmp" >&2 || true
    rm -f "$tmp"
    return "$status"
  done
}
