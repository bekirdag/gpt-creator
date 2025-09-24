#!/usr/bin/env bash
# shellcheck shell=bash
# http.sh — simple HTTP helpers (curl-based)

if [[ -n "${GC_LIB_HTTP_SH:-}" ]]; then return 0; fi
GC_LIB_HTTP_SH=1

# HTTP GET (returns body, no header)
http_get() {
  local url="$1"
  curl -sSL "$url"
}

# HTTP POST (JSON body, returns response)
http_post_json() {
  local url="$1"
  local body="$2"
  curl -sSL -X POST -H "Content-Type: application/json" -d "$body" "$url"
}

# HTTP PUT (JSON body, returns response)
http_put_json() {
  local url="$1"
  local body="$2"
  curl -sSL -X PUT -H "Content-Type: application/json" -d "$body" "$url"
}

# HTTP DELETE (returns response)
http_delete() {
  local url="$1"
  curl -sSL -X DELETE "$url"
}
