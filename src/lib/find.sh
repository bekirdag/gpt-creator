#!/usr/bin/env bash
# shellcheck shell=bash
# gpt-creator lib/find.sh — fuzzy project discovery helpers
# Safe to source multiple times.
if [[ -n "${GC_LIB_FIND_SH:-}" ]]; then return 0; fi
GC_LIB_FIND_SH=1

: "${GC_TRACE:=0}"

_find_trace() { [[ "${GC_TRACE}" == "1" ]] && printf '[find] %s\n' "$*" >&2 || true; }

# Internal ignore set for find/fd
_find_prunes=(
  ".git"
  "node_modules"
  "dist"
  "build"
  ".next"
  ".nuxt"
  ".cache"
  ".turbo"
  "coverage"
  ".DS_Store"
)

_find_cmd() {
  # Choose fd if available (faster), else fallback to find
  if command -v fd >/dev/null 2>&1; then
    printf 'fd'
  else
    printf 'find'
  fi
}

_find_with_ignores() {
  # Usage: _find_with_ignores <root> [fd/find args...]
  local root="${1:-.}"; shift || true
  local cmd; cmd="$(_find_cmd)"
  if [[ "${cmd}" == "fd" ]]; then
    # fd respects .gitignore by default; add prunes as --exclude
    local args=()
    for p in "${_find_prunes[@]}"; do args+=(--exclude "$p"); done
    fd --hidden --follow "${args[@]}" --search-path "${root}" "$@"
  else
    # POSIX find with explicit prunes
    local prune_expr=()
    for p in "${_find_prunes[@]}"; do prune_expr+=( -name "$p" -prune -o ); done
    # shellcheck disable=SC2068
    eval set -- "$@"  # pass-through patterns/flags
    # Build: find root ( -name prune -prune -o ) \( rest \) -print
    find "${root}" \( ${prune_expr[@]:-} -false \) -o \( "$@" -print \)
  fi
}

# ---- High-level discovery for gpt-creator -----------------------------------
find_guess_root() {
  # Walk up from CWD until repo markers or limit reached
  local d="${1:-$PWD}"
  local limit=10
  while (( limit-- > 0 )); do
    if [[ -d "${d}/.git" || -f "${d}/package.json" || -f "${d}/pnpm-workspace.yaml" ]]; then
      printf '%s\n' "${d}"; return 0
    fi
    local parent; parent="$(cd "${d}/.." && pwd -P)"
    [[ "${parent}" == "${d}" ]] && break
    d="${parent}"
  done
  printf '%s\n' "${1:-$PWD}"
}

