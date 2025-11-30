#!/usr/bin/env bash
# Shared filesystem/navigation helpers for gpt-creator.

gc_clone_python_tool() {
  local script_name="${1:?python script name required}"
  local root_param="${2:-}"
  local root="${root_param:-${PROJECT_ROOT:-$PWD}}"
  local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}/scripts}"
  if [[ -z "$root" ]]; then
    die "Unable to determine project root while preparing ${script_name}"
  fi
  local source_path="${scripts_root}/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    die "Python helper missing at ${source_path}"
  fi
  local target_dir="${root}/.gpt-creator/shims/python"
  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || die "Failed to create ${target_dir}"
  fi
  local target_path="${target_dir}/${script_name}"
  if [[ ! -f "$target_path" ]] || ! cmp -s "$source_path" "$target_path"; then
    cp "$source_path" "$target_path" || die "Failed to copy ${script_name} helper"
  fi
  if [[ "$script_name" == *.py ]]; then
    local base_name="${script_name%.py}"
    local sidecar="${base_name}_lib.py"
    local sidecar_source="${scripts_root}/python/${sidecar}"
    local sidecar_target="${target_dir}/${sidecar}"
    if [[ -f "$sidecar_source" ]]; then
      if [[ ! -f "$sidecar_target" ]] || ! cmp -s "$sidecar_source" "$sidecar_target"; then
        cp "$sidecar_source" "$sidecar_target" || die "Failed to copy ${sidecar} helper"
      fi
    fi
  fi
  echo "$target_path"
}

gc_repo_root_from_git() {
  git rev-parse --show-toplevel 2>/dev/null || true
}

gc_search_up_for_markers() {
  local dir="${PWD}"
  while [[ -n "$dir" && "$dir" != "/" ]]; do
    for marker in .gpt-creator .git package.json pnpm-workspace.yaml pyproject.toml requirements.txt setup.cfg poetry.lock Cargo.toml; do
      if [[ -e "${dir}/${marker}" ]]; then
        printf '%s\n' "$dir"
        return 0
      fi
    done
    dir="${dir%/*}"
  done
  printf '%s\n' "$PWD"
}

gc_detect_project_root() {
  local configured="${GC_PROJECT_ROOT:-}"
  if [[ -n "$configured" && -d "$configured" ]]; then
    (cd "$configured" >/dev/null 2>&1 && pwd -P) && return 0
  fi
  local git_root
  git_root="$(gc_repo_root_from_git)"
  if [[ -n "$git_root" && -d "$git_root" ]]; then
    (cd "$git_root" >/dev/null 2>&1 && pwd -P) && return 0
  fi
  gc_search_up_for_markers
}

gc_abs_from_project() {
  local rel_path="${1:-}"
  local base="${PROJECT_ROOT:-$(gc_detect_project_root)}"
  if [[ -z "$rel_path" ]]; then
    printf '%s\n' "$base"
    return 0
  fi
  if [[ "$rel_path" == /* ]]; then
    (cd "$(dirname "$rel_path")" >/dev/null 2>&1 && printf '%s/%s\n' "$(pwd -P)" "$(basename "$rel_path")") && return 0
    printf '%s\n' "$rel_path"
    return 0
  fi
  (
    cd "$base" >/dev/null 2>&1 || exit 0
    cd "$(dirname "$rel_path")" >/dev/null 2>&1 || exit 0
    printf '%s/%s\n' "$(pwd -P)" "$(basename "$rel_path")"
  )
}

gc_from_root() {
  local rel="${1:-}"
  local base="${PROJECT_ROOT:-$(gc_detect_project_root)}"
  if [[ -z "$rel" ]]; then
    printf '%s\n' "$base"
    return 0
  fi
  if [[ "$rel" == /* ]]; then
    printf '%s\n' "$rel"
    return 0
  fi
  rel="${rel#./}"
  printf '%s/%s\n' "${base%/}" "$rel"
}

gc_rel_from_root() {
  local path="${1:-}"
  local base="${PROJECT_ROOT:-$(gc_detect_project_root)}"
  local prefix="${base%/}/"
  if [[ "$path" == "$prefix"* ]]; then
    printf '%s\n' "${path#$prefix}"
  else
    printf '%s\n' "$path"
  fi
}

gc_guess_interpreter() {
  local script="${1:?script path required}"
  local first_line
  if first_line="$(head -n 1 -- "$script" 2>/dev/null || true)"; then
    if [[ "$first_line" == '#!'* ]]; then
      local shebang="${first_line#\#!}"
      shebang="${shebang#"${shebang%%[![:space:]]*}"}"
      shebang="${shebang%"${shebang##*[![:space:]]}"}"
      set -- $shebang
      printf '%s\n' "$1"
      return 0
    fi
  fi
  case "${script##*.}" in
    py) printf '%s\n' "${PYTHON_BIN:-python3}" ;;
    js|cjs|mjs) printf '%s\n' node ;;
    sh|bash) printf '%s\n' bash ;;
    *) printf '%s\n' "${PYTHON_BIN:-python3}" ;;
  esac
}

abs_path() {
  local target="${1:-}"
  local helper_path
  helper_path="$(gc_clone_python_tool "abs_path.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  local resolved=""
  if resolved="$(python3 "$helper_path" "$target" 2>/dev/null)"; then
    printf '%s\n' "${resolved:-$target}"
    return 0
  fi
  perl -MCwd=abs_path -e 'print abs_path(shift)."\n"' "$target" || echo "$target"
}
