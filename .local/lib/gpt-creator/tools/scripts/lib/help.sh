#!/usr/bin/env bash
# Help metadata loader.

if [[ -n "${GC_LIB_HELP_SH:-}" ]]; then
  return 0
fi
GC_LIB_HELP_SH=1

gc_help_template_for_cmd() {
  local cmd="${1:-}"
  [[ -n "$cmd" ]] || return 1
  local index_file="${CLI_ROOT:-$PWD}/assets/templates/help/templates_index.json"
  [[ -f "$index_file" ]] || return 1
  local tmpl=""
  local helper_path=""
  if declare -F gc_clone_python_tool >/dev/null 2>&1; then
    helper_path="$(gc_clone_python_tool "help_template_lookup.py" "${PROJECT_ROOT:-$PWD}")" || helper_path=""
  fi
  if [[ -z "$helper_path" ]]; then
    local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT:-$PWD}/tools/scripts}"
    if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
      scripts_root="${CLI_ROOT}/scripts"
    fi
    if [[ -f "${scripts_root}/python/help_template_lookup.py" ]]; then
      helper_path="${scripts_root}/python/help_template_lookup.py"
    fi
  fi
  [[ -n "$helper_path" ]] || return 1
  tmpl="$(python3 "$helper_path" "$cmd" "$index_file")" || tmpl=""
  if [[ -n "$tmpl" && -f "$tmpl" ]]; then
    printf '%s\n' "$tmpl"
    return 0
  fi
  return 1
}
