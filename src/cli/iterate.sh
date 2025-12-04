#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLI_ROOT="$ROOT_DIR"

export GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

# Load shared constants if present
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  . "$ROOT_DIR/src/constants.sh"
fi

# Sensible defaults if constants are missing
: "${GC_NAME:=gpt-creator}"
# Prefer CLI default model.
: "${GC_DEFAULT_MODEL:=gpt-5.1-codex}"
: "${PROJECT_DIR:=${PWD}}"
: "${GC_STATE_DIR:=${PROJECT_DIR}/.gpt-creator}"
: "${GC_STAGING_DIR:=${GC_STATE_DIR}/staging}"
: "${GC_DOCKER_DIR:=${PROJECT_DIR}/docker}"
: "${GC_COMPOSE_FILE:=${GC_DOCKER_DIR}/docker-compose.yml}"
: "${GC_WORK_DIR_NAME:=.gpt-creator}"

info(){ printf "[%s] %s\n" "$GC_NAME" "$*"; }
warn(){ printf "\033[33m[%s][WARN]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
err(){  printf "\033[31m[%s][ERROR]\033[0m %s\n" "$GC_NAME" "$*" >&2; }
die(){ err "$*"; exit 1; }

gc_clone_python_tool() {
  local script_name="${1:?python script name required}"
  local root="${2:-${PROJECT_DIR:-$ROOT_DIR}}"
  local cli_root="${GC_ROOT:-${CLI_ROOT:-$ROOT_DIR}}"
  local scripts_root="${GC_SCRIPTS_ROOT:-${cli_root}/scripts}"

  if [[ -z "$root" ]]; then
    die "Unable to determine project root while preparing ${script_name}"
  fi

  local source_path="${scripts_root}/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    die "Python helper missing at ${source_path}"
  fi

  local target_dir="${root}/${GC_WORK_DIR_NAME}/shims/python"
  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || die "Failed to create ${target_dir}"
  fi
  local target_path="${target_dir}/${script_name}"
  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || die "Failed to copy ${script_name} helper"
  fi
  if [[ "$script_name" == *.py ]]; then
    local base_name="${script_name%.py}"
    local sidecar="${base_name}_lib.py"
    local sidecar_source="${scripts_root}/python/${sidecar}"
    local sidecar_target="${target_dir}/${sidecar}"
    if [[ -f "$sidecar_source" ]]; then
      if [[ ! -f "$sidecar_target" || "$sidecar_source" -nt "$sidecar_target" ]]; then
        cp "$sidecar_source" "$sidecar_target" || die "Failed to copy ${sidecar} helper"
      fi
    fi
  fi
  printf '%s\n' "$target_path"
}

humanize_name() {
  local helper_path
  helper_path="$(gc_clone_python_tool "humanize_name.py" "${PROJECT_DIR:-$ROOT_DIR}")" || return 1
  python3 "$helper_path" "${1:-}"
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
  env \
    ITERATE_DEFAULT_MODEL="$GC_DEFAULT_MODEL" \
    gc_cli_render_template "help/iterate_usage.txt"
}

: "${CODEX_BIN:=codex}"
: "${CODEX_MODEL:=${GC_DEFAULT_MODEL}}"
DRY_RUN=0
TASKS_FILE=""
case "${GC_DRY_RUN:-}" in
  1|true|yes|on) DRY_RUN=1 ;;
esac

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
RUN_DIR="$GC_STATE_DIR/${GC_ITERATE_RUN_DIR:-iterate_runs}/$timestamp"
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
  title="${entry#*|}"
  slug="$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9 -_' | tr ' ' '-' | cut -c1-80)"
  PROMPT="$RUN_DIR/task_${i}_${slug}.prompt.md"
  OUTPUT="$OUT_DIR/task_${i}_${slug}.out.md"

  env \
    ITERATE_CODEX_MODEL="$CODEX_MODEL" \
    ITERATE_PROJECT_LABEL="$PROJECT_LABEL_PROMPT" \
    ITERATE_TASK_TITLE="$title" \
    gc_cli_render_template "prompts/iterate_task.prompt.md.tmpl" > "$PROMPT"

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
