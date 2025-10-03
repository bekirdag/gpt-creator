#!/usr/bin/env bash
# gpt-creator core library
# shellcheck shell=bash disable=SC2034,SC2155

set -Eeuo pipefail

# Load constants
GC_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=src/constants.sh
source "$GC_LIB_DIR/constants.sh"

# ------------- Logging & UX helpers -------------
gc::ts() { date +"%Y-%m-%d %H:%M:%S"; }

gc::log()    { printf "%s%s[%s] %s%s\n"   "${GC_CLR_DIM}" "[INFO] "  "$(gc::ts)" "${*}" "${GC_CLR_RESET}"; }
gc::ok()     { printf "%s%s[%s] %s%s\n"   "${GC_CLR_GREEN}" "[ OK ] " "$(gc::ts)" "${*}" "${GC_CLR_RESET}"; }
gc::warn()   { printf "%s%s[%s] %s%s\n"   "${GC_CLR_YELLOW}" "[WARN] " "$(gc::ts)" "${*}" "${GC_CLR_RESET}"; }
gc::err()    { printf "%s%s[%s] %s%s\n"   "${GC_CLR_RED}" "[FAIL] " "$(gc::ts)" "${*}" "${GC_CLR_RESET}" 1>&2; }
gc::die()    { gc::err "$@"; exit 1; }

gc::hr()     { printf "%s\n" "────────────────────────────────────────────────────────"; }

gc::banner() {
  if [[ -f "$GC_BANNER_FILE" ]]; then
    printf "%s" "${GC_CLR_CYAN}"
    cat "$GC_BANNER_FILE"
    printf "%s\n" "${GC_CLR_RESET}"
  else
    printf "%s%s v%s%s\n" "${GC_CLR_BOLD}" "$GC_NAME" "$GC_VERSION" "${GC_CLR_RESET}"
  fi
}

# ------------- Env checks -------------
gc::has_cmd() { command -v "$1" >/dev/null 2>&1; }

gc::require_cmds_soft() {
  local missing=0
  for c in "${GC_PREREQ_CMDS[@]}"; do
    if ! gc::has_cmd "$c"; then
      gc::warn "Prerequisite missing: ${c}"
      missing=1
    fi
  done
  if [[ $missing -eq 1 ]]; then
    gc::warn "Some prerequisites are missing. The installer will set these up."
  fi
}

# ------------- Path & workspace helpers -------------
gc::abs_path() (
  # prints absolute path of $1 (no symlink resolution requirement)
  cd "$1" 2>/dev/null && pwd || { cd "$(dirname "$1")" && printf "%s/%s\n" "$(pwd)" "$(basename "$1")"; }
)

gc::ensure_workspace() {
  local project_root="$1"
  local work="$project_root/$GC_WORK_DIR_NAME"
  mkdir -p "$work"
  for sub in "${GC_STAGING_SUBDIRS[@]}"; do
    mkdir -p "$work/staging/$sub"
  done
  printf "%s" "$work"
}

# ------------- Discovery (fuzzy) -------------
gc::_find_first_by_patterns() {
  local root="$1"; shift
  local -a patterns=("$@")
  local found=""
  shopt -s nocaseglob nullglob
  for pat in "${patterns[@]}"; do
    while IFS= read -r -d '' f; do
      found="$f"; echo "$found"; return 0
    done < <(find "$root" -type f -iname "$pat" -print0 2>/dev/null)
  done
  return 1
}

gc::_find_all_by_patterns() {
  local root="$1"; shift
  local -a patterns=("$@")
  shopt -s nocaseglob nullglob
  while IFS= read -r -d '' f; do
    echo "$f"
  done < <(find "$root" -type f \( $(printf -- '-iname %q -o ' "${patterns[@]}" | sed 's/ -o $//') \) -print0 2>/dev/null)
}

gc::discover() {
  # Args: project_root ; Outputs variables via declare -gA/-ga + manifest echo
  local project_root="$1"
  declare -gA GC_FOUND_DOCS=() GC_FOUND_MISC=()
  declare -ga GC_FOUND_MMD=() GC_FOUND_SAMPLES=()

  # Primary documents
  GC_FOUND_DOCS[pdr]="$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(pdr|product.*design.*requirement).*" -m1 || true; })"
  GC_FOUND_DOCS[sds]="$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(sds|system.*design.*spec).*" -m1 || true; })"
  GC_FOUND_DOCS[rfp]="$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(rfp|request.*for.*proposal).*" -m1 || true; })"
  GC_FOUND_DOCS[jira]="$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(jira).*" -m1 || true; })"
  GC_FOUND_DOCS[ui_pages]="$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(ui.*pages|website.*ui.*pages).*" -m1 || true; })"

  # OpenAPI & SQL
  GC_FOUND_DOCS[openapi]="$({ gc::_find_first_by_patterns "$project_root" "${GC_OPENAPI_PATTERNS[@]}" | head -n1 || true; })"
  GC_FOUND_DOCS[sql]="$({ gc::_find_first_by_patterns "$project_root" "${GC_SQL_PATTERNS[@]}" | head -n1 || true; })"

  # Mermaid diagrams
  mapfile -t GC_FOUND_MMD < <(gc::_find_all_by_patterns "$project_root" "${GC_MERMAID_PATTERNS[@]}")

  # Page samples: prefer known directories; fall back to loose files
  for d in "${GC_SAMPLE_DIRS[@]}"; do
    if [[ -d "$project_root/$d" ]]; then
      while IFS= read -r -d '' f; do GC_FOUND_SAMPLES+=("$f"); done < <(find "$project_root/$d" -type f \( -iname "*.html" -o -iname "*.css" \) -print0)
    fi
  done
  # loose
  while IFS= read -r -d '' f; do GC_FOUND_SAMPLES+=("$f"); done < <(find "$project_root" -maxdepth 2 -type f \( -iname "*.html" -o -iname "*.css" \) -print0)

  # Manifest (stdout)
  echo "---"
  echo "found:"
  for k in pdr sds rfp jira ui_pages openapi sql; do
    printf "  %s: %s\n" "$k" "${GC_FOUND_DOCS[$k]:-}"
  done
  echo "  mermaid_diagrams:"
  for m in "${GC_FOUND_MMD[@]:-}"; do printf "    - %s\n" "$m"; done
  echo "  samples:"
  for s in "${GC_FOUND_SAMPLES[@]:-}"; do printf "    - %s\n" "$s"; done
}

