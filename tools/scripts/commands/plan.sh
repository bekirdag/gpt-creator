#!/usr/bin/env bash
# shellcheck shell=bash

cmd_plan() {
  local root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      *) break;;
    esac
  done
  ensure_ctx "$root"

  local openapi=""
  for cand in "$INPUT_DIR/openapi.yaml" "$INPUT_DIR/openapi.yml" "$INPUT_DIR/openapi.json" "$INPUT_DIR/openapi.src"; do
    [[ -f "$cand" ]] && { openapi="$cand"; break; }
  done
  local sql_dir="$INPUT_DIR/sql"
  local python_bin="${PYTHON_BIN:-python3}"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    die "Python runtime '${python_bin}' not available; cannot build plan artifacts."
  fi
  local plan_helper
  plan_helper="$(gc_clone_python_tool "generate_plan_artifacts.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  "$python_bin" "$plan_helper" "$openapi" "$sql_dir" "$PLAN_DIR"

  ok "Plan artifacts created under ${PLAN_DIR}"
}
