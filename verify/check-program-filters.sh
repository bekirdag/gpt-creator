#!/usr/bin/env bash
# verify/check-program-filters.sh — verify /programs filter behavior
# Dependencies: curl, jq
#
# Usage:
#   verify/check-program-filters.sh [API_BASE]
#
# Env (override defaults as needed):
#   PROGRAMS_ENDPOINT   — full endpoint (default: $API_BASE/programs)
#   TYPE_PARAM          — query param for type (default: type)
#   INSTRUCTOR_PARAM    — query param for instructor (default: instructor)
#   LEVEL_PARAM         — query param for level (default: level)
#   DATE_FROM_PARAM     — query param for date-from (default: from)
#   DATE_TO_PARAM       — query param for date-to (default: to)
#
#   TYPE_VALUE          — example value to test (e.g., "yoga")
#   INSTRUCTOR_VALUE    — example value to test (e.g., "123")
#   LEVEL_VALUE         — example value to test (e.g., "beginner")
#   DATE_FROM_VALUE     — ISO date (e.g., "2024-01-01")
#   DATE_TO_VALUE       — ISO date (e.g., "2024-12-31")
#
#   TYPE_FIELD          — jq field path candidates (comma-separated). Default: .type,.category
#   INSTRUCTOR_FIELD    — jq field path candidates. Default: .instructorId,.instructor.id
#   LEVEL_FIELD         — jq field path candidates. Default: .level
#   DATE_FIELD          — jq field path candidates. Default: .startDate,.date
set -Eeuo pipefail

API_BASE="${1:-${GC_DEFAULT_API_URL:-http://localhost:3000/api/v1}}"
PROGRAMS_ENDPOINT="${PROGRAMS_ENDPOINT:-${API_BASE%/}/programs}"

TYPE_PARAM="${TYPE_PARAM:-type}"
INSTRUCTOR_PARAM="${INSTRUCTOR_PARAM:-instructor}"
LEVEL_PARAM="${LEVEL_PARAM:-level}"
DATE_FROM_PARAM="${DATE_FROM_PARAM:-from}"
DATE_TO_PARAM="${DATE_TO_PARAM:-to}"

TYPE_FIELD="${TYPE_FIELD:-.type,.category}"
INSTRUCTOR_FIELD="${INSTRUCTOR_FIELD:-.instructorId,.instructor.id}"
LEVEL_FIELD="${LEVEL_FIELD:-.level}"
DATE_FIELD="${DATE_FIELD:-.startDate,.date}"

