#!/usr/bin/env bash
# Portable helper to clone a python helper into the project workspace shims.

__gc_clone_log() {
  if declare -f log >/dev/null 2>&1; then
    log "$@"
  elif declare -f warn >/dev/null 2>&1; then
    warn "$@"
  elif declare -f err >/dev/null 2>&1; then
    err "$@"
  else
    printf '[python-clone] %s\n' "$*" >&2
  fi
}

gc_clone_python_tool() {
  local script_name="${1:?python script name required}"
  local project_root="${2:-${PROJECT_ROOT:-$PWD}}"
  local cli_root="${3:-${GC_ROOT:-${CLI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}}"

  if [[ -z "$project_root" ]]; then
    __gc_clone_log "Unable to determine project root while preparing ${script_name}"
    return 1
  fi

  local scripts_root="${GC_SCRIPTS_ROOT:-${cli_root}/tools/scripts}"
  if [[ ! -d "$scripts_root" ]]; then
    scripts_root="${cli_root}/scripts"
  fi

  local source_path="${scripts_root}/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    __gc_clone_log "Python helper missing at ${source_path}"
    return 1
  fi

  local work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  local target_dir="${project_root%/}/${work_dir_name}/shims/python"
  local target_path="${target_dir}/${script_name}"

  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || { __gc_clone_log "Failed to create ${target_dir}"; return 1; }
  fi

  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || { __gc_clone_log "Failed to copy ${script_name} helper"; return 1; }
  fi

  if [[ "$script_name" == *.py ]]; then
    local base_name="${script_name%.py}"
    local sidecar="${base_name}_lib.py"
    local sidecar_source="${scripts_root}/python/${sidecar}"
    local sidecar_target="${target_dir}/${sidecar}"
    if [[ -f "$sidecar_source" ]]; then
      if [[ ! -f "$sidecar_target" || "$sidecar_source" -nt "$sidecar_target" ]]; then
        cp "$sidecar_source" "$sidecar_target" || { __gc_clone_log "Failed to copy ${sidecar} helper"; return 1; }
      fi
    fi
  fi

  printf '%s\n' "$target_path"
}

# Backwards-compatible alias used by some scripts.
clone_python_tool() {
  gc_clone_python_tool "$@"
}
