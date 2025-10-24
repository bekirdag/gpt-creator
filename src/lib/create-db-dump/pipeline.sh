#!/usr/bin/env bash
# shellcheck shell=bash
# create-db-dump pipeline helpers

if [[ -n "${GC_LIB_CREATE_DB_DUMP_PIPELINE_SH:-}" ]]; then
  return 0
fi
GC_LIB_CREATE_DB_DUMP_PIPELINE_SH=1

set -o errtrace

cddb::log()  { printf '\033[36m[create-db-dump]\033[0m %s\n' "$*"; }
cddb::warn() { printf '\033[33m[create-db-dump][WARN]\033[0m %s\n' "$*"; }
cddb::err()  { printf '\033[31m[create-db-dump][ERROR]\033[0m %s\n' "$*" >&2; }
cddb::die()  { cddb::err "$*"; exit 1; }

cddb::abs_path() {
  local path="${1:-}"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$path"
  else
    python3 - <<'PY' "$path"
import pathlib
import sys

p = pathlib.Path(sys.argv[1] or '.')
print(p.expanduser().resolve())
PY
  fi
}

cddb::codex_has_subcommand() {
  local subcmd="$1"
  if ! command -v "$CDDB_CODEX_CMD" >/dev/null 2>&1; then
    return 1
  fi
  "$CDDB_CODEX_CMD" --help 2>/dev/null | grep -Eqi "(^|[[:space:]/-])${subcmd}([[:space:]/-]|$)" || return 1
}

