#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load shared constants if present
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  . "$ROOT_DIR/src/constants.sh"
fi

# Sensible defaults if constants are missing
: "${GC_NAME:=gpt-creator}"
: "${GC_VERSION:=0.1.0}"
: "${GC_DEFAULT_MODEL:=gpt-5-high}"
: "${PROJECT_DIR:=${PWD}}"
: "${GC_STATE_DIR:=${PROJECT_DIR}/.gpt-creator}"
: "${GC_STAGING_DIR:=${GC_STATE_DIR}/staging}"
: "${GC_DOCKER_DIR:=${PROJECT_DIR}/docker}"
: "${GC_COMPOSE_FILE:=${GC_DOCKER_DIR}/docker-compose.yml}"

info(){ printf "[%s] %s\n" "$GC_NAME" "$*"; }
warn(){ printf "\033[33m[%s][WARN]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
err(){  printf "\033[31m[%s][ERROR]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
die(){ err "$*"; exit 1; }

humanize_name() {
  python3 - <<'PY' "${1:-}"
import pathlib
import re
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else ''
if raw:
    raw = pathlib.Path(raw).name
raw = re.sub(r'[_\-]+', ' ', raw).strip()
if not raw:
    print('Project')
else:
    words = []
    for token in raw.split():
        if len(token) <= 3:
            words.append(token.upper())
        elif token.isupper():
            words.append(token)
        else:
            words.append(token.capitalize())
    print(' '.join(words))
PY
}

if [[ -n "${GC_PROJECT_TITLE:-}" ]]; then
  PROJECT_LABEL="$GC_PROJECT_TITLE"
else
  PROJECT_LABEL="$(humanize_name "$PROJECT_DIR")"
fi
[[ -n "$PROJECT_LABEL" ]] || PROJECT_LABEL="Project"
project_label_lower="$(printf '%s' "$PROJECT_LABEL" | tr '[:upper:]' '[:lower:]')"
if [[ "$project_label_lower" == "project" ]]; then
  PROJECT_LABEL_PROMPT="this project"
else
  PROJECT_LABEL_PROMPT="the ${PROJECT_LABEL}"
fi

warn "'gpt-creator iterate' is deprecated. Use 'gpt-creator create-tasks' followed by 'gpt-creator work-on-tasks'."

usage() {
  cat <<'EOF'
Usage: gpt-creator iterate [options]

Options:
  --tasks-file PATH  Path to Jira tasks markdown (default: discover under .gpt-creator/staging)
  --model NAME       Codex model to use (default: $GC_DEFAULT_MODEL)
  --codex-bin PATH   Codex CLI binary (default: codex)
  --dry-run          Build prompts only; do not invoke Codex (default: off)
  -h, --help         Show help

Behavior:
  • Builds a consolidated context from normalized docs in .gpt-creator/staging (PDR, SDS, OpenAPI, SQL, Mermaid, UI pages, samples).
  • Parses unchecked Jira tasks ('- [ ] ...') and runs Codex once per task with the context + task prompt.
  • Stores outputs under .gpt-creator/codex_runs/<timestamp>/.
EOF
}

: "${CODEX_BIN:=codex}"
: "${CODEX_MODEL:=${GC_DEFAULT_MODEL}}"
DRY_RUN=0
TASKS_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tasks-file) TASKS_FILE="$2"; shift 2;;
    --model) CODEX_MODEL="$2"; shift 2;;
    --codex-bin) CODEX_BIN="$2"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) err "Unknown argument: $1"; usage; exit 2;;
  esac
done