find_docs() {
  # Usage: find_docs <root>
  # Prints key=value pairs (tab-separated): KIND<TAB>PATH
  local root="${1:-.}"
  _find_trace "Scanning docs in ${root}"

  # Patterns (case-insensitive)
  local p_pdr='(?i)(^|/)(pdr|product[ _-]*design[ _-]*requirements)[^/]*\.(md|pdf|docx?)$'
  local p_sds='(?i)(^|/)(sds|system[ _-]*design[ _-]*spec)[^/]*\.(md|pdf|docx?)$'
  local p_rfp='(?i)(^|/)(rfp|request[ _-]*for[ _-]*proposal)[^/]*\.(md|pdf|docx?)$'
  local p_openapi='(?i)(^|/)(openapi|swagger)\.(ya?ml|json)$'
  local p_sql='(?i)(^|/).*\.(sql|dump)$'
  local p_mermaid='(?i)(^|/).*\.(mmd)$'
  local p_jira='(?i)(^|/).*((jira|tasks?).*)\.(md|csv|xlsx?)$'
  local p_pages_dir='(?i)(^|/)page[_-]?samples?/'
  local p_backoffice_dir='(?i)(^|/)(backoffice[_-]?pages?|admin[_-]?pages?)/'
  local p_website_dir='(?i)(^|/)(website[_-]?pages?)/'
  local p_html='(?i)(^|/).*\.(html?)$'
  local p_css='(?i)(^|/).*\.(css|scss)$'

  # Use fd if available to leverage PCRE; fallback to find -regex (limited)
  if [[ "$(_find_cmd)" == "fd" ]]; then
    fd --hidden --follow --search-path "${root}" --regex "${p_pdr}"     -0 | xargs -0 -I{} printf "PDR\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_sds}"     -0 | xargs -0 -I{} printf "SDS\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_rfp}"     -0 | xargs -0 -I{} printf "RFP\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_openapi}" -0 | xargs -0 -I{} printf "OPENAPI\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_sql}"     -0 | xargs -0 -I{} printf "SQL\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_mermaid}" -0 | xargs -0 -I{} printf "MERMAID\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_jira}"    -0 | xargs -0 -I{} printf "JIRA\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_pages_dir}"   -0 | xargs -0 -I{} printf "PAGE_SAMPLES\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_backoffice_dir}" -0 | xargs -0 -I{} printf "BACKOFFICE_PAGES\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_website_dir}" -0 | xargs -0 -I{} printf "WEBSITE_PAGES\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_html}"    -0 | xargs -0 -I{} printf "HTML\t%s\n" "{}"
    fd --hidden --follow --search-path "${root}" --regex "${p_css}"     -0 | xargs -0 -I{} printf "CSS\t%s\n" "{}"
  else
    # Minimal fallback using name globs (case-insensitive for BSD find via -iname)
    _find_with_ignores "${root}" -type f \( \
      -iname "*pdr*.md" -o -iname "*pdr*.pdf" -o -iname "*product*design*requirements*.*" \) -print | \
      while IFS= read -r p; do printf "PDR\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f \( \
      -iname "*sds*.md" -o -iname "*system*design*spec*.*" \) -print | \
      while IFS= read -r p; do printf "SDS\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f \( \
      -iname "*rfp*.md" -o -iname "*request*for*proposal*.*" \) -print | \
      while IFS= read -r p; do printf "RFP\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f \( -iname "openapi.*" -o -iname "swagger.*" \) -print | \
      while IFS= read -r p; do printf "OPENAPI\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f \( -iname "*.sql" -o -iname "*dump*" \) -print | \
      while IFS= read -r p; do printf "SQL\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f -iname "*.mmd" -print | \
      while IFS= read -r p; do printf "MERMAID\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f \( -iname "*jira*.md" -o -iname "*tasks*.md" \) -print | \
      while IFS= read -r p; do printf "JIRA\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type d -iname "page*sample*" -print | \
      while IFS= read -r p; do printf "PAGE_SAMPLES\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type d \( -iname "backoffice*pages*" -o -iname "admin*pages*" \) -print | \
      while IFS= read -r p; do printf "BACKOFFICE_PAGES\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type d -iname "website*pages*" -print | \
      while IFS= read -r p; do printf "WEBSITE_PAGES\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f -iname "*.html" -print | \
      while IFS= read -r p; do printf "HTML\t%s\n" "$p"; done
    _find_with_ignores "${root}" -type f \( -iname "*.css" -o -iname "*.scss" \) -print | \
      while IFS= read -r p; do printf "CSS\t%s\n" "$p"; done
  fi
}

find_openapi()    { find_docs "${1:-.}" | awk -F'\t' '$1=="OPENAPI"{print $2}'; }
find_sql_dumps()  { find_docs "${1:-.}" | awk -F'\t' '$1=="SQL"{print $2}'; }
find_mermaid()    { find_docs "${1:-.}" | awk -F'\t' '$1=="MERMAID"{print $2}'; }
find_jira()       { find_docs "${1:-.}" | awk -F'\t' '$1=="JIRA"{print $2}'; }
find_pdr()        { find_docs "${1:-.}" | awk -F'\t' '$1=="PDR"{print $2}'; }
find_sds()        { find_docs "${1:-.}" | awk -F'\t' '$1=="SDS"{print $2}'; }
find_rfp()        { find_docs "${1:-.}" | awk -F'\t' '$1=="RFP"{print $2}'; }
find_page_samples(){ find_docs "${1:-.}" | awk -F'\t' '$1=="PAGE_SAMPLES"{print $2}'; }
find_backoffice_pages(){ find_docs "${1:-.}" | awk -F'\t' '$1=="BACKOFFICE_PAGES"{print $2}'; }
find_website_pages(){ find_docs "${1:-.}" | awk -F'\t' '$1=="WEBSITE_PAGES"{print $2}'; }

return 0
