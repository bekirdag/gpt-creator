#!/usr/bin/env bash
# Surface detection helpers shared across commands.

if [[ -n "${GC_LIB_SURFACES_SH:-}" ]]; then
  return 0
fi
GC_LIB_SURFACES_SH=1

gc_detect_surfaces() {
  local project_root="${1:-}"
  local rfp_path="${2:-}"
  local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
  if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
    scripts_root="${CLI_ROOT}/scripts"
  fi
  local detector="${scripts_root}/python/detect_surfaces.py"
  [[ -n "$project_root" ]] || return 0
  if [[ ! -f "$detector" ]]; then
    return 0
  fi
  python3 "$detector" "$project_root" ${rfp_path:+--rfp "$rfp_path"} 2>/dev/null || true
}

gc_resolve_surfaces() {
  local project_root="${1:-}"
  local surfaces_override="${2:-}"
  local rfp_path="${3:-}"
  local surfaces=""
  if [[ -n "$surfaces_override" ]]; then
    surfaces="$(printf '%s' "$surfaces_override" | tr ',;' ' ')"
  else
    surfaces="$(gc_detect_surfaces "$project_root" "$rfp_path")"
  fi
  # If nothing is detected, return empty (caller may choose a fallback).
  printf '%s\n' "$surfaces"
}

gc_docker_services_from_surfaces() {
  local -a surfaces=("$@")
  local -a services=()
  local has_web=0 has_admin=0
  local surface
  for surface in "${surfaces[@]}"; do
    case "$surface" in
      web) has_web=1;;
      admin) has_admin=1;;
    esac
    case "$surface" in
      api|db|web|admin|mobile) services+=("$surface");;
    esac
  done
  if (( has_web && has_admin )); then
    services+=("proxy")
  fi
  # Deduplicate while preserving order
  local -a deduped=()
  local seen=""
  for surface in "${services[@]}"; do
    [[ -z "$surface" ]] && continue
    case " $seen " in
      *" $surface "*) continue;;
    esac
    deduped+=("$surface")
    seen+=" $surface"
  done
  printf '%s\n' "${deduped[*]}"
}
