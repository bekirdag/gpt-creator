#!/usr/bin/env bash
# gpt-creator :: scan — fuzzy discovery of project inputs
# Usage: gpt-creator scan /path/to/project
set -Eeuo pipefail

# --- Locate constants.sh (from repo) or fall back to sane defaults ---
__DIR__="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${__DIR__}/../constants.sh" ]]; then
  # shellcheck source=../constants.sh
  source "${__DIR__}/../constants.sh"
else
  # Fallback defaults if constants.sh is not present (keeps script portable)
  GC_TOOL_NAME="gpt-creator"
  GC_RUNTIME_SUBDIR=".gpt-creator"
  GC_EXCLUDES=(-name ".git" -prune -o -name "node_modules" -prune -o -name "dist" -prune -o -name "build" -prune -o -name ".venv" -prune)
fi

PROJECT_DIR="${1:-${PWD}}"
PROJECT_DIR="$(cd "${PROJECT_DIR}" && pwd)"
RUNTIME_DIR="${PROJECT_DIR}/${GC_RUNTIME_SUBDIR:-.gpt-creator}"
MANIFEST_DIR="${RUNTIME_DIR}/manifests"
LOG_DIR="${RUNTIME_DIR}/logs"
STAGING_DIR="${RUNTIME_DIR}/staging"

