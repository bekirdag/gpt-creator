# shellcheck shell=bash
# shellcheck disable=SC2034
# gpt-creator — constants & defaults

# ---- Project identity ----
GC_NAME="gpt-creator"
GC_VERSION="${GC_VERSION:-0.1.0}"
GC_MODEL_DEFAULT="${GC_MODEL_DEFAULT:-gpt-5-high}"   # Codex model to use by default

# Root (repository) directory (resolve relative to this file)
GC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GC_BANNER_FILE="${GC_BANNER_FILE:-$GC_ROOT/src/banner.txt}"

# Staging workspace inside a target project
GC_WORK_DIR_NAME="${GC_WORK_DIR_NAME:-.gpt-creator}"
GC_STAGING_SUBDIRS=(docs openapi sql diagrams samples ui plan logs)

# Prerequisite command names (soft-checked here; installer handles hard checks)
GC_PREREQ_CMDS=(docker node pnpm mysql)

# Codex local client (override with env)
GC_CODEX_BIN="${GC_CODEX_BIN:-codex}"
GC_CODEX_MODEL="${GC_CODEX_MODEL:-$GC_MODEL_DEFAULT}"

# Discovery patterns (case-insensitive; best-effort fuzzy search)

# Documents
GC_DOC_PATTERNS=(
  "*pdr*.md" "*product*design*requirement*.md"
  "*sds*.md" "*system*design*spec*.md"
  "*rfp*.md" "*request*for*proposal*.md"
  "*jira*task*.md" "*jira*.md"
  "*ui*pages*.md" "*website*ui*pages*.md"
)

# OpenAPI
GC_OPENAPI_PATTERNS=(
  "openapi.yaml" "openapi.yml"
  "*openapi*.yml" "*openapi*.yaml" "*openapi*.json" "*openapi*.txt"
)

# SQL dumps
GC_SQL_PATTERNS=(
  "sql_dump*.sql" "*production*.sql" "*.sql"
)

# Mermaid diagrams
GC_MERMAID_PATTERNS=("*.mmd")

# Page samples (dirs + loose files)
GC_SAMPLE_DIRS=("page_samples" "samples")
GC_SAMPLE_FILE_PATTERNS=("*.html" "*.css")

# Optional page-code hints that may appear in sample HTML filenames
GC_UI_SAMPLE_CODES=("ABO1" "AUTH1" "PRG1" "EVT1" "CTN1")

# Colors (toggle with GC_COLOR=0 to disable)
if [[ -t 1 && "${GC_COLOR:-1}" -eq 1 ]]; then
  GC_CLR_RESET=$'\e[0m'
  GC_CLR_BOLD=$'\e[1m'
  GC_CLR_DIM=$'\e[2m'
  GC_CLR_RED=$'\e[31m'
  GC_CLR_GREEN=$'\e[32m'
  GC_CLR_YELLOW=$'\e[33m'
  GC_CLR_BLUE=$'\e[34m'
  GC_CLR_MAGENTA=$'\e[35m'
  GC_CLR_CYAN=$'\e[36m'
else
  GC_CLR_RESET=""; GC_CLR_BOLD=""; GC_CLR_DIM=""
  GC_CLR_RED=""; GC_CLR_GREEN=""; GC_CLR_YELLOW=""
  GC_CLR_BLUE=""; GC_CLR_MAGENTA=""; GC_CLR_CYAN=""
fi
