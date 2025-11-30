#!/usr/bin/env bash
# shellcheck shell=bash

cmd_normalize() {
  local root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      *) break;;
    esac
  done
  ensure_ctx "$root"
  gc_load_cmd scan

  local scan_json="${STAGING_DIR}/scan.json"
  if [[ ! -f "$scan_json" ]]; then
    warn "No scan.json found, running scan first."
    cmd_scan --project "$PROJECT_ROOT"
  fi

  local python_bin="${PYTHON_BIN:-python3}"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    die "Python runtime '${python_bin}' not available; cannot normalize inputs."
  fi

  local normalize_helper
  normalize_helper="$(gc_clone_python_tool "normalize_inputs.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  "$python_bin" "$normalize_helper" "$scan_json" "$INPUT_DIR" "$PLAN_DIR"

  ok "Normalized inputs → ${INPUT_DIR}"
}
