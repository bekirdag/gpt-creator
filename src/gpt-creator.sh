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
gc::_found_doc_var() {
  local key="$1"
  key="${key//-/_}"
  key="$(printf '%s' "$key" | tr '[:lower:]' '[:upper:]')"
  printf 'GC_FOUND_DOC_%s' "$key"
}

gc::_set_found_doc() {
  local key="$1"
  local value="${2:-}"
  local var
  var="$(gc::_found_doc_var "$key")"
  printf -v "$var" '%s' "$value"
}

gc::_get_found_doc() {
  local key="$1"
  local var
  var="$(gc::_found_doc_var "$key")"
  printf '%s' "${!var:-}"
}

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
  local -a expr=()
  local pat
  for pat in "${patterns[@]}"; do
    expr+=(-iname "$pat" -o)
  done
  if ((${#expr[@]} > 0)); then
    unset 'expr[-1]'
  else
    expr=(-name '*')
  fi
  while IFS= read -r -d '' f; do
    echo "$f"
  done < <(find "$root" -type f \( "${expr[@]}" \) -print0 2>/dev/null)
}

gc::discover() {
  # Args: project_root [out_file]
  local project_root="$1"
  local out_file="${2:-}"

  GC_FOUND_MMD=()
  GC_FOUND_SAMPLES=()

  gc::_set_found_doc pdr "$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(pdr|product.*design.*requirement).*" -m1 || true; })"
  gc::_set_found_doc sds "$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(sds|system.*design.*spec).*" -m1 || true; })"
  gc::_set_found_doc rfp "$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(rfp|request.*for.*proposal).*" -m1 || true; })"
  gc::_set_found_doc jira "$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(jira).*" -m1 || true; })"
  gc::_set_found_doc ui_pages "$({ gc::_find_first_by_patterns "$project_root" "${GC_DOC_PATTERNS[@]}" | grep -Ei "/(ui.*pages|website.*ui.*pages).*" -m1 || true; })"

  gc::_set_found_doc openapi "$({ gc::_find_first_by_patterns "$project_root" "${GC_OPENAPI_PATTERNS[@]}" | head -n1 || true; })"
  gc::_set_found_doc sql "$({ gc::_find_first_by_patterns "$project_root" "${GC_SQL_PATTERNS[@]}" | head -n1 || true; })"

  if command -v python3 >/dev/null 2>&1; then
    local work_dir registry_path
    work_dir="$(gc::ensure_workspace "$project_root")"
    registry_path="$work_dir/staging/plan/tasks/tasks.db"
    if [[ -f "$registry_path" ]]; then
      local key
      for key in pdr sds rfp jira ui_pages openapi sql; do
        local current
        current="$(gc::_get_found_doc "$key")"
        if [[ -n "$current" ]]; then
          continue
        fi
        local fallback
        fallback="$(python3 - "$registry_path" "$key" <<'PY'
import sqlite3
import sys
from pathlib import Path

registry = Path(sys.argv[1])
key = sys.argv[2]

doc_type_map = {
    "pdr": "pdr",
    "sds": "sds",
    "rfp": "rfp",
    "jira": "jira",
    "ui_pages": "ui",
    "openapi": "openapi",
    "sql": "sql",
}

search_terms_map = {
    "pdr": ["pdr", "product"],
    "sds": ["sds", "system", "design-spec"],
    "rfp": ["rfp", "proposal"],
    "jira": ["jira"],
    "ui_pages": ["ui-pages", "ui_pages", "ui pages", "ui"],
    "openapi": ["openapi", "swagger"],
    "sql": [".sql", "dump"],
}

def pick(row):
    if row is None:
        return ""
    value = row["resolved_path"]
    if not value:
        return ""
    try:
        return str(Path(value).resolve())
    except Exception:
        return str(Path(value))

doc_type = doc_type_map.get(key)

try:
    conn = sqlite3.connect(str(registry))
    conn.row_factory = sqlite3.Row
except Exception:
    print("")
    raise SystemExit(0)

