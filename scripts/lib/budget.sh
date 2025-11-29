#!/usr/bin/env bash
# Budget stage helpers.

gc_budget_stage_id() {
  local stage="${1:-}"
  stage="${stage,,}"
  stage="${stage//[^a-z0-9]/_}"
  printf '%s' "$stage"
}

gc_budget_stage_limit_var() {
  local id
  id="$(gc_budget_stage_id "$1")"
  id="${id^^}"
  printf 'GC_BUDGET_STAGE_LIMIT_%s' "$id"
}

gc_budget_stage_total_var() {
  local id
  id="$(gc_budget_stage_id "$1")"
  id="${id^^}"
  printf 'GC_BUDGET_STAGE_TOTAL_%s' "$id"
}

gc_budget_stage_tripped_var() {
  local id
  id="$(gc_budget_stage_id "$1")"
  id="${id^^}"
  printf 'GC_BUDGET_STAGE_TRIPPED_%s' "$id"
}

gc_budget_stage_skip_var() {
  local id
  id="$(gc_budget_stage_id "$1")"
  id="${id^^}"
  printf 'GC_BUDGET_STAGE_SKIP_%s' "$id"
}

gc_budget_stage_reason_var() {
  local id
  id="$(gc_budget_stage_id "$1")"
  id="${id^^}"
  printf 'GC_BUDGET_STAGE_SKIP_REASON_%s' "$id"
}

gc_budget_get_stage_limit() {
  local var
  var="$(gc_budget_stage_limit_var "$1")"
  printf '%s' "${!var:-0}"
}

gc_budget_set_stage_limit() {
  local var
  var="$(gc_budget_stage_limit_var "$1")"
  local value="${2:-0}"
  printf -v "$var" '%s' "$value"
}

gc_budget_stage_tripped() {
  local var
  var="$(gc_budget_stage_tripped_var "$1")"
  [[ "${!var:-0}" == "1" ]]
}

gc_budget_stage_should_skip() {
  local var
  var="$(gc_budget_stage_skip_var "$1")"
  [[ "${!var:-0}" == "1" ]]
}

gc_budget_set_stage_skip() {
  local stage="$1"
  local flag="${2:-0}"
  local reason="${3:-}"
  local skip_var
  skip_var="$(gc_budget_stage_skip_var "$stage")"
  printf -v "$skip_var" '%s' "$flag"
  local reason_var
  reason_var="$(gc_budget_stage_reason_var "$stage")"
  printf -v "$reason_var" '%s' "$reason"
}

gc_budget_stage_skip_reason() {
  local var
  var="$(gc_budget_stage_reason_var "$1")"
  printf '%s' "${!var:-}"
}

gc_budget_reset_stage_tracking() {
  local stages=("retrieve" "plan" "patch")
  local stage
  for stage in "${stages[@]}"; do
    local total_var
    total_var="$(gc_budget_stage_total_var "$stage")"
    printf -v "$total_var" '%s' "0"
    local trip_var
    trip_var="$(gc_budget_stage_tripped_var "$stage")"
    printf -v "$trip_var" '%s' "0"
    local skip_var
    skip_var="$(gc_budget_stage_skip_var "$stage")"
    printf -v "$skip_var" '%s' "0"
    local reason_var
    reason_var="$(gc_budget_stage_reason_var "$stage")"
    printf -v "$reason_var" '%s' ""
  done
}