# ------------- Normalization (staging copy with canonical names) -------------
gc::normalize_to_staging() {
  local project_root="$1"
  local work_dir; work_dir="$(gc::ensure_workspace "$project_root")"
  local stage="$work_dir/staging"

  # docs
  [[ -n "${GC_FOUND_DOCS[pdr]:-}"      ]] && install -m 0644 "${GC_FOUND_DOCS[pdr]}"      "$stage/docs/pdr.md"
  [[ -n "${GC_FOUND_DOCS[sds]:-}"      ]] && install -m 0644 "${GC_FOUND_DOCS[sds]}"      "$stage/docs/sds.md"
  [[ -n "${GC_FOUND_DOCS[rfp]:-}"      ]] && install -m 0644 "${GC_FOUND_DOCS[rfp]}"      "$stage/docs/rfp.md"
  [[ -n "${GC_FOUND_DOCS[jira]:-}"     ]] && install -m 0644 "${GC_FOUND_DOCS[jira]}"     "$stage/docs/jira.md"
  [[ -n "${GC_FOUND_DOCS[ui_pages]:-}" ]] && install -m 0644 "${GC_FOUND_DOCS[ui_pages]}" "$stage/docs/ui-pages.md"

  # openapi
  if [[ -n "${GC_FOUND_DOCS[openapi]:-}" ]]; then
    ext="${GC_FOUND_DOCS[openapi]##*.}"
    case "$ext" in
      yml|yaml) install -m 0644 "${GC_FOUND_DOCS[openapi]}" "$stage/openapi/openapi.yaml" ;;
      json)     install -m 0644 "${GC_FOUND_DOCS[openapi]}" "$stage/openapi/openapi.json" ;;
      *)        install -m 0644 "${GC_FOUND_DOCS[openapi]}" "$stage/openapi/openapi.src"  ;;
    esac
  fi

  # sql
  [[ -n "${GC_FOUND_DOCS[sql]:-}" ]] && install -m 0644 "${GC_FOUND_DOCS[sql]}" "$stage/sql/dump.sql"

  # diagrams
  for f in "${GC_FOUND_MMD[@]:-}"; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"
    install -m 0644 "$f" "$stage/diagrams/$base"
  done

  # samples (preserve relative subdirs if under known sample dirs)
  for f in "${GC_FOUND_SAMPLES[@]:-}"; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"
    case "$base" in
      *backoffice*|*admin*) destdir="$stage/samples/backoffice_pages" ;;
      *website*|*site*|*public*) destdir="$stage/samples/website_pages" ;;
      *) # try to infer from page codes
         if echo "$base" | grep -Eiq "(ABO1|AUTH1|PRG1|EVT1|CTN1)"; then destdir="$stage/samples/website_pages"; else destdir="$stage/samples/misc"; fi
      ;;
    esac
    mkdir -p "$destdir"
    install -m 0644 "$f" "$destdir/$base"
  done

  # write discovery manifest
  gc::discover "$project_root" > "$stage/discovery.yaml"

  echo "$work_dir"
}

# ------------- Codex glue (placeholder — user may adjust to local client) -------------
gc::codex_call() {
  # Usage: gc::codex_call "prompt string" "outfile"
  local prompt="$1"; local outfile="$2"
  if gc::has_cmd "$GC_CODEX_BIN"; then
    # This is an example; adapt to your local Codex CLI
    # Expecting: codex --model gpt-5-high --files <dir> --prompt "<prompt>" --out <file>
    "$GC_CODEX_BIN" --model "$GC_CODEX_MODEL" --files "$GC_ROOT" --prompt "$prompt" > "$outfile" || {
      gc::warn "Codex invocation failed, wrote nothing to $outfile"
      return 1
    }
  else
    gc::warn "Codex client ($GC_CODEX_BIN) not found; skipping generation step."
    return 1
  fi
}

# ------------- Loader for CLI subcommands -------------
gc::load_cli() {
  local d="$GC_ROOT/src/cli"
  shopt -s nullglob
  for f in "$d"/*.sh; do
    # shellcheck source=src/cli/create-project.sh
    source "$f"
  done
  shopt -u nullglob
}

# end of core lib
