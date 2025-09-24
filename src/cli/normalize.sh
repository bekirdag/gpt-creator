#!/usr/bin/env bash
# gpt-creator :: normalize — stage & rename discovered inputs for downstream steps
# Usage: gpt-creator normalize /path/to/project [path/to/discovery.tsv]
set -Eeuo pipefail

__DIR__="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${__DIR__}/../constants.sh" ]]; then
  # shellcheck source=../constants.sh
  source "${__DIR__}/../constants.sh"
else
  GC_TOOL_NAME="gpt-creator"
  GC_RUNTIME_SUBDIR=".gpt-creator"
fi

PROJECT_DIR="${1:-${PWD}}"
PROJECT_DIR="$(cd "${PROJECT_DIR}" && pwd)"
RUNTIME_DIR="${PROJECT_DIR}/${GC_RUNTIME_SUBDIR:-.gpt-creator}"
MANIFEST_DIR="${RUNTIME_DIR}/manifests"
STAGING_DIR="${RUNTIME_DIR}/staging"
LOG_DIR="${RUNTIME_DIR}/logs"
TSV="${2:-}"

mkdir -p "${MANIFEST_DIR}" "${STAGING_DIR}" "${LOG_DIR}"

# Pick latest discovery.tsv if not provided
if [[ -z "${TSV}" ]]; then
  TSV="$(ls -1t "${MANIFEST_DIR}"/discovery_*.tsv 2>/dev/null | head -n 1 || true)"
fi
[[ -f "${TSV}" ]] || { echo "[normalize] No discovery.tsv found. Run 'gpt-creator scan' first." >&2; exit 1; }

# Target normalized layout
NORM="${STAGING_DIR}/normalized"
DOCS="${NORM}/docs"
UI="${NORM}/ui"
SQL_DIR="${NORM}/db/sql"
DIAG="${NORM}/diagrams"
TASKS="${NORM}/tasks"

mkdir -p "${DOCS}" "${UI}/website" "${UI}/backoffice" "${UI}/styles" "${SQL_DIR}" "${DIAG}" "${TASKS}"

# Helper to choose the top-ranked file by category
choose() {
  local cat="$1"; shift
  awk -F'\t' -v c="${cat}" '$1==c {print $2"\t"$3}' "${TSV}" | sort -rn | head -n 1 | cut -f2-
}

copy_if() {
  local src="$1" dst="$2"
  [[ -f "${src}" ]] || return 1
  mkdir -p "$(dirname "${dst}")"
  /bin/cp -f "${src}" "${dst}"
  echo "${src} -> ${dst}"
}

# Primary docs
PDR="$(choose pdr)"
SDS="$(choose sds)"
RFP="$(choose rfp)"
OPENAPI="$(choose openapi)"
JIRA="$(choose jira)"

# Mermaid
M_WEBSITE="$(choose mermaid_website)"
M_BACKOFFICE="$(choose mermaid_backoffice)"
[[ -z "${M_WEBSITE}" ]] && M_WEBSITE="$(choose mermaid_unknown)"
[[ -z "${M_BACKOFFICE}" ]] && M_BACKOFFICE="$(choose mermaid_unknown)"

# CSS (pick one)
CSS="$(choose css)"

# UI page samples (copy all)
mapfile -t UI_WEB < <(awk -F'\t' '$1=="page_sample_website" || $1=="page_sample_website_dir" {print $3}' "${TSV}")
mapfile -t UI_BOF < <(awk -F'\t' '$1=="page_sample_backoffice" || $1=="page_sample_backoffice_dir" {print $3}' "${TSV}")

# SQL (copy all)
mapfile -t SQLS < <(awk -F'\t' '$1=="sql" {print $3}' "${TSV}")

MAN_OUT="${MANIFEST_DIR}/normalize_$(date +"%Y%m%d-%H%M%S").txt"
echo "# gpt-creator :: normalize" > "${MAN_OUT}"

# Copy docs
[[ -n "${PDR:-}" ]] && copy_if "${PDR}" "${DOCS}/pdr$(printf "%s" "${PDR##*.}" | sed 's/[^a-zA-Z0-9].*//;s/^/./')" >> "${MAN_OUT}"
[[ -n "${SDS:-}" ]] && copy_if "${SDS}" "${DOCS}/sds$(printf "%s" "${SDS##*.}" | sed 's/[^a-zA-Z0-9].*//;s/^/./')" >> "${MAN_OUT}"
[[ -n "${RFP:-}" ]] && copy_if "${RFP}" "${DOCS}/rfp$(printf "%s" "${RFP##*.}" | sed 's/[^a-zA-Z0-9].*//;s/^/./')" >> "${MAN_OUT}"
if [[ -n "${OPENAPI:-}" ]]; then
  ext="${OPENAPI##*.}"
  if [[ "${ext}" == "yaml" || "${ext}" == "yml" ]]; then
    copy_if "${OPENAPI}" "${DOCS}/openapi.yaml" >> "${MAN_OUT}"
  elif [[ "${ext}" == "json" ]]; then
    copy_if "${OPENAPI}" "${DOCS}/openapi.json" >> "${MAN_OUT}"
  else
    copy_if "${OPENAPI}" "${DOCS}/openapi.txt" >> "${MAN_OUT}"
  fi
fi
[[ -n "${JIRA:-}" ]] && copy_if "${JIRA}" "${TASKS}/jira.md" >> "${MAN_OUT}"

# Copy diagrams
[[ -n "${M_WEBSITE:-}" ]] && copy_if "${M_WEBSITE}" "${DIAG}/website.mmd" >> "${MAN_OUT}"
[[ -n "${M_BACKOFFICE:-}" ]] && copy_if "${M_BACKOFFICE}" "${DIAG}/backoffice.mmd" >> "${MAN_OUT}"

# Copy CSS
if [[ -n "${CSS:-}" ]]; then
  base="$(basename "${CSS}")"
  copy_if "${CSS}" "${UI}/styles/${base}" >> "${MAN_OUT}"
fi

# Copy UI samples
for p in "${UI_WEB[@]}"; do
  if [[ -d "${p}" ]]; then
    rsync -a --exclude '.DS_Store' "${p}/" "${UI}/website/" 2>/dev/null || cp -R "${p}/." "${UI}/website/" 2>/dev/null || true
    echo "${p} -> ${UI}/website/" >> "${MAN_OUT}"
  elif [[ -f "${p}" ]]; then
    copy_if "${p}" "${UI}/website/$(basename "${p}")" >> "${MAN_OUT}"
  fi
done

for p in "${UI_BOF[@]}"; do
  if [[ -d "${p}" ]]; then
    rsync -a --exclude '.DS_Store' "${p}/" "${UI}/backoffice/" 2>/dev/null || cp -R "${p}/." "${UI}/backoffice/" 2>/dev/null || true
    echo "${p} -> ${UI}/backoffice/" >> "${MAN_OUT}"
  elif [[ -f "${p}" ]]; then
    copy_if "${p}" "${UI}/backoffice/$(basename "${p}")" >> "${MAN_OUT}"
  fi
done

# Copy SQLs
for s in "${SQLS[@]}"; do
  [[ -f "${s}" ]] && copy_if "${s}" "${SQL_DIR}/$(basename "${s}")" >> "${MAN_OUT}"
done

echo "[normalize] Staged files under: ${NORM}"
echo "${MAN_OUT}"