resolved = ""
try:
    if doc_type:
        row = conn.execute(
            """
            SELECT COALESCE(staging_path, source_path) AS resolved_path
            FROM documentation
            WHERE status = 'active' AND doc_type = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (doc_type,),
        ).fetchone()
        resolved = pick(row)
    if not resolved and doc_type:
        row = conn.execute(
            """
            SELECT COALESCE(staging_path, source_path) AS resolved_path
            FROM documentation
            WHERE status = 'active' AND tags_json LIKE ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (f'%"{doc_type}"%',),
        ).fetchone()
        resolved = pick(row)
    if not resolved:
        for term in search_terms_map.get(key, []):
            term = term.lower()
            row = conn.execute(
                """
                SELECT COALESCE(staging_path, source_path) AS resolved_path
                FROM documentation
                WHERE status = 'active'
                  AND (
                    LOWER(COALESCE(rel_path, '')) LIKE ?
                    OR LOWER(COALESCE(file_name, '')) LIKE ?
                  )
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (f"%{term}%", f"%{term}%"),
            ).fetchone()
            resolved = pick(row)
            if resolved:
                break
finally:
    try:
        conn.close()
    except Exception:
        pass

print(resolved)
PY
)"
        if [[ -n "$fallback" ]]; then
          gc::_set_found_doc "$key" "$fallback"
        fi
      done
    fi
  fi

  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    GC_FOUND_MMD+=("$f")
  done < <(gc::_find_all_by_patterns "$project_root" "${GC_MERMAID_PATTERNS[@]}")

  local d
  for d in "${GC_SAMPLE_DIRS[@]}"; do
    if [[ -d "$project_root/$d" ]]; then
      while IFS= read -r -d '' f; do
        GC_FOUND_SAMPLES+=("$f")
      done < <(find "$project_root/$d" -type f \( -iname "*.html" -o -iname "*.css" \) -print0)
    fi
  done
  while IFS= read -r -d '' f; do
    GC_FOUND_SAMPLES+=("$f")
  done < <(find "$project_root" -maxdepth 2 -type f \( -iname "*.html" -o -iname "*.css" \) -print0)

  local manifest_buffer="---"$'\n'"found:"$'\n'
  local k
  for k in pdr sds rfp jira ui_pages openapi sql; do
    manifest_buffer+="  ${k}: $(gc::_get_found_doc "$k")"$'\n'
  done
  manifest_buffer+="  mermaid_diagrams:"$'\n'
  local m
  for m in ${GC_FOUND_MMD[@]+"${GC_FOUND_MMD[@]}"}; do
    manifest_buffer+="    - ${m}"$'\n'
  done
  manifest_buffer+="  samples:"$'\n'
  local s
  for s in ${GC_FOUND_SAMPLES[@]+"${GC_FOUND_SAMPLES[@]}"}; do
    manifest_buffer+="    - ${s}"$'\n'
  done

  if [[ -n "$out_file" ]]; then
    printf '%s' "$manifest_buffer" > "$out_file"
  else
    printf '%s' "$manifest_buffer"
  fi
}

# ------------- Normalization (staging copy with canonical names) -------------
gc::normalize_to_staging() {
  local project_root="$1"
  local work_dir; work_dir="$(gc::ensure_workspace "$project_root")"
  local stage="$work_dir/staging"
  local doc_registry_cli="$GC_LIB_DIR/lib/doc_registry.py"
  local doc_registry_ready=0
  if command -v python3 >/dev/null 2>&1 && [[ -f "$doc_registry_cli" ]]; then
    doc_registry_ready=1
  fi
  gc::discover "$project_root" "$stage/discovery.yaml"

  # docs
  local doc_path
  doc_path="$(gc::_get_found_doc pdr)"
  if [[ -n "$doc_path" ]]; then
    install -m 0644 "$doc_path" "$stage/docs/pdr.md"
    if (( doc_registry_ready )); then
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "pdr" \
        --source-path "$doc_path" \
        --staging-path "$stage/docs/pdr.md" \
        --rel-path "docs/pdr.md" \
        --tags '["pdr","primary"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for docs/pdr.md"
    fi
  fi
  doc_path="$(gc::_get_found_doc sds)"
  if [[ -n "$doc_path" ]]; then
    install -m 0644 "$doc_path" "$stage/docs/sds.md"
    if (( doc_registry_ready )); then
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "sds" \
        --source-path "$doc_path" \
        --staging-path "$stage/docs/sds.md" \
        --rel-path "docs/sds.md" \
        --tags '["sds","primary"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for docs/sds.md"
    fi
  fi
  doc_path="$(gc::_get_found_doc rfp)"
  if [[ -n "$doc_path" ]]; then
    install -m 0644 "$doc_path" "$stage/docs/rfp.md"
    if (( doc_registry_ready )); then
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "rfp" \
        --source-path "$doc_path" \
        --staging-path "$stage/docs/rfp.md" \
        --rel-path "docs/rfp.md" \
        --tags '["rfp"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for docs/rfp.md"
    fi
  fi
  doc_path="$(gc::_get_found_doc jira)"
  if [[ -n "$doc_path" ]]; then
    install -m 0644 "$doc_path" "$stage/docs/jira.md"
    if (( doc_registry_ready )); then
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "jira" \
        --source-path "$doc_path" \
        --staging-path "$stage/docs/jira.md" \
        --rel-path "docs/jira.md" \
        --tags '["jira"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for docs/jira.md"
    fi
  fi
  doc_path="$(gc::_get_found_doc ui_pages)"
  if [[ -n "$doc_path" ]]; then
    install -m 0644 "$doc_path" "$stage/docs/ui-pages.md"
    if (( doc_registry_ready )); then
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "ui" \
        --source-path "$doc_path" \
        --staging-path "$stage/docs/ui-pages.md" \
        --rel-path "docs/ui-pages.md" \
        --tags '["ui","pages"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for docs/ui-pages.md"
    fi
  fi

  # openapi
  local openapi_path
  openapi_path="$(gc::_get_found_doc openapi)"
  if [[ -n "$openapi_path" ]]; then
    local ext
    ext="${openapi_path##*.}"
    local openapi_dest=""
    case "$ext" in
      yml|yaml) openapi_dest="$stage/openapi/openapi.yaml" ;;
      json)     openapi_dest="$stage/openapi/openapi.json" ;;
      *)        openapi_dest="$stage/openapi/openapi.src" ;;
    esac
    install -m 0644 "$openapi_path" "$openapi_dest"
    if (( doc_registry_ready )); then
      local openapi_rel
      openapi_rel="${openapi_dest##$stage/}"
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "openapi" \
        --source-path "$openapi_path" \
        --staging-path "$openapi_dest" \
        --rel-path "$openapi_rel" \
        --tags '["openapi","api"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for ${openapi_rel}"
    fi
  fi

  # sql
  local sql_path
  sql_path="$(gc::_get_found_doc sql)"
  if [[ -n "$sql_path" ]]; then
    install -m 0644 "$sql_path" "$stage/sql/dump.sql"
    if (( doc_registry_ready )); then
      python3 "$doc_registry_cli" register \
        --runtime-dir "$work_dir" \
        --doc-type "sql" \
        --source-path "$sql_path" \
        --staging-path "$stage/sql/dump.sql" \
        --rel-path "sql/dump.sql" \
        --tags '["sql","database"]' \
        --context "normalize" \
        --compute-hash >/dev/null || gc::warn "Documentation registry update failed for sql/dump.sql"
    fi
  fi

  # diagrams
  local f
  for f in ${GC_FOUND_MMD[@]+"${GC_FOUND_MMD[@]}"}; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"
    install -m 0644 "$f" "$stage/diagrams/$base"
  done

  # samples (preserve relative subdirs if under known sample dirs)
  for f in ${GC_FOUND_SAMPLES[@]+"${GC_FOUND_SAMPLES[@]}"}; do
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

  gc::refresh_doc_catalog "$project_root" "$stage"
  echo "$work_dir"
}

gc::refresh_doc_catalog() {
  local project_root="${1:-$PWD}"
  local staging_dir="${2:-}"
  if [[ -z "$staging_dir" ]]; then
    local work_dir
    work_dir="$(gc::ensure_workspace "$project_root")"
    staging_dir="$work_dir/staging"
  fi
  [[ -d "$staging_dir" ]] || return 0
  local plan_dir="$staging_dir/plan"
  local work_dir="$plan_dir/work"
  local docs_dir="$plan_dir/docs"
  mkdir -p "$work_dir" "$docs_dir"
  local out_json="$work_dir/doc-catalog.json"
  local out_library="$docs_dir/doc-library.md"
  local out_index="$docs_dir/doc-index.md"
  if ! command -v python3 >/dev/null 2>&1; then
    gc::warn "python3 not found; skipping documentation catalog refresh."
    return 0
  fi
  local catalog_tool="$GC_LIB_DIR/lib/doc_catalog.py"
  if [[ ! -f "$catalog_tool" ]]; then
    gc::warn "Missing catalog tool (${catalog_tool}); skipping doc catalog refresh."
    return 0
  fi
  if ! python3 "$catalog_tool" \
    --project-root "$project_root" \
    --staging-dir "$staging_dir" \
    --out-json "$out_json" \
    --out-library "$out_library" \
    --out-index "$out_index"; then
    gc::warn "Documentation catalog refresh failed for ${staging_dir}."
  fi
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
