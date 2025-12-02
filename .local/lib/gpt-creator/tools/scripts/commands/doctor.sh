#!/usr/bin/env bash
# shellcheck shell=bash

cmd_doctor() {
  local fail=0
  PROJECT_ROOT="${PROJECT_ROOT:-$(gc_detect_project_root)}"
  echo "gpt-creator doctor"
  echo "project root: ${PROJECT_ROOT}"
  for c in git curl bash; do
    if ! command -v "$c" >/dev/null 2>&1; then
      echo "missing: $c"
      fail=1
    else
      echo "$c: $(command -v "$c")"
    fi
  done
  command -v timeout >/dev/null 2>&1 || command -v gtimeout >/dev/null 2>&1 || echo "note: timeout utility not found; per-step timeouts will fall back to best-effort."
  if command -v node >/dev/null 2>&1; then
    echo "node: $(node -v)"
  else
    echo "node: not found (ok if unused)"
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3: $(python3 -V)"
  else
    echo "python3: not found (ok if unused)"
  fi
  echo "end-of-task.d search:"
  while IFS= read -r dir; do
    if [[ -d "$dir" ]]; then
      echo "  $dir"
      find "$dir" -maxdepth 1 -type f ! -name '.*' -printf '    %f\n' 2>/dev/null || true
    else
      echo "  (absent) $dir"
    fi
  done < <(gc_end_scripts_dirs)
  mkdir -p "${PROJECT_ROOT}/.gpt-creator/reports" || { echo "reports dir not writable"; fail=1; }
  mkdir -p "${PROJECT_ROOT}/.gpt-creator/locks/finalize" || { echo "locks dir not writable"; fail=1; }
  if declare -F gc_load_required_vars >/dev/null 2>&1; then
    echo "required vars:"
    local -a req_vars=()
    if ! mapfile -t req_vars < <(gc_load_required_vars); then
      req_vars=()
    fi
    if ((${#req_vars[@]} == 0)); then
      echo "  (none declared)"
    else
      local var
      for var in "${req_vars[@]}"; do
        if [[ -z "${!var+x}" || -z "${!var//[[:space:]]/}" ]]; then
          echo "  MISSING: $var"
          fail=1
        else
          echo "  OK: $var=$(gc_redact "${!var}")"
        fi
      done
    fi
  fi
  if [[ $fail -eq 0 ]]; then
    echo "doctor: OK"
  else
    echo "doctor: issues found"
    return 1
  fi
}
