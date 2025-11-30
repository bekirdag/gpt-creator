#!/usr/bin/env bash
# HTTP wrappers.

: "${GC_WRAP_CURL:=1}"

gc_curl() {
  command curl \
    --retry "${GC_HTTP_RETRY_MAX:-5}" \
    --retry-delay 0 \
    --retry-all-errors \
    --retry-connrefused \
    --retry-max-time "${GC_HTTP_RETRY_MAX_TIME:-60}" \
    "$@"
}

gc_wrap_curl_if_enabled() {
  if [[ "${GC_WRAP_CURL}" == "1" ]] && command -v curl >/dev/null 2>&1; then
    curl() {
      gc_curl "$@"
    }
  fi
}