# Find tasks file if not provided
if [[ -z "${TASKS_FILE}" ]]; then
  shopt -s nullglob globstar
  candidates=( "$GC_STAGING_DIR"/**/*[Jj][Ii][Rr][Aa]*.md )
  if [[ ${#candidates[@]} -gt 0 ]]; then
    TASKS_FILE="${candidates[0]}"
  else
    die "No Jira tasks markdown found in $GC_STAGING_DIR (hint: use --tasks-file)."
  fi
fi
[[ -f "$TASKS_FILE" ]] || die "Tasks file not found: $TASKS_FILE"

timestamp="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$GC_STATE_DIR/codex_runs/$timestamp"
CTX_DIR="$RUN_DIR/context"
OUT_DIR="$RUN_DIR/out"
mkdir -p "$CTX_DIR" "$OUT_DIR"

info "Building Codex context from staging → $CTX_DIR"
# Consolidate context
{
  echo "# Project Context (auto-generated)"
  echo
  for f in "$GC_STAGING_DIR"/pdr.* "$GC_STAGING_DIR"/sds.* "$GC_STAGING_DIR"/openapi.* \
           "$GC_STAGING_DIR"/*.sql "$GC_STAGING_DIR"/*.mmd \
           "$GC_STAGING_DIR"/*ui*pages*.* "$GC_STAGING_DIR"/*rfp*.* \
           "$GC_STAGING_DIR"/*style*.* "$GC_STAGING_DIR"/*css*; do
    [[ -f "$f" ]] || continue
    echo ""
    echo "----- FILE: $(basename "$f") -----"
    # If binary or huge, just reference path
    if file -b --mime-type "$f" | grep -q 'text'; then
      sed -e 's/\t/  /g' "$f" | sed -e $'s/\r$//'
    else
      echo "(binary or non-text file; path: $f)"
    fi
  done
} > "$CTX_DIR/context.md"

info "Parsing Jira tasks from: $TASKS_FILE"
mapfile -t TASKS < <(grep -nE '^- \[ \] ' "$TASKS_FILE" | sed -E 's/^([0-9]+):- \[ \] (.*)$/\1|\2/')

if [[ ${#TASKS[@]} -eq 0 ]]; then
  warn "No unchecked '- [ ]' tasks found; exiting."
  exit 0
fi

# Verify Codex presence (optional)
if ! command -v "$CODEX_BIN" >/dev/null 2>&1; then
  if [[ $DRY_RUN -eq 0 ]]; then
    warn "Codex binary '$CODEX_BIN' not found. Switching to --dry-run."
  fi
  DRY_RUN=1
fi

i=0
for entry in "${TASKS[@]}"; do
  ((i++)) || true
  line="${entry%%|*}"
  title="${entry#*|}"
  slug="$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9 -_' | tr ' ' '-' | cut -c1-80)"
  PROMPT="$RUN_DIR/task_${i}_${slug}.prompt.md"
  OUTPUT="$OUT_DIR/task_${i}_${slug}.out.md"

  cat > "$PROMPT" <<EOP
# You are Codex (model: $CODEX_MODEL)

You are helping build ${PROJECT_LABEL_PROMPT} based on normalized docs. Read **all** context below, then complete the task precisely.
Focus on: NestJS (API), MySQL 8 (Prisma/TypeORM), Vue 3 (site+admin), Docker. Adhere to PDR/SDS acceptance checks.

## Task
$title

## Deliverable
- Concrete code changes (files, paths, diffs or complete new files).
- Any migrations (SQL/Prisma).
- Shell commands to wire into this repo structure.
- Short verification steps.

## Context (truncated when large)
(Full context: context.md in this run directory)
EOP

  # Append a tail of the context (to give Codex some inline hints while keeping the full context on disk)
  tail -n 400 "$CTX_DIR/context.md" >> "$PROMPT"

  info "Prepared task $i: $title"
  if [[ $DRY_RUN -eq 1 ]]; then
    info "DRY-RUN: prompt at $PROMPT"
  else
    info "Invoking Codex for task $i → $OUTPUT"
    # Generic invocation: accept prompt via stdin if CLI doesn't support files
    if "$CODEX_BIN" chat --model "$CODEX_MODEL" --input-file "$PROMPT" --output-file "$OUTPUT" >/dev/null 2>&1; then
      ok "Codex completed task $i → $OUTPUT"
    else
      # Fallback: pipe prompt to stdin and capture output
      if cat "$PROMPT" | "$CODEX_BIN" chat --model "$CODEX_MODEL" > "$OUTPUT" 2>/dev/null; then
        ok "Codex completed task $i → $OUTPUT (stdin mode)"
      else
        warn "Codex invocation failed for task $i. Prompt kept at $PROMPT"
      fi
    fi
  fi
done

info "Run artifacts in: $RUN_DIR"