cddb::run_codex() {
  local prompt_file="${1:?prompt file required}"
  local output_file="${2:?output file required}"
  local label="${3:-codex}"

  if [[ "$CDDB_DRY_RUN" == "1" ]]; then
    cddb::warn "[dry-run] Skipping Codex invocation for ${label}"
    printf '{"status": "dry-run", "label": "%s"}\n' "$label" >"$output_file"
    return 0
  fi

  mkdir -p "$(dirname "$output_file")"

  if cddb::codex_has_subcommand chat; then
    local cmd=("$CDDB_CODEX_CMD" chat --model "$CDDB_MODEL" --prompt-file "$prompt_file" --output "$output_file")
    cddb::log "Running Codex (${label}) via chat"
    if ! "${cmd[@]}"; then
      cddb::warn "Codex invocation failed for ${label}"
      return 1
    fi
    return 0
  fi

  if cddb::codex_has_subcommand exec; then
    local args=("$CDDB_CODEX_CMD" exec --model "$CDDB_MODEL" --full-auto --sandbox workspace-write --skip-git-repo-check)
    if [[ -n "${CODEX_PROFILE:-}" ]]; then
      args+=(--profile "$CODEX_PROFILE")
    fi
    if [[ -n "$CDDB_PROJECT_ROOT" ]]; then
      args+=(--cd "$CDDB_PROJECT_ROOT")
    fi
    if [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
      args+=(-c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\"")
    fi
    args+=(--output-last-message "$output_file")
    cddb::log "Running Codex (${label}) via exec"
    if ! "${args[@]}" < "$prompt_file"; then
      cddb::warn "Codex invocation failed for ${label}"
      return 1
    fi
    return 0
  fi

  if cddb::codex_has_subcommand generate; then
    local cmd=("$CDDB_CODEX_CMD" generate --model "$CDDB_MODEL" --prompt-file "$prompt_file" --output "$output_file")
    cddb::log "Running Codex (${label}) via generate"
    if ! "${cmd[@]}"; then
      cddb::warn "Codex invocation failed for ${label}"
      return 1
    fi
    return 0
  fi

  cddb::warn "Codex CLI '${CDDB_CODEX_CMD}' lacks chat/exec/generate; writing dry-run marker for ${label}."
  printf '{"status": "codex-missing", "label": "%s"}\n' "$label" >"$output_file"
  return 0
}

cddb::init() {
  CDDB_PROJECT_ROOT="${1:?project root required}"
  CDDB_MODEL="${2:-${CODEX_MODEL:-gpt-5-codex}}"
  CDDB_DRY_RUN="${3:-0}"
  # shellcheck disable=SC2034  # reserved for future force re-run behavior
  CDDB_FORCE="${4:-0}"

  CDDB_PROJECT_ROOT="$(cddb::abs_path "$CDDB_PROJECT_ROOT")"
  [[ -d "$CDDB_PROJECT_ROOT" ]] || cddb::die "Project root not found: $CDDB_PROJECT_ROOT"

  CDDB_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

  source "$CDDB_ROOT_DIR/src/constants.sh"
  source "$CDDB_ROOT_DIR/src/gpt-creator.sh"
  [[ -f "$CDDB_ROOT_DIR/src/lib/path.sh" ]] && source "$CDDB_ROOT_DIR/src/lib/path.sh"

  CDDB_WORK_DIR="$(gc::ensure_workspace "$CDDB_PROJECT_ROOT")"
  CDDB_STAGING_DIR="$CDDB_WORK_DIR/staging"
  CDDB_PLAN_DIR="$CDDB_STAGING_DIR/plan"
  CDDB_PIPELINE_DIR="$CDDB_PLAN_DIR/create-db-dump"
  CDDB_PROMPTS_DIR="$CDDB_PIPELINE_DIR/prompts"
  CDDB_OUTPUT_DIR="$CDDB_PIPELINE_DIR/out"
  CDDB_SQL_DIR="$CDDB_PIPELINE_DIR/sql"
  CDDB_TMP_DIR="$CDDB_PIPELINE_DIR/tmp"

  mkdir -p "$CDDB_PROMPTS_DIR" "$CDDB_OUTPUT_DIR" "$CDDB_SQL_DIR" "$CDDB_TMP_DIR"

  CDDB_SCHEMA_PATH="$CDDB_SQL_DIR/schema.sql"
  CDDB_SEED_PATH="$CDDB_SQL_DIR/seed.sql"

  CDDB_CODEX_CMD="${CODEX_BIN:-${CODEX_CMD:-codex}}"
  if ! command -v "$CDDB_CODEX_CMD" >/dev/null 2>&1; then
    cddb::warn "Codex CLI '$CDDB_CODEX_CMD' not found; enabling dry-run mode."
    CDDB_DRY_RUN=1
  fi

  cddb::locate_documents
}

cddb::locate_documents() {
  if [[ -f "$CDDB_STAGING_DIR/plan/sds/sds.md" ]]; then
    CDDB_SDS_PATH="$CDDB_STAGING_DIR/plan/sds/sds.md"
  elif [[ -f "$CDDB_STAGING_DIR/docs/sds.md" ]]; then
    CDDB_SDS_PATH="$CDDB_STAGING_DIR/docs/sds.md"
  elif [[ -f "$CDDB_STAGING_DIR/sds.md" ]]; then
    CDDB_SDS_PATH="$CDDB_STAGING_DIR/sds.md"
  else
    CDDB_SDS_PATH="$(find "$CDDB_STAGING_DIR" -maxdepth 3 -type f -iname '*sds*.md' | head -n1 || true)"
  fi

  [[ -n "${CDDB_SDS_PATH:-}" && -f "$CDDB_SDS_PATH" ]] || cddb::die "Unable to locate SDS document under ${CDDB_STAGING_DIR}."
  cddb::log "Using SDS source → ${CDDB_SDS_PATH}"

  if [[ -f "$CDDB_STAGING_DIR/plan/pdr/pdr.md" ]]; then
    CDDB_PDR_PATH="$CDDB_STAGING_DIR/plan/pdr/pdr.md"
  elif [[ -f "$CDDB_STAGING_DIR/docs/pdr.md" ]]; then
    CDDB_PDR_PATH="$CDDB_STAGING_DIR/docs/pdr.md"
  else
    CDDB_PDR_PATH="$(find "$CDDB_STAGING_DIR" -maxdepth 3 -type f -iname '*pdr*.md' | head -n1 || true)"
  fi
}

cddb::prepare_context() {
  CDDB_SDS_CONTEXT="$CDDB_PIPELINE_DIR/sds_context.md"
  CDDB_SDS_SNIPPET="$CDDB_PIPELINE_DIR/sds_context_snippet.md"
  cp "$CDDB_SDS_PATH" "$CDDB_SDS_CONTEXT"
  if ! head -n 2000 "$CDDB_SDS_PATH" >"$CDDB_SDS_SNIPPET"; then
    cp "$CDDB_SDS_PATH" "$CDDB_SDS_SNIPPET"
  fi

  if [[ -n "${CDDB_PDR_PATH:-}" && -f "$CDDB_PDR_PATH" ]]; then
    CDDB_PDR_SNIPPET="$CDDB_PIPELINE_DIR/pdr_context_snippet.md"
    if ! head -n 1000 "$CDDB_PDR_PATH" >"$CDDB_PDR_SNIPPET"; then
      cp "$CDDB_PDR_PATH" "$CDDB_PDR_SNIPPET"
    fi
  else
    CDDB_PDR_SNIPPET=""
  fi
}

cddb::write_schema_prompt() {
  local prompt_file="${1:?prompt file required}"
  mkdir -p "$(dirname "$prompt_file")"
  {
    cat <<'PROMPT'
You are a principal database architect. Design a MySQL schema that fully supports the system described in the SDS.

Instructions:
- Produce a complete SQL dump suitable for `mysql < schema.sql`.
- Define databases, tables, columns with data types, defaults, nullability, character sets, indexes, primary keys, foreign keys, unique constraints, and check constraints where appropriate.
- Model relationships explicitly with foreign keys, cascading rules, and junction tables.
- Include derived tables needed for analytics, audit, compliance, or background processing called out in the SDS.
- Add necessary views or stored routines only if they are critical to system operation.
- Use consistent naming conventions and comment statements (`-- ...`) to explain non-obvious design decisions.
- Ensure the schema is normalized but pragmatic—denormalize when the SDS calls for performance considerations.
- Output only SQL (no code fences, no prose outside of SQL comments).

## SDS Excerpt
PROMPT
    cat "$CDDB_SDS_SNIPPET"
    if [[ -n "$CDDB_PDR_SNIPPET" ]]; then
      cat <<'PROMPT'

## PDR Excerpt
PROMPT
      cat "$CDDB_PDR_SNIPPET"
    fi
    cat <<'PROMPT'

## End Context
PROMPT
  } >"$prompt_file"
}

cddb::write_seed_prompt() {
  local prompt_file="${1:?prompt file required}"
  local schema_file="${2:?schema path required}"
  mkdir -p "$(dirname "$prompt_file")"
  {
    cat <<'PROMPT'
You are preparing production-quality seed data for a freshly provisioned MySQL database.

Instructions:
- Use the provided schema to craft INSERT statements that populate reference data, configuration defaults, sample content, feature flags, roles/permissions, enumerations, and critical bootstrap records required for the system to operate end-to-end.
- Provide realistic values, respecting all constraints, foreign keys, and unique indexes.
- Cover every table that must start non-empty (including lookup tables and essential user accounts).
- Avoid dummy lorem ipsum; align the seed data with the domain terminology found in the SDS.
- Wrap the output as executable SQL: include `START TRANSACTION;` and `COMMIT;` around the inserts, and set `SET NAMES utf8mb4;` at the start.
- Output SQL only—no prose or code fences.

## Database Schema
PROMPT
    cat "$schema_file"
    cat <<'PROMPT'

## SDS Excerpt
PROMPT
    cat "$CDDB_SDS_SNIPPET"
    cat <<'PROMPT'

## End Context
PROMPT
  } >"$prompt_file"
}

cddb::write_review_prompt() {
  local schema_file="${1:?schema required}"
  local seed_file="${2:?seed required}"
  local prompt_file="${3:?prompt required}"
  mkdir -p "$(dirname "$prompt_file")"
  {
    cat <<'PROMPT'
You are auditing a MySQL schema dump and seed dataset before launch.

Tasks:
1. Validate that table definitions, keys, indexes, constraints, data types, and relationships satisfy the SDS requirements and are internally consistent.
2. Confirm the seed data loads without violating constraints and provides the minimum viable records for the system to run end-to-end.
3. Resolve inconsistencies by editing the schema and/or seed scripts directly.
4. Optimise naming, ensure referential integrity, and align default values with business logic described in the SDS.
5. Return the corrected schema followed by a blank line and then the corrected seed script. Do not include explanatory prose or fences.

## SDS Excerpt
PROMPT
    cat "$CDDB_SDS_SNIPPET"
    cat <<'PROMPT'

## Schema Dump
PROMPT
    cat "$schema_file"
    cat <<'PROMPT'

## Seed Dump
PROMPT
    cat "$seed_file"
    cat <<'PROMPT'

## End Inputs
PROMPT
  } >"$prompt_file"
}

cddb::run_pipeline() {
  cddb::prepare_context

  local schema_prompt="$CDDB_PROMPTS_DIR/schema.prompt.sql"
  local schema_raw="$CDDB_OUTPUT_DIR/schema.raw.sql"

  cddb::log "Generating schema dump from SDS"
  cddb::write_schema_prompt "$schema_prompt"
  if cddb::run_codex "$schema_prompt" "$schema_raw" "db-schema"; then
    if [[ "$CDDB_DRY_RUN" == "1" ]]; then
      cddb::warn "[dry-run] schema generation skipped"
    else
      cp "$schema_raw" "$CDDB_SCHEMA_PATH"
      cddb::log "Schema dump written → ${CDDB_SCHEMA_PATH}"
    fi
  else
    cddb::die "Codex failed while generating schema dump"
  fi

  if [[ "$CDDB_DRY_RUN" == "1" ]]; then
    cddb::warn "[dry-run] Skipping seed and review steps"
    return
  fi

  local seed_prompt="$CDDB_PROMPTS_DIR/seed.prompt.sql"
  local seed_raw="$CDDB_OUTPUT_DIR/seed.raw.sql"
  cddb::log "Generating seed dump"
  cddb::write_seed_prompt "$seed_prompt" "$CDDB_SCHEMA_PATH"
  if cddb::run_codex "$seed_prompt" "$seed_raw" "db-seed"; then
    if [[ "$CDDB_DRY_RUN" == "1" ]]; then
      cddb::warn "[dry-run] seed generation skipped"
    else
      cp "$seed_raw" "$CDDB_SEED_PATH"
      cddb::log "Seed dump written → ${CDDB_SEED_PATH}"
    fi
  else
    cddb::die "Codex failed while generating seed dump"
  fi

  if [[ "$CDDB_DRY_RUN" == "1" ]]; then
    cddb::warn "[dry-run] Skipping review step"
    return
  fi

  if [[ ! -s "$CDDB_SCHEMA_PATH" || ! -s "$CDDB_SEED_PATH" ]]; then
    cddb::warn "Schema or seed dump missing; skipping review"
    return
  fi

  local review_prompt="$CDDB_PROMPTS_DIR/review.prompt.sql"
  local review_raw="$CDDB_OUTPUT_DIR/review.raw.sql"
  local review_schema="$CDDB_TMP_DIR/schema.reviewed.sql"
  local review_seed="$CDDB_TMP_DIR/seed.reviewed.sql"

  cddb::log "Reviewing schema and seed dumps for consistency"
  cddb::write_review_prompt "$CDDB_SCHEMA_PATH" "$CDDB_SEED_PATH" "$review_prompt"
  if cddb::run_codex "$review_prompt" "$review_raw" "db-review"; then
    python3 - <<'PY' "$review_raw" "$review_schema" "$review_seed"
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding='utf-8').strip()
if not raw:
    schema_sql = ''
    seed_sql = ''
else:
    parts = raw.split('\n\n', 1)
    if len(parts) == 2:
        schema_sql, seed_sql = parts
    else:
        schema_sql, seed_sql = raw, ''
Path(sys.argv[2]).write_text(schema_sql.strip() + ('\n' if schema_sql and not schema_sql.endswith('\n') else ''), encoding='utf-8')
Path(sys.argv[3]).write_text(seed_sql.strip() + ('\n' if seed_sql and not seed_sql.endswith('\n') else ''), encoding='utf-8')
PY
    if [[ -s "$review_schema" ]]; then
      local backup_schema="${CDDB_SCHEMA_PATH%.sql}.initial.sql"
      if [[ ! -f "$backup_schema" ]]; then
        cp "$CDDB_SCHEMA_PATH" "$backup_schema"
      fi
      mv "$review_schema" "$CDDB_SCHEMA_PATH"
      cddb::log "Reviewed schema saved → ${CDDB_SCHEMA_PATH}"
    else
      cddb::warn "Review did not return schema edits; keeping original schema"
    fi
    if [[ -s "$review_seed" ]]; then
      local backup_seed="${CDDB_SEED_PATH%.sql}.initial.sql"
      if [[ ! -f "$backup_seed" ]]; then
        cp "$CDDB_SEED_PATH" "$backup_seed"
      fi
      mv "$review_seed" "$CDDB_SEED_PATH"
      cddb::log "Reviewed seed saved → ${CDDB_SEED_PATH}"
    else
      cddb::warn "Review did not return seed edits; keeping original seed"
    fi
  else
    cddb::warn "Codex review step failed; retaining original schema and seed"
  fi
}

return 0