ok()   { printf '✅ %s\n' "$*"; }
bad()  { printf '❌ %s\n' "$*" >&2; }
info() { printf 'ℹ️  %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { bad "Missing dependency: $1"; exit 2; }; }
need curl
need jq

urlencode() {
  local LC_ALL=C
  local value="${1:-}"
  python3 - "$value" <<'PY'
import sys
from urllib.parse import quote

print(quote(sys.argv[1] if len(sys.argv) > 1 else ""))
PY
}

fetch() {
  local url="$1"
  curl -fsS --retry 2 --retry-delay 1 "$url"
}

resolve_field() {
  # $1: baseline json
  # $2: candidate CSV (comma-separated paths)
  local baseline="$1"
  local candidates="$2"
  local IFS=','
  for path in $candidates; do
    if jq -e ".[0] | (${path})" >/dev/null 2>&1 <<<"$baseline"; then
      echo "$path"
      return 0
    fi
  done
  echo ""
}

all_eq() {
  # $1 json, $2 jq path, $3 expected string
  local json="$1" path="$2" expected="$3"
  jq -e --arg v "$expected" "all(.[]; (${path} // empty | tostring) == \$v)" >/dev/null <<<"$json"
}

all_in_range() {
  # $1 json, $2 jq date path, $3 from, $4 to
  local json="$1" path="$2" from="$3" to="$4"
  jq -e --arg from "$from" --arg to "$to" '
    def ts(x): try (x | fromdateiso8601) catch 0;
    all(.[]; (('"$path"') as $d | (ts($d) >= ts($from) and ts($d) <= ts($to)) ))
  ' >/dev/null <<<"$json"
}

FAIL=0

info "Endpoint: $PROGRAMS_ENDPOINT"
baseline="$(fetch "$PROGRAMS_ENDPOINT" || echo "[]")"
count_base="$(jq 'length' <<<"$baseline" 2>/dev/null || echo 0)"
ok "Baseline count: $count_base"

# TYPE filter
if [[ -n "${TYPE_VALUE:-}" ]]; then
  field="$(resolve_field "$baseline" "$TYPE_FIELD")"; [[ -z "$field" ]] && field="$(cut -d, -f1 <<<"$TYPE_FIELD")"
  q="${PROGRAMS_ENDPOINT}?${TYPE_PARAM}=$(urlencode "$TYPE_VALUE")"
  data="$(fetch "$q" || echo "[]")"
  if all_eq "$data" "$field" "$TYPE_VALUE"; then
    ok "Type filter: ${TYPE_PARAM}=${TYPE_VALUE} (field $field) ✔"
  else
    bad "Type filter mismatch: param ${TYPE_PARAM}=${TYPE_VALUE}, field $field does not match for all items."
    FAIL=1
  fi
fi

# INSTRUCTOR filter
if [[ -n "${INSTRUCTOR_VALUE:-}" ]]; then
  field="$(resolve_field "$baseline" "$INSTRUCTOR_FIELD")"; [[ -z "$field" ]] && field="$(cut -d, -f1 <<<"$INSTRUCTOR_FIELD")"
  q="${PROGRAMS_ENDPOINT}?${INSTRUCTOR_PARAM}=$(urlencode "$INSTRUCTOR_VALUE")"
  data="$(fetch "$q" || echo "[]")"
  if all_eq "$data" "$field" "$INSTRUCTOR_VALUE"; then
    ok "Instructor filter: ${INSTRUCTOR_PARAM}=${INSTRUCTOR_VALUE} (field $field) ✔"
  else
    bad "Instructor filter mismatch: param ${INSTRUCTOR_PARAM}=${INSTRUCTOR_VALUE}, field $field does not match for all items."
    FAIL=1
  fi
fi

# LEVEL filter
if [[ -n "${LEVEL_VALUE:-}" ]]; then
  field="$(resolve_field "$baseline" "$LEVEL_FIELD")"; [[ -z "$field" ]] && field="$(cut -d, -f1 <<<"$LEVEL_FIELD")"
  q="${PROGRAMS_ENDPOINT}?${LEVEL_PARAM}=$(urlencode "$LEVEL_VALUE")"
  data="$(fetch "$q" || echo "[]")"
  if all_eq "$data" "$field" "$LEVEL_VALUE"; then
    ok "Level filter: ${LEVEL_PARAM}=${LEVEL_VALUE} (field $field) ✔"
  else
    bad "Level filter mismatch: param ${LEVEL_PARAM}=${LEVEL_VALUE}, field $field does not match for all items."
    FAIL=1
  fi
fi

# DATE range filter
if [[ -n "${DATE_FROM_VALUE:-}" && -n "${DATE_TO_VALUE:-}" ]]; then
  field="$(resolve_field "$baseline" "$DATE_FIELD")"; [[ -z "$field" ]] && field="$(cut -d, -f1 <<<"$DATE_FIELD")"
  q="${PROGRAMS_ENDPOINT}?${DATE_FROM_PARAM}=$(urlencode "$DATE_FROM_VALUE")&${DATE_TO_PARAM}=$(urlencode "$DATE_TO_VALUE")"
  data="$(fetch "$q" || echo "[]")"
  if all_in_range "$data" "$field" "$DATE_FROM_VALUE" "$DATE_TO_VALUE"; then
    ok "Date filter: ${DATE_FROM_PARAM}..${DATE_TO_PARAM} (field $field) ✔"
  else
    bad "Date filter mismatch: items not within ${DATE_FROM_VALUE}..${DATE_TO_VALUE} for field $field."
    FAIL=1
  fi
fi

if [[ "$FAIL" -eq 0 ]]; then
  ok "Program filter checks passed."
else
  bad "Program filter checks failed."
  exit 1
fi
