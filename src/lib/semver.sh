#!/usr/bin/env bash
# shellcheck shell=bash
# gpt-creator lib/semver.sh — Semantic Version helpers (SemVer 2.0.0)
# Safe to source multiple times.
if [[ -n "${GC_LIB_SEMVER_SH:-}" ]]; then return 0; fi
GC_LIB_SEMVER_SH=1

# Parse version into components
# Outputs: major minor patch prerelease build
_semver_parse() {
  # Usage: _semver_parse <version>
  local v="$1"
  # Validate rough shape
  if [[ ! "${v}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-([0-9A-Za-z.-]+))?(\+([0-9A-Za-z.-]+))?$ ]]; then
    return 1
  fi
  local major="${BASH_REMATCH[1]}"
  local minor="${BASH_REMATCH[2]}"
  local patch="${BASH_REMATCH[3]}"
  local prerelease="${BASH_REMATCH[5]}"
  local build="${BASH_REMATCH[7]}"
  printf '%s\t%s\t%s\t%s\t%s\n' "${major}" "${minor}" "${patch}" "${prerelease}" "${build}"
}

semver_is_valid() {
  _semver_parse "$1" >/dev/null 2>&1
}

# Compare two identifiers (numeric vs alnum) for pre-release precedence
_semver_cmp_ident() {
  local a="$1" b="$2"
  # Empty means greater (release > prerelease)
  if [[ -z "${a}" && -z "${b}" ]]; then echo 0; return; fi
  if [[ -z "${a}" ]]; then echo 1; return; fi
  if [[ -z "${b}" ]]; then echo -1; return; fi

  # Numeric?
  if [[ "${a}" =~ ^[0-9]+$ && "${b}" =~ ^[0-9]+$ ]]; then
    ((10#${a} < 10#${b})) && { echo -1; return; }
    ((10#${a} > 10#${b})) && { echo 1; return; }
    echo 0; return
  fi
  # Alphanumeric lexical
  if [[ "${a}" < "${b}" ]]; then echo -1; return; fi
  if [[ "${a}" > "${b}" ]]; then echo 1; return; fi
  echo 0
}

# Compare two pre-release strings per SemVer rules
_semver_cmp_prerelease() {
  local pa="$1" pb="$2"
  # Exact equality
  [[ "${pa}" == "${pb}" ]] && { echo 0; return; }
  # Empty prerelease means higher precedence
  if [[ -z "${pa}" && -n "${pb}" ]]; then echo 1; return; fi
  if [[ -n "${pa}" && -z "${pb}" ]]; then echo -1; return; fi

  IFS='.' read -r -a A <<< "${pa}"
  IFS='.' read -r -a B <<< "${pb}"
  local i=0
  local max="${#A[@]}"; (( ${#B[@]} > max )) && max="${#B[@]}"
  while (( i < max )); do
    local ai="${A[i]:-}"
    local bi="${B[i]:-}"
    if [[ -z "${ai}" ]]; then echo -1; return; fi
    if [[ -z "${bi}" ]]; then echo 1; return; fi
    local c; c="$(_semver_cmp_ident "${ai}" "${bi}")"
    [[ "${c}" != "0" ]] && { echo "${c}"; return; }
    ((i++))
  done
  echo 0
}

# Main comparator: prints -1 / 0 / 1
semver_compare() {
  local va="$1" vb="$2"
  local a; a="$(_semver_parse "${va}")" || { echo "NaN" >&2; return 2; }
  local b; b="$(_semver_parse "${vb}")" || { echo "NaN" >&2; return 2; }
  local A=() B=()
  IFS=$'\t' read -r A0 A1 A2 A3 A4 <<< "${a}"
  IFS=$'\t' read -r B0 B1 B2 B3 B4 <<< "${b}"

  # Numeric compare on major/minor/patch
  for i in 0 1 2; do
    local x y
    case "$i" in
      0) x="${A0}"; y="${B0}";;
      1) x="${A1}"; y="${B1}";;
      2) x="${A2}"; y="${B2}";;
    esac
    if (( 10#${x} < 10#${y} )); then echo -1; return; fi
    if (( 10#${x} > 10#${y} )); then echo 1; return; fi
  done

  # Pre-release precedence
  local pc; pc="$(_semver_cmp_prerelease "${A3}" "${B3}")"
  echo "${pc}"
}

semver_eq() { [[ "$(semver_compare "$1" "$2")" == "0" ]]; }
semver_ne() { [[ "$(semver_compare "$1" "$2")" != "0" ]]; }
semver_gt() { [[ "$(semver_compare "$1" "$2")" == "1" ]]; }
semver_ge() { local c; c="$(semver_compare "$1" "$2")"; [[ "${c}" == "1" || "${c}" == "0" ]]; }
semver_lt() { [[ "$(semver_compare "$1" "$2")" == "-1" ]]; }
semver_le() { local c; c="$(semver_compare "$1" "$2")"; [[ "${c}" == "-1" || "${c}" == "0" ]]; }

# Bump helpers
semver_bump() {
  # Usage: semver_bump (major|minor|patch) <version>
  local kind="$1" v="$2"
  local major minor patch pre build
  IFS=$'\t' read -r major minor patch pre build < <(_semver_parse "${v}") || {
    echo "semver_bump: invalid version: ${v}" >&2; return 2; }

  case "${kind}" in
    major) ((major++)); minor=0; patch=0; pre= ;;
    minor) ((minor++)); patch=0; pre= ;;
    patch) ((patch++)); pre= ;;
    *) echo "semver_bump: kind must be major|minor|patch" >&2; return 2;;
  esac

  printf '%s.%s.%s\n' "${major}" "${minor}" "${patch}"
}

return 0
