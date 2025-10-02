#!/usr/bin/env bash
# shellcheck shell=bash
# gpt-creator lib/path.sh — path utilities (portable; no GNU-only deps)
# Safe to source multiple times.
if [[ -n "${GC_LIB_PATH_SH:-}" ]]; then return 0; fi
GC_LIB_PATH_SH=1

: "${GC_TRACE:=0}"
_path_trace() { [[ "${GC_TRACE}" == "1" ]] && printf '[path] %s\n' "$*" >&2 || true; }

# Join path segments (skips empty, handles slashes)
path_join() {
  # Usage: path_join <segment...>
  local IFS=/ out= seg
  for seg in "$@"; do
    [[ -z "${seg}" ]] && continue
    # Remove duplicate slashes on both sides
    seg="${seg%%/}"; seg="${seg##/}"
    if [[ -z "${out}" ]]; then out="${seg}"; else out="${out}/${seg}"; fi
  done
  printf '%s\n' "${out:-/}"
}

# Absolute form (no symlink resolution guarantees without realpath)
path_abs() {
  # Usage: path_abs <path>
  local p="${1:-.}"
  if [[ -d "${p}" ]]; then
    (cd "${p}" 2>/dev/null && pwd -P) || return 1
  else
    local d; d="$(dirname -- "${p}")"
    local b; b="$(basename -- "${p}")"
    (cd "${d}" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "${b}") || return 1
  fi
}

# Normalize (resolve . and ..; collapse slashes)
path_normalize() {
  # Usage: path_normalize <path>
  path_abs "$1"
}

# Directory name / base name (without extension helper)
path_dirname()  { dirname -- "$1"; }
path_basename() { basename -- "$1"; }

path_strip_ext() {
  # Usage: path_strip_ext <file>
  local f="$1"
  f="$(basename -- "${f}")"
  printf '%s\n' "${f%.*}"
}

# Relative path: from $2 (base) to $1 (target). Pure bash fallback.
path_rel() {
  # Usage: path_rel <target> <base>
  local target; target="$(path_abs "$1")" || return 1
  local base;   base="$(path_abs "${2:-$PWD}")" || return 1

  # If identical
  [[ "${target}" == "${base}" ]] && { printf '.\n'; return 0; }

  # Split into arrays
  IFS='/' read -r -a tarr <<< "${target}"
  IFS='/' read -r -a barr <<< "${base}"

  # Find common prefix length
  local i=0
  while [[ $i -lt ${#tarr[@]} && $i -lt ${#barr[@]} && "${tarr[$i]}" == "${barr[$i]}" ]]; do
    ((i++))
  done

  local up='' down=''
  local j
  for (( j=i; j<${#barr[@]}; j++ )); do up+="../"; done
  for (( j=i; j<${#tarr[@]}; j++ )); do
    down+="${tarr[$j]}"
    [[ $j -lt $((${#tarr[@]}-1)) ]] && down+="/"
  done
  printf '%s\n' "${up}${down}"
}

# Prefix check
path_has_prefix() {
  # Usage: path_has_prefix <path> <prefix>
  local p; p="$(path_abs "$1")" || return 1
  local pref; pref="$(path_abs "$2")" || return 1
  [[ "${p}" == "${pref}"* ]]
}

# Slugify (safe file/dir name)
path_slugify() {
  # Usage: path_slugify "Some Name — 1.2"
  local s="$*"
  # To lowercase
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
  # Replace Turkish chars and accents (basic map)
  s="${s//ç/c}"; s="${s//ğ/g}"; s="${s//ı/i}"; s="${s//ö/o}"; s="${s//ş/s}"; s="${s//ü/u}"
  # Replace non-alnum with dashes
  s="$(printf '%s' "${s}" | tr -cs 'a-z0-9._-' '-')"
  # Collapse dashes
  s="$(printf '%s' "${s}" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-item}"
}

return 0