PROJECT_SCORE_TOKENS=()
_scan_add_token() {
  local token="$1"
  token="$(printf '%s' "$token" | tr '[:upper:]' '[:lower:]')"
  token="$(printf '%s' "$token" | tr -cd 'a-z0-9')"
  [[ ${#token} -ge 3 ]] || return
  local existing
  for existing in "${PROJECT_SCORE_TOKENS[@]}"; do
    [[ "$existing" == "$token" ]] && return
  done
  PROJECT_SCORE_TOKENS+=("$token")
}

project_base="$(basename "$PROJECT_DIR")"
project_base_clean="$(printf '%s' "$project_base" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' ' ')"
for token in $project_base_clean; do
  _scan_add_token "$token"
done

if [[ -n "${GC_PROJECT_KEYWORDS:-}" ]]; then
  keywords_expanded="$(printf '%s' "$GC_PROJECT_KEYWORDS" | tr ',;/' ' ')"
  for token in $keywords_expanded; do
    _scan_add_token "$token"
  done
fi

keywords_file="${RUNTIME_DIR}/project-keywords.txt"
if [[ -f "$keywords_file" ]]; then
  while IFS= read -r line; do
    line="${line%%#*}"
    [[ -n "$line" ]] || continue
    line="$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' ' ')"
    for token in $line; do
      _scan_add_token "$token"
    done
  done < "$keywords_file"
fi

mkdir -p "${MANIFEST_DIR}" "${LOG_DIR}" "${STAGING_DIR}"

TS="$(date +"%Y%m%d-%H%M%S")"
OUT_TSV="${MANIFEST_DIR}/discovery_${TS}.tsv"
OUT_TXT="${MANIFEST_DIR}/discovery_${TS}.txt"

echo "# ${GC_TOOL_NAME:-gpt-creator} :: scan" > "${OUT_TXT}"
echo "# root: ${PROJECT_DIR}" >> "${OUT_TXT}"
echo -e "category	score	path" > "${OUT_TSV}"

log() { printf "[scan] %s\n" "$*" | tee -a "${OUT_TXT}" > /dev/null; }

# --- Helpers ---
shopt -s nullglob dotglob

# Score helper: higher = better
score() {
  local base="$1" ext="$2"
  local s=10
  [[ "${ext}" =~ ^(md|yaml|yml|json|sql|mmd|html|css|txt)$ ]] || s=$((s-2))
  local lower_base
  lower_base="$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')"
  local token
  for token in "${PROJECT_SCORE_TOKENS[@]}"; do
    if [[ -n "$token" && "$lower_base" == *"$token"* ]]; then
      s=$((s+6))
      break
    fi
  done
  [[ "${base}" =~ (final|v1|latest) ]] && s=$((s+4))
  [[ "${base}" =~ (draft|old|backup|copy) ]] && s=$((s-3))
  printf "%d" "${s}"
}

add() {
  local cat="$1"; shift
  local path="$1"; shift
  local base ext s
  base="$(basename "${path}")"
  ext="${base##*.}"
  s="$(score "${base}" "${ext}")"
  printf "%s\t%s\t%s\n" "${cat}" "${s}" "${path}" >> "${OUT_TSV}"
}

# Content probe (fast, safe). BSD grep on macOS supports -E -i -m 1 -q
has() {
  local pattern="$1"; shift
  local file="$1"; shift
  LC_ALL=C grep -E -i -m 1 -q -- "${pattern}" "${file}" 2>/dev/null || return 1
}

# Find all candidate files (skip heavy trees)
log "Scanning… (this may take a short while)"

# Build find command with prunes
FIND_ARGS=( "${PROJECT_DIR}" )
if [[ -n "${GC_EXCLUDES[*]:-}" ]]; then
  FIND_ARGS+=( \( "${GC_EXCLUDES[@]}" -o -type f -print \) )
else
  FIND_ARGS+=( -type f -print )
fi

mapfile -t FILES < <(find "${FIND_ARGS[@]}")

for f in "${FILES[@]}"; do
  name="$(basename "$f")"
  lower="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
  case "${lower}" in
    *pdr*|*product*design*requirements*)
      add "pdr" "${f}"; continue;;
    *sds*|*system*design*spec*)
      add "sds" "${f}"; continue;;
    *rfp*|*request*for*proposal*)
      add "rfp" "${f}"; continue;;
  esac

  # OpenAPI signatures
  if [[ "${lower}" =~ \.(ya?ml|json|txt)$ ]]; then
    if has '^[[:space:]]*openapi[[:space:]]*:[[:space:]]*3(\.[0-9]+)?' "${f}" || has '^[[:space:]]*swagger[[:space:]]*:[[:space:]]*2(\.[0-9]+)?' "${f}" || has '"openapi"[[:space:]]*:[[:space:]]*"' "${f}"; then
      add "openapi" "${f}"; continue
    fi
  fi

  # Mermaid
  if [[ "${lower}" =~ \.mmd$ ]]; then
    if [[ "${lower}" =~ (backoffice|admin) ]]; then
      add "mermaid_backoffice" "${f}"
    elif [[ "${lower}" =~ (web|site|website|front) ]]; then
      add "mermaid_website" "${f}"
    else
      add "mermaid_unknown" "${f}"
    fi
    continue
  fi

  # SQL dumps
  if [[ "${lower}" =~ \.sql$ || "${lower}" =~ sql_dump ]]; then
    add "sql" "${f}"; continue
  fi

  # Jira tasks
  if [[ "${lower}" =~ jira ]] || has 'JIRA|Issue Key' "${f}"; then
    add "jira" "${f}"; continue
  fi

  # UI pages spec
  if has 'HOM1|PRG1|EVT1|AUTH1|AUTH2|MEM1|CTN1' "${f}" && [[ "${lower}" =~ \.md$ ]]; then
    add "ui_pages_doc" "${f}"; continue
  fi

  # Page samples (HTML)
  if [[ "${lower}" =~ \.html$ ]]; then
    if [[ "${f}" == *"/page_samples/"* || "${f}" == *"/website_pages/"* ]]; then
      add "page_sample_website" "${f}"
    elif [[ "${f}" == *"/backoffice_pages/"* ]]; then
      add "page_sample_backoffice" "${f}"
    else
      # Infer from code in filename (ABO1, AUTH1, CTN1, etc.)
      if [[ "${name}" =~ ^(abo|auth|ctn|prg|evt|ins|prc)[0-9]+\.html$ ]]; then
        add "page_sample_website" "${f}"
      else
        add "page_sample_unknown" "${f}"
      fi
    fi
    continue
  fi

  # CSS
  if [[ "${lower}" =~ \.css$ || "${lower}" == style.css ]]; then
    add "css" "${f}"; continue
  fi
done

# Also try to locate obvious top-level folders for samples
if [[ -d "${PROJECT_DIR}/page_samples" ]]; then add "page_samples_root" "${PROJECT_DIR}/page_samples"; fi
if [[ -d "${PROJECT_DIR}/page_samples/website_pages" ]]; then add "page_samples_website_dir" "${PROJECT_DIR}/page_samples/website_pages"; fi
if [[ -d "${PROJECT_DIR}/page_samples/backoffice_pages" ]]; then add "page_samples_backoffice_dir" "${PROJECT_DIR}/page_samples/backoffice_pages"; fi

log "Discovery written to ${OUT_TSV}"
echo "${OUT_TSV}"
