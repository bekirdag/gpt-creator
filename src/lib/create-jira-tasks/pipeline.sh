#!/usr/bin/env bash
# shellcheck shell=bash
# create-jira-tasks pipeline helpers

if [[ -n "${GC_LIB_CREATE_JIRA_TASKS_PIPELINE_SH:-}" ]]; then
  return 0
fi
GC_LIB_CREATE_JIRA_TASKS_PIPELINE_SH=1

set -o errtrace

CJT_DOC_FILES=()
CJT_SDS_CHUNKS_DIR=""
CJT_SDS_CHUNKS_LIST=""
CJT_PDR_PATH=""
CJT_SQL_PATH=""

cjt::clone_python_tool() {
  local script_name="${1:?python script name required}"
  local project_root="${2:-${CJT_PROJECT_ROOT:-${PROJECT_DIR:-$PWD}}}"

  if declare -f gc_clone_python_tool >/dev/null 2>&1; then
    gc_clone_python_tool "$script_name" "$project_root"
    return
  fi

  local cli_root
  if [[ -n "${CJT_ROOT_DIR:-}" ]]; then
    cli_root="$CJT_ROOT_DIR"
  else
    cli_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  fi

  local source_path="${cli_root}/scripts/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    cjt::die "Python helper missing at ${source_path}"
  fi

  local work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  local target_dir="${project_root%/}/${work_dir_name}/shims/python"
  local target_path="${target_dir}/${script_name}"
  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || cjt::die "Failed to create ${target_dir}"
  fi
  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || cjt::die "Failed to copy ${script_name} helper"
  fi
  printf '%s\n' "$target_path"
}

cjt::log()   { printf '\033[36m[create-jira-tasks]\033[0m %s\n' "$*"; }
cjt::warn()  { printf '\033[33m[create-jira-tasks][WARN]\033[0m %s\n' "$*"; }
cjt::err()   { printf '\033[31m[create-jira-tasks][ERROR]\033[0m %s\n' "$*" >&2; }
cjt::die()   { cjt::err "$*"; exit 1; }
cjt::state_init() {
  CJT_STATE_FILE="$CJT_PIPELINE_DIR/state.json"
  if (( CJT_FORCE )); then
    rm -f "$CJT_STATE_FILE"
  fi
  if [[ ! -f "$CJT_STATE_FILE" ]]; then
    cat >"$CJT_STATE_FILE" <<'JSON'
{
  "version": 1,
  "epics": {"status": "pending"},
  "stories": {"status": "pending", "completed": []},
  "tasks": {"status": "pending", "completed": []},
  "refine": {"status": "pending", "stories": {}}
}
JSON
  fi
}

cjt::state_stage_is_completed() {
  local stage="$1"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_stage_is_completed.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$stage"
}

cjt::state_mark_stage_completed() {
  local stage="$1"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_mark_stage_completed.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$stage"
}

cjt::state_mark_stage_pending() {
  local stage="$1"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_mark_stage_pending.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$stage"
}

cjt::state_story_is_completed() {
  local section="$1" slug="$2" file_path="$3"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_story_is_completed.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$section" "$slug" "$file_path"
}

cjt::state_mark_story_completed() {
  local section="$1" slug="$2"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_mark_story_completed.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$section" "$slug"
}

cjt::state_get_refine_progress() {
  local slug="$1" total="$2"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_get_refine_progress.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$slug" "$total"
}

cjt::state_update_refine_progress() {
  local slug="$1" next_task="$2" total="$3"
  local helper_path
  helper_path="$(cjt::clone_python_tool "state_update_refine_progress.py")" || return 1
  python3 "$helper_path" "$CJT_STATE_FILE" "$slug" "$next_task" "$total"
}

cjt::abs_path() {
  local path="${1:-}"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$path"
  else
    local helper_path
    helper_path="$(cjt::clone_python_tool "abs_path.py")" || return 1
    python3 "$helper_path" "$path"
  fi
}

cjt::slugify() {
  local value="${1:-}"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  value="$(printf '%s' "$value" | tr -cs 'a-z0-9' '-')"
  value="$(printf '%s' "$value" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${value:-item}"
}

cjt::derive_project_title() {
  local input="${1:-}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "derive_project_title.py")" || return 1
  python3 "$helper_path" "$input"
}


cjt::init() {
  CJT_PROJECT_ROOT="${1:?project root required}"
  local cjt_default_model="${CODEX_MODEL_NON_CODE:-${CODEX_MODEL_LOW:-${CODEX_MODEL:-gpt-5-codex}}}"
  CJT_MODEL="${2:-$cjt_default_model}"
  CJT_FORCE="${3:-0}"
  CJT_SKIP_REFINE="${4:-0}"
  CJT_DRY_RUN="${5:-0}"

  CJT_PROJECT_ROOT="$(cjt::abs_path "$CJT_PROJECT_ROOT")"
  [[ -d "$CJT_PROJECT_ROOT" ]] || cjt::die "Project root not found: $CJT_PROJECT_ROOT"

  CJT_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

  source "$CJT_ROOT_DIR/src/constants.sh"
  source "$CJT_ROOT_DIR/src/gpt-creator.sh"
  [[ -f "$CJT_ROOT_DIR/src/lib/path.sh" ]] && source "$CJT_ROOT_DIR/src/lib/path.sh"

  CJT_WORK_DIR="$(gc::ensure_workspace "$CJT_PROJECT_ROOT")"
  CJT_STAGING_DIR="$CJT_WORK_DIR/staging"
  CJT_PLAN_DIR="$CJT_STAGING_DIR/plan"
  CJT_PIPELINE_DIR="$CJT_PLAN_DIR/create-jira-tasks"
  CJT_PROMPTS_DIR="$CJT_PIPELINE_DIR/prompts"
  CJT_OUTPUT_DIR="$CJT_PIPELINE_DIR/out"
  CJT_JSON_DIR="$CJT_PIPELINE_DIR/json"
  CJT_JSON_STORIES_DIR="$CJT_JSON_DIR/stories"
  CJT_JSON_TASKS_DIR="$CJT_JSON_DIR/tasks"
  CJT_JSON_REFINED_DIR="$CJT_JSON_DIR/refined"
  CJT_TMP_DIR="$CJT_PIPELINE_DIR/tmp"
  CJT_CONTEXT_FILE="$CJT_PIPELINE_DIR/context-full.md"
  CJT_CONTEXT_SNIPPET_FILE="$CJT_PIPELINE_DIR/context-snippet.md"
  CJT_CONTEXT_EPIC_FILE="$CJT_PIPELINE_DIR/context-epics.md"
  CJT_CONTEXT_BOILER_CACHE="$CJT_PIPELINE_DIR/context-boilerplate-cache.txt"
  CJT_TASKS_DIR="$CJT_PLAN_DIR/tasks"
  CJT_PLAN_DOCS_DIR="$CJT_PLAN_DIR/docs"
  CJT_DOC_LIBRARY_PATH="${CJT_PLAN_DOCS_DIR}/doc-library.md"
  CJT_DOC_INDEX_PATH="${CJT_PLAN_DOCS_DIR}/doc-index.md"
  CJT_DOC_CATALOG_PATH="$CJT_PLAN_DIR/work/doc-catalog.json"

  mkdir -p "$CJT_TASKS_DIR"
  CJT_TASKS_DB_PATH="${CJT_TASKS_DB_PATH:-$CJT_TASKS_DIR/tasks.db}"

  mkdir -p "$CJT_PROMPTS_DIR" "$CJT_OUTPUT_DIR" "$CJT_JSON_DIR" \
    "$CJT_JSON_STORIES_DIR" "$CJT_JSON_TASKS_DIR" "$CJT_JSON_REFINED_DIR" "$CJT_TMP_DIR"

  if [[ -n "${CJT_PROJECT_TITLE:-}" ]]; then
    :
  elif [[ -n "${GC_PROJECT_TITLE:-}" ]]; then
    CJT_PROJECT_TITLE="$GC_PROJECT_TITLE"
  else
    CJT_PROJECT_TITLE="$(cjt::derive_project_title "$CJT_PROJECT_ROOT")"
  fi

  local codex_bin="${CODEX_BIN:-${CODEX_CMD:-codex}}"
  if ! command -v "$codex_bin" >/dev/null 2>&1; then
    cjt::warn "Codex CLI '${codex_bin}' not found on PATH; commands will run in dry-run mode."
    CJT_DRY_RUN=1
  fi

  CJT_CODEX_CMD="$codex_bin"

  if [[ "$CJT_FORCE" == "1" && "${CJT_DRY_RUN:-0}" != "1" ]]; then
    rm -f "$CJT_TASKS_DB_PATH"
  fi

  CJT_INCREMENTAL_DB=0

  if [[ -f "$CJT_STAGING_DIR/docs/pdr.md" ]]; then
    CJT_PDR_PATH="$CJT_STAGING_DIR/docs/pdr.md"
  elif [[ -f "$CJT_STAGING_DIR/pdr.md" ]]; then
    CJT_PDR_PATH="$CJT_STAGING_DIR/pdr.md"
  elif [[ -f "$CJT_PLAN_DIR/pdr/pdr.md" ]]; then
    CJT_PDR_PATH="$CJT_PLAN_DIR/pdr/pdr.md"
  else
    CJT_PDR_PATH=""
  fi

  if [[ -f "$CJT_STAGING_DIR/sql/dump.sql" ]]; then
    CJT_SQL_PATH="$CJT_STAGING_DIR/sql/dump.sql"
  else
    CJT_SQL_PATH=""
    if [[ -d "$CJT_STAGING_DIR/sql" ]]; then
      local first_sql
      first_sql="$(find "$CJT_STAGING_DIR/sql" -maxdepth 1 -type f -name '*.sql' | head -n1 || true)"
      CJT_SQL_PATH="$first_sql"
    fi
  fi

  cjt::state_init
}

cjt::prepare_inputs() {
  cjt::log "Discovering documentation under $CJT_PROJECT_ROOT"
  gc::discover "$CJT_PROJECT_ROOT" "$CJT_PIPELINE_DIR/discovery.yaml"

  cjt::log "Normalizing source documents into staging workspace"
  local _had_nounset=0
  if [[ $- == *u* ]]; then
    _had_nounset=1
    set +u
  fi
  gc::normalize_to_staging "$CJT_PROJECT_ROOT" >/dev/null
  if (( _had_nounset )); then
    set -u
  fi

  cjt::log "Compiling context excerpts"
  cjt::build_context_files
}

cjt::collect_source_files() {
  CJT_DOC_FILES=()
  local pattern
  for pattern in \
    "$CJT_STAGING_DIR/docs"/*.md \
    "$CJT_STAGING_DIR"/*.md \
    "$CJT_STAGING_DIR"/*.txt \
    "$CJT_STAGING_DIR/openapi"/* \
    "$CJT_STAGING_DIR/sql"/*.sql; do
    [[ -f "$pattern" ]] || continue
    CJT_DOC_FILES+=("$pattern")
  done
}

cjt::sanitize_doc_to() {
  local source_path="${1:?source path required}"
  local dest_path="${2:?dest path required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "sanitize_doc_to.py")" || return 1
  python3 "$helper_path" "$source_path" "$dest_path"
}

cjt::append_file_with_char_limit() {
  local source_path="${1:?source path required}"
  local dest_path="${2:?destination path required}"
  local max_chars="${3:-0}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "append_file_with_char_limit.py")" || return 1
  python3 "$helper_path" "$source_path" "$dest_path" "$max_chars"
}

cjt::append_file_with_line_limit() {
  local source_path="${1:?source path required}"
  local dest_path="${2:?destination path required}"
  local max_lines="${3:-0}"
  local max_chars="${4:-0}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "append_file_with_line_limit.py")" || return 1
  python3 "$helper_path" "$source_path" "$dest_path" "$max_lines" "$max_chars"
}



cjt::filter_context_boilerplate() {
  local source_path="${1:?source path required}"
  local dest_path="${2:?destination path required}"
  local cache_path="${3:?cache path required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "filter_context_boilerplate.py")" || return 1
  python3 "$helper_path" "$source_path" "$dest_path" "$cache_path"
}



cjt::chunk_doc_by_headings() {
  local source_file="${1:?source file required}"
  local chunk_dir="${2:?chunk directory required}"
  local out_list="${3:?chunk list file required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "chunk_doc_by_headings.py")" || return 1
  python3 "$helper_path" "$source_file" "$chunk_dir" "$out_list"
}

cjt::build_epic_context_summary() {
  local source_path="${1:?source context required}"
  local dest_path="${2:?destination path required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "build_epic_context_summary.py")" || return 1
  python3 "$helper_path" "$source_path" "$dest_path"
}

cjt::render_context_snippet() {
  local manifest_path="${1:?manifest required}"
  local output_path="${2:?output path required}"
  local catalog_path="${3:-}"
  local library_path="${4:-}"
  local index_path="${5:-}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "render_context_snippet.py")" || return 1
  python3 "$helper_path" "$manifest_path" "$output_path" "$catalog_path" "$library_path" "$index_path"
}

cjt::build_context_files() {
  local _had_nounset=0
  if [[ $- == *u* ]]; then
    _had_nounset=1
    set +u
  fi
  cjt::collect_source_files
  if [[ -z ${CJT_DOC_FILES+x} ]]; then
    CJT_DOC_FILES=()
  fi
  : "${CJT_CONTEXT_FULL_CHAR_LIMIT:=8000}"
  : "${CJT_CONTEXT_SNIPPET_LINES:=45}"
  : "${CJT_CONTEXT_SNIPPET_CHAR_LIMIT:=3200}"
  : "${CJT_DOC_LIBRARY_SECTION_LINES:=48}"
  : "${CJT_DOC_LIBRARY_SECTION_CHAR_LIMIT:=2200}"
  : "${CJT_DOC_INDEX_SECTION_LINES:=72}"
  : "${CJT_DOC_INDEX_SECTION_CHAR_LIMIT:=2600}"
  : "${CJT_DOC_HEADINGS_LIMIT:=8}"
  : "${CJT_DOC_EXCERPT_CHAR_LIMIT:=900}"
  : "${CJT_DOC_EXCERPT_PARAGRAPH_LIMIT:=5}"

  local cleaned_dir="$CJT_PIPELINE_DIR/cleaned-docs"
  local dedupe_cache="${CJT_CONTEXT_BOILER_CACHE:-$CJT_PIPELINE_DIR/context-boilerplate-cache.txt}"
  mkdir -p "$cleaned_dir" "$CJT_TMP_DIR"

  : > "$CJT_CONTEXT_FILE"
  : > "$CJT_CONTEXT_SNIPPET_FILE"
  : > "$CJT_CONTEXT_EPIC_FILE"
  : > "$dedupe_cache"
  local doc_manifest="$CJT_TMP_DIR/context-doc-manifest.tsv"
  : > "$doc_manifest"

  {
    echo "# Consolidated Project Context"
    echo "(Source: .gpt-creator staging copy)"
    echo
  } >> "$CJT_CONTEXT_FILE"

  local sds_candidate="" sds_clean_path=""
  local file
  for file in "${CJT_DOC_FILES[@]}"; do
    local base_name
    base_name="$(basename "$file")"
    local rel_path="$file"
    if [[ "$file" == "$CJT_PROJECT_ROOT/"* ]]; then
      rel_path="${file#$CJT_PROJECT_ROOT/}"
    fi
    if [[ -z "$sds_candidate" && "$base_name" =~ [sS][dD][sS] ]]; then
      sds_candidate="$file"
    fi

    local cleaned_path
    cleaned_path="$(mktemp "$cleaned_dir/doc_XXXXXX")"
    cjt::sanitize_doc_to "$file" "$cleaned_path"

    local context_filtered
    context_filtered="$(mktemp "$cleaned_dir/context_XXXXXX")"
    cjt::filter_context_boilerplate "$cleaned_path" "$context_filtered" "$dedupe_cache"

    printf -- '----- FILE: %s -----\n' "$rel_path" >> "$CJT_CONTEXT_FILE"
    if [[ -s "$context_filtered" ]]; then
      cjt::append_file_with_char_limit "$context_filtered" "$CJT_CONTEXT_FILE" "$CJT_CONTEXT_FULL_CHAR_LIMIT"
    else
      printf '(empty after sanitization)\n\n' >> "$CJT_CONTEXT_FILE"
    fi

    printf '%s\t%s\n' "$file" "$context_filtered" >> "$doc_manifest"

    if [[ -z "$sds_clean_path" && "$file" == "$sds_candidate" ]]; then
      sds_clean_path="$cleaned_path"
    fi
  done

  if [[ -z "$sds_candidate" ]] && [[ -f "$CJT_PLAN_DIR/sds/sds.md" ]]; then
    sds_candidate="$CJT_PLAN_DIR/sds/sds.md"
  fi

  if [[ -n "$sds_candidate" ]]; then
    if [[ -z "$sds_clean_path" || ! -f "$sds_clean_path" ]]; then
      sds_clean_path="$(mktemp "$cleaned_dir/sds_XXXXXX")"
      cjt::sanitize_doc_to "$sds_candidate" "$sds_clean_path"
    fi
    CJT_SDS_CHUNKS_DIR="$CJT_PIPELINE_DIR/sds-chunks"
    CJT_SDS_CHUNKS_LIST="$CJT_SDS_CHUNKS_DIR/list.txt"
    cjt::chunk_doc_by_headings "$sds_clean_path" "$CJT_SDS_CHUNKS_DIR" "$CJT_SDS_CHUNKS_LIST"
  else
    CJT_SDS_CHUNKS_DIR=""
    CJT_SDS_CHUNKS_LIST=""
  fi

  if [[ -s "$doc_manifest" ]]; then
    cjt::render_context_snippet \
      "$doc_manifest" \
      "$CJT_CONTEXT_SNIPPET_FILE" \
      "${CJT_DOC_CATALOG_PATH:-}" \
      "${CJT_DOC_LIBRARY_PATH:-}" \
      "${CJT_DOC_INDEX_PATH:-}"
  else
    {
      echo "# Context Excerpt"
      echo "(No documentation discovered in staging.)"
      echo
    } > "$CJT_CONTEXT_SNIPPET_FILE"
  fi

  cjt::build_epic_context_summary "$CJT_CONTEXT_SNIPPET_FILE" "$CJT_CONTEXT_EPIC_FILE"

  if (( _had_nounset )); then
    set -u
  fi
}

cjt::codex_has_subcommand() {
  local subcmd="$1"
  if ! command -v "$CJT_CODEX_CMD" >/dev/null 2>&1; then
    return 1
  fi
  "$CJT_CODEX_CMD" --help 2>/dev/null | grep -Eqi "(^|[[:space:]/-])${subcmd}([[:space:]/-]|$)" || return 1
}

cjt::task_title_from_json() {
  local json_file="${1:?json file required}" index="${2:?index required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "task_title_from_json.py")" || return 1
  python3 "$helper_path" "$json_file" "$index"
}

cjt::run_codex() {
  local prompt_file="${1:?prompt file required}"
  local output_file="${2:?output file required}"
  local label="${3:-codex}"
  local codex_reasoning="${CODEX_REASONING_EFFORT:-${CODEX_REASONING_EFFORT_NON_CODE:-low}}"

  if [[ "$CJT_DRY_RUN" == "1" ]]; then
    cjt::warn "[dry-run] Skipping Codex invocation for $label"
    printf '{"status": "dry-run", "label": "%s"}\n' "$label" >"$output_file"
    return 0
  fi

  mkdir -p "$(dirname "$output_file")"
  local model="$CJT_MODEL"

  if cjt::codex_has_subcommand chat; then
    local cmd=("$CJT_CODEX_CMD" chat --model "$model" --prompt-file "$prompt_file" --output "$output_file")
    cjt::log "Running Codex (${label}) with model $CJT_MODEL (reasoning=${codex_reasoning})"
    if ! "${cmd[@]}"; then
      cjt::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if cjt::codex_has_subcommand exec; then
    local args=("$CJT_CODEX_CMD" exec --model "$model" --full-auto --sandbox workspace-write --skip-git-repo-check)
    if [[ -n "${CODEX_PROFILE:-}" ]]; then
      args+=(--profile "$CODEX_PROFILE")
    fi
    if [[ -n "$CJT_PROJECT_ROOT" ]]; then
      args+=(--cd "$CJT_PROJECT_ROOT")
    fi
    if [[ -n "$codex_reasoning" ]]; then
      args+=(-c "model_reasoning_effort=\"${codex_reasoning}\"")
    fi
    args+=(--output-last-message "$output_file")
    cjt::log "Running Codex (${label}) with model $CJT_MODEL via exec (reasoning=${codex_reasoning})"
    if ! "${args[@]}" < "$prompt_file"; then
      cjt::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if cjt::codex_has_subcommand generate; then
    local cmd=("$CJT_CODEX_CMD" generate --model "$model" --prompt-file "$prompt_file" --output "$output_file")
    cjt::log "Running Codex (${label}) with model $CJT_MODEL via generate (reasoning=${codex_reasoning})"
    if ! "${cmd[@]}"; then
      cjt::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  cjt::warn "Codex CLI '${CJT_CODEX_CMD}' does not expose supported subcommands (chat/exec/generate); switching to dry-run for ${label}."
  printf '{"status": "codex-missing", "label": "%s"}\n' "$label" >"$output_file"
  return 0
}

cjt::wrap_json_extractor() {
  local infile="${1:?input file required}"
  local outfile="${2:?output file required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "wrap_json_extractor.py")" || return 1
  python3 "$helper_path" "$infile" "$outfile"
}

cjt::write_story_prompt() {
  local epic_id="${1:?epic id required}"
  local prompt_file="${2:?prompt file required}"
  local epics_json="$CJT_JSON_DIR/epics.json"
  local project_label="${CJT_PROJECT_TITLE:-the product}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "write_story_prompt.py")" || return 1
  CJT_PROMPT_TITLE="$project_label" python3 "$helper_path" "$epics_json" "$epic_id" "$prompt_file" "$CJT_CONTEXT_SNIPPET_FILE"
}

cjt::generate_tasks() {
  if cjt::state_stage_is_completed "tasks"; then
    cjt::log "Tasks already generated; skipping"
    return
  fi

  cjt::state_mark_stage_pending "tasks"
  local inline_refine_enabled=0
  local inline_refine_reason=""
  if cjt::inline_refine_is_enabled; then
    inline_refine_enabled=1
  else
    inline_refine_reason="${CJT_INLINE_REFINE_REASON:-}"
    if [[ "${CJT_INLINE_REFINE_NOTICE_EMITTED:-0}" != "1" && -n "$inline_refine_reason" ]]; then
      case "$inline_refine_reason" in
        pending-refine-stage)
          cjt::log "Inline refinement disabled; the refine_tasks stage will handle polishing."
          ;;
        disabled-explicit)
          cjt::log "Inline refinement disabled (CJT_INLINE_REFINE_ENABLED=0)."
          ;;
      esac
      CJT_INLINE_REFINE_NOTICE_EMITTED=1
    fi
    unset CJT_INLINE_REFINE_REASON
  fi

  local story_file
  while IFS= read -r story_file; do
    [[ -n "$story_file" ]] || continue
    local slug
    slug="${story_file##*/}"; slug="${slug%.json}"
    local prompt_file="$CJT_PROMPTS_DIR/tasks_${slug}.prompt.md"
    local raw_file="$CJT_OUTPUT_DIR/tasks_${slug}.raw.txt"
    local json_file="$CJT_JSON_TASKS_DIR/${slug}.json"
    if cjt::state_story_is_completed "tasks" "$slug" "$json_file"; then
      cjt::log "Tasks already generated for story ${slug}; skipping"
      continue
    fi
    cjt::write_task_prompt "$story_file" "$prompt_file"
    cjt::log "Generating tasks for story ${slug}"
    if cjt::run_codex "$prompt_file" "$raw_file" "tasks-${slug}"; then
      cjt::wrap_json_extractor "$raw_file" "$json_file"
      cjt::state_mark_story_completed "tasks" "$slug"
      cjt::sync_story_snapshot_to_db "$json_file" "$slug"
      if (( inline_refine_enabled )); then
        CJT_INLINE_REFINEMENT_ALLOWED=1
        cjt::inline_refine_story_tasks "$json_file" "$slug"
        unset CJT_INLINE_REFINEMENT_ALLOWED
      fi
    else
      cjt::die "Codex failed while generating tasks for story ${slug}"
    fi
  done < <(find "$CJT_JSON_STORIES_DIR" -maxdepth 1 -type f -name '*.json' | sort)

  cjt::state_mark_stage_completed "tasks"
}

cjt::inline_refine_is_enabled() {
  CJT_INLINE_REFINE_REASON=""
  local flag="${CJT_INLINE_REFINE_ENABLED:-}"
  if [[ -n "$flag" ]]; then
    flag="${flag,,}"
    case "$flag" in
      1|true|yes|on)
        return 0
        ;;
      0|false|no|off|"")
        CJT_INLINE_REFINE_REASON="disabled-explicit"
        return 1
        ;;
    esac
  fi
  if [[ "${CJT_SKIP_REFINE:-0}" == "1" ]]; then
    return 0
  fi
  CJT_INLINE_REFINE_REASON="pending-refine-stage"
  return 1
}

cjt::sync_story_snapshot_to_db() {
  local story_json="${1:?story json required}"
  local slug="${2:?story slug required}"
  if [[ "${CJT_DRY_RUN:-0}" == "1" ]]; then
    return
  fi
  if [[ -z "${CJT_TASKS_DB_PATH:-}" ]]; then
    return
  fi
  if ! python3 "$CJT_ROOT_DIR/src/lib/create-jira-tasks/upsert_story_into_db.py" \
      "$CJT_TASKS_DB_PATH" "$story_json" "$slug"; then
    cjt::warn "Failed to upsert story ${slug} into tasks database"
  else
    CJT_INCREMENTAL_DB=1
  fi
}

cjt::inline_refine_story_tasks() {
  local story_json="${1:?story json required}"
  local slug="${2:?story slug required}"
  if [[ "${CJT_DRY_RUN:-0}" == "1" ]]; then
    cjt::log "[dry-run] Skipping inline refinement for ${slug}"
    return
  fi
  if [[ ! -f "$story_json" ]]; then
    return
  fi
  if [[ "${CJT_INLINE_REFINEMENT_ALLOWED:-0}" != "1" ]]; then
    if ! cjt::inline_refine_is_enabled; then
      return
    fi
  fi

  local working="$CJT_TMP_DIR/inline_refine_${slug}.json"
  mkdir -p "$CJT_TMP_DIR"
  cp "$story_json" "$working" || {
    cjt::warn "Unable to prepare working copy for ${slug}; skipping inline refinement"
    return
  }

  local refine_mode="${CJT_INLINE_REFINE_MODE:-auto}"
  case "${refine_mode,,}" in
    off|disabled|none|0)
      cjt::log "Inline refinement disabled (mode=${refine_mode}); skipping ${slug}"
      rm -f "$working" 2>/dev/null || true
      return
      ;;
    all|auto|automatic|1)
      ;;
    *)
      cjt::warn "Inline refinement mode '${refine_mode}' not recognized; skipping ${slug}"
      rm -f "$working" 2>/dev/null || true
      return
      ;;
  esac

  local inline_refine_helper
  inline_refine_helper="$(cjt::clone_python_tool "inline_refine_story_tasks.py")" || {
    rm -f "$working" 2>/dev/null || true
    return
  }

  local refine_data
  refine_data="$(python3 "$inline_refine_helper" "$working" "$refine_mode")"
  if [[ $? -ne 0 || -z "$refine_data" ]]; then
    cjt::warn "Inline refinement helper failed for ${slug}; skipping"
    rm -f "$working" 2>/dev/null || true
    return
  fi

  local total=0
  local -a refine_order=()
  local line_no=0
  while IFS= read -r line; do
    if (( line_no == 0 )); then
      total="${line:-0}"
    else
      [[ -z "$line" ]] || refine_order+=("$line")
    fi
    ((line_no++))
  done <<<"$refine_data"

  local max_tasks="${CJT_INLINE_REFINE_MAX_TASKS:-0}"
  if (( max_tasks > 0 && ${#refine_order[@]} > max_tasks )); then
    refine_order=("${refine_order[@]:0:max_tasks}")
  fi

  if (( total <= 0 || ${#refine_order[@]} == 0 )); then
    cjt::log "Inline refinement not required for story ${slug} (mode=${refine_mode})"
    rm -f "$working" 2>/dev/null || true
    return
  fi

  local selected_count=${#refine_order[@]}
  cjt::log "Inline refining story ${slug}: selected=${selected_count}${total:+ / total=${total}} (mode=${refine_mode})"

  local actual_index
  for actual_index in "${refine_order[@]}"; do
    if [[ -z "$actual_index" ]]; then
      continue
    fi
    local task_num
    printf -v task_num "%03d" $((actual_index + 1))
    local prompt_file="$CJT_PROMPTS_DIR/inline_refine_${slug}_${task_num}.prompt.md"
    local raw_file="$CJT_OUTPUT_DIR/inline_refine_${slug}_${task_num}.raw.txt"
    local refined_json="$CJT_TMP_DIR/inline_refine_${slug}_${task_num}.json"

    cjt::write_refine_task_prompt \
      "$working" "$actual_index" "$prompt_file" \
      "${CJT_SDS_CHUNKS_LIST:-}" "${CJT_PDR_PATH:-}" "${CJT_SQL_PATH:-}" "${CJT_TASKS_DB_PATH:-}"

    if cjt::run_codex "$prompt_file" "$raw_file" "refine-inline-${slug}-task-${task_num}"; then
      if cjt::wrap_json_extractor "$raw_file" "$refined_json"; then
        cjt::apply_refined_task "$working" "$refined_json" "$actual_index"
        cjt::sync_story_snapshot_to_db "$working" "$slug"
      else
        cjt::warn "Inline refinement produced non-JSON output for ${slug} task ${task_num}; keeping prior content"
      fi
    else
      cjt::warn "Codex failed during inline refinement for ${slug} task ${task_num}"
    fi

    rm -f "$raw_file" "$refined_json" 2>/dev/null || true
  done

  mv "$working" "$story_json"
  cjt::sync_story_snapshot_to_db "$story_json" "$slug"
}

cjt::write_task_prompt() {
  local story_file="${1:?story json required}"
  local prompt_file="${2:?prompt file required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "write_task_prompt.py")" || return 1
  python3 "$helper_path" "$story_file" "$CJT_CONTEXT_SNIPPET_FILE" "$prompt_file" "${CJT_SDS_CHUNKS_LIST:-}"
}


cjt::refine_tasks() {
  if [[ "$CJT_SKIP_REFINE" == "1" ]]; then
    cjt::log "Skipping task refinement (per flag)"
    return
  fi
  : "${CJT_REFINE_PROCESSED_TASKS:=0}"
  : "${CJT_REFINE_PROCESSED_STORIES:=0}"
  : "${CJT_REFINE_SKIPPED_STORIES:=0}"
  if [[ -n "${CJT_REFINE_TOTAL_TASKS:-}" ]]; then
    cjt::log "Backlog summary: tasks total=${CJT_REFINE_TOTAL_TASKS}, refined=${CJT_REFINE_REFINED_TASKS:-0}, pending=${CJT_REFINE_PENDING_TASKS:-0}; stories total=${CJT_REFINE_TOTAL_STORIES:-0}, pending=${CJT_REFINE_PENDING_STORIES:-0}."
  fi
  if [[ "${CJT_DRY_RUN:-0}" == "1" ]]; then
    cjt::warn "Running in dry-run mode; no Codex calls will be issued and the database will not be updated."
  fi
  local using_db=0
  local story_entries
  local story_mode="pending"
  if [[ "${CJT_REFINE_FORCE:-0}" == "1" || "${CJT_HAVE_REFINED_COLUMN:-0}" == "0" ]]; then
    story_mode="all"
  fi
  if [[ -n "${CJT_TASKS_DB_PATH:-}" ]]; then
    using_db=1
    story_entries=()
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      story_entries+=("$line")
    done < <(python3 "$CJT_ROOT_DIR/src/lib/create-jira-tasks/list_stories_from_db.py" "$CJT_TASKS_DB_PATH" "${CJT_ONLY_STORY_SLUG:-}" "$story_mode")
    if (( ${#story_entries[@]} == 0 )); then
      cjt::warn "No stories found in tasks database${CJT_ONLY_STORY_SLUG:+ matching filter '${CJT_ONLY_STORY_SLUG}'}; skipping refinement"
      return
    fi
  else
    story_entries=()
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      story_entries+=("$line")
    done < <(find "$CJT_JSON_TASKS_DIR" -maxdepth 1 -type f -name '*.json' | sort)
  fi

  if [[ "${CJT_IGNORE_REFINE_STATE:-0}" != "1" ]]; then
    if cjt::state_stage_is_completed "refine"; then
      cjt::log "Task refinement already completed; skipping"
      return
    fi
    cjt::state_mark_stage_pending "refine"
  fi

  local entry
  for entry in "${story_entries[@]}"; do
    local slug=""
    local source_file=""
    local working_copy=""
    local pending_total
    local -a refine_order=()
    if (( using_db )); then
      slug="${entry}"
      working_copy="$CJT_TMP_DIR/refine_${slug}.json"
      if ! task_total=$(python3 "$CJT_ROOT_DIR/src/lib/create-jira-tasks/export_story_from_db.py" "$CJT_TASKS_DB_PATH" "$slug" "$working_copy" "$story_mode" 2>/dev/null); then
        cjt::warn "Unable to load story ${slug} from tasks database; skipping"
        continue
      fi
      if [[ -z "$task_total" ]]; then
        cjt::warn "Unable to load story ${slug} from tasks database; skipping"
        continue
      fi
      mkdir -p "$CJT_JSON_TASKS_DIR"
      cp "$working_copy" "$CJT_JSON_TASKS_DIR/${slug}.json" 2>/dev/null || true
    else
      source_file="$entry"
      slug="${source_file##*/}"; slug="${slug%.json}"
      working_copy="$CJT_TMP_DIR/refine_${slug}.json"
      cp "$source_file" "$working_copy"
      local count_helper
      count_helper="$(cjt::clone_python_tool "count_story_tasks.py")" || {
        rm -f "$working_copy" 2>/dev/null || true
        continue
      }
      task_total="$(python3 "$count_helper" "$working_copy")"
      local count_status=$?
      if (( count_status != 0 )); then
        cjt::warn "Unable to count tasks for story ${slug}; skipping"
        rm -f "$working_copy" 2>/dev/null || true
        continue
      fi
    fi
    if [[ -n "${CJT_ONLY_STORY_SLUG:-}" ]]; then
      local _match=0
      IFS=',' read -r -a _filters <<<"${CJT_ONLY_STORY_SLUG}"
      local slug_lower
      slug_lower=$(printf '%s' "$slug" | tr '[:upper:]' '[:lower:]')
      for _filter in "${_filters[@]}"; do
        local filter_lower
        filter_lower=$(printf '%s' "$_filter" | tr '[:upper:]' '[:lower:]')
        if [[ "$slug_lower" == "$filter_lower" ]]; then
          _match=1
          break
        fi
      done
      unset _filters
      if (( _match == 0 )); then
        rm -f "$working_copy" 2>/dev/null || true
        continue
      fi
    fi
    task_total=${task_total//$'\r'/}
    task_total=${task_total//$'\n'/}
    if [[ -z "$task_total" ]]; then
      task_total=0
    fi

    local refine_mode="${CJT_REFINE_MODE:-auto}"
    local refine_helper
    refine_helper="$(cjt::clone_python_tool "refine_tasks_selection.py")" || {
      rm -f "$working_copy" 2>/dev/null || true
      continue
    }
    local refine_data
    refine_data="$(python3 "$refine_helper" "$working_copy" "$refine_mode")"
    local refine_status=$?
    if [[ $refine_status -ne 0 ]]; then
      cjt::warn "Inline refine helper failed for story ${slug}; skipping"
      rm -f "$working_copy" 2>/dev/null || true
      continue
    fi
    if [[ "$refine_data" == "SKIP" ]]; then
      cjt::log "Refinement skipped for story ${slug} (mode=${refine_mode})"
      rm -f "$working_copy" 2>/dev/null || true
      continue
    fi

    local -a refine_order=()
    local task_total_candidates=""
    local __line_index=0
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      if (( __line_index == 0 )); then
        task_total_candidates="$line"
      else
        refine_order+=("$line")
      fi
      ((__line_index++))
    done <<<"$refine_data"
    if [[ -n "$task_total_candidates" ]]; then
      task_total="$task_total_candidates"
    fi
    task_total=${task_total//$'\r'/}
    task_total=${task_total//$'\n'/}
    local pending_total=${#refine_order[@]}

    if (( pending_total == 0 )); then
      if (( using_db )) && [[ "$story_mode" != "all" ]]; then
        cjt::log "All tasks already refined for story ${slug}; skipping"
      else
        cjt::warn "No tasks found for story ${slug}; skipping refinement"
      fi
      rm -f "$CJT_JSON_REFINED_DIR/${slug}.json" 2>/dev/null || true
      if [[ "${CJT_IGNORE_REFINE_STATE:-0}" != "1" ]]; then
        cjt::state_update_refine_progress "$slug" 0 0
      fi
      rm -f "$working_copy" 2>/dev/null || true
      CJT_REFINE_SKIPPED_STORIES=$((CJT_REFINE_SKIPPED_STORIES + 1))
      continue
    fi

    local progress
    local start_index=0
    if (( using_db )); then
      progress=0
      start_index=0
    else
      if [[ "${CJT_IGNORE_REFINE_STATE:-0}" == "1" ]]; then
        cjt::state_update_refine_progress "$slug" 0 "$pending_total"
        progress=0
      else
        progress="$(cjt::state_get_refine_progress "$slug" "$pending_total")"
        if [[ "$progress" == "done" && -f "$CJT_JSON_REFINED_DIR/${slug}.json" ]]; then
          cjt::log "Refinement already completed for story ${slug}; skipping"
          rm -f "$working_copy" 2>/dev/null || true
          continue
        fi
        if [[ "$progress" != "done" ]]; then
          start_index=${progress:-0}
        fi
      fi
    fi
    local total_indices=${#refine_order[@]}
    local next_target="N/A"
    if (( total_indices > start_index )); then
      next_target="${refine_order[start_index]}"
    fi
    cjt::log "Refining story ${slug}: pending=${pending_total}${task_total:+ / total=${task_total}} (start index ${start_index}, next task index ${next_target})"
    local idx
    local processed_count=0
    local story_success=1
    for (( idx=start_index; idx<total_indices; idx++ )); do
      local actual_index="${refine_order[idx]}"
      local task_num
      printf -v task_num "%03d" $((actual_index + 1))
      local prompt_file="$CJT_PROMPTS_DIR/refine_${slug}_task_${task_num}.prompt.md"
      local raw_file="$CJT_OUTPUT_DIR/refine_${slug}_task_${task_num}.raw.txt"
      local json_file="$CJT_TMP_DIR/refine_${slug}_task_${task_num}.json"

      cjt::write_refine_task_prompt "$working_copy" "$actual_index" "$prompt_file" \
        "${CJT_SDS_CHUNKS_LIST:-}" "${CJT_PDR_PATH:-}" "${CJT_SQL_PATH:-}" "${CJT_TASKS_DB_PATH:-}"
      local task_title
      task_title=$(cjt::task_title_from_json "$working_copy" "$actual_index")
      local attempt=0
      local success=0
      local parse_retry=0
      while :; do
        (( attempt++ ))
        if [[ -n "$task_title" ]]; then
          cjt::log "  -> Task ${slug}#${task_num} attempt ${attempt} — '${task_title//'"'/\"}'"
        else
          cjt::log "  -> Task ${slug}#${task_num} attempt ${attempt}"
        fi
        rm -f "$raw_file" "$json_file" 2>/dev/null || true
        if ! cjt::run_codex "$prompt_file" "$raw_file" "refine-${slug}-task-${task_num}"; then
          cjt::warn "Codex invocation failed for ${slug} task ${task_num}; aborting refinement for this task"
          break
        fi
        if cjt::wrap_json_extractor "$raw_file" "$json_file"; then
          cjt::apply_refined_task "$working_copy" "$json_file" "$actual_index"
          if [[ "${CJT_IGNORE_REFINE_STATE:-0}" != "1" ]]; then
            cjt::state_update_refine_progress "$slug" $((idx + 1)) "$pending_total"
          fi
          cjt::sync_refined_task_to_db "$working_copy" "$slug" "$actual_index"
          if [[ -n "$task_title" ]]; then
            cjt::log "    -> Codex refinement applied for ${slug}#${task_num} ('${task_title//'"'/\"}')"
          else
            cjt::log "    -> Codex refinement applied for ${slug}#${task_num}"
          fi
          ((processed_count++))
          success=1
          break
        fi
        if (( parse_retry == 0 )); then
          cat >>"$prompt_file" <<'REM'

## Reminder
- Output a single JSON object conforming to the schema above.
- Do not include explanations, markdown code fences, or commentary outside the JSON.
- If a field is not applicable use an empty array or omit it; do not return prose.
REM
          parse_retry=1
          cjt::warn "Codex produced non-JSON output for ${slug} task ${task_num}; retrying once with stricter reminder."
          continue
        fi
        cjt::warn "Codex did not return usable JSON for ${slug} task ${task_num} after a parse retry; keeping prior content"
        break
      done
      if (( success == 0 )); then
        if [[ -n "$task_title" ]]; then
          cjt::warn "Unable to obtain JSON output for ${slug} task ${task_num} ('${task_title//'"'/\"}') ; keeping prior content"
        else
          cjt::warn "Unable to obtain JSON output for ${slug} task ${task_num}; keeping prior content"
        fi
        story_success=0
        cjt::warn "    ✗ Codex did not return usable JSON for ${slug}#${task_num}"
        break
      fi
    done

    local final_story="$CJT_JSON_REFINED_DIR/${slug}.json"
    mkdir -p "$(dirname "$final_story")"
    cp "$working_copy" "$final_story"
    rm -f "$working_copy" 2>/dev/null || true
    if (( story_success == 1 )); then
      if [[ "${CJT_IGNORE_REFINE_STATE:-0}" != "1" ]]; then
        cjt::state_update_refine_progress "$slug" "$pending_total" "$pending_total"
      fi
      cjt::log "  -> Story ${slug} refined ${processed_count}/${pending_total} tasks"
    fi

    if (( processed_count > 0 )); then
      if [[ -n "${CJT_REFINE_PENDING_TASKS:-}" ]]; then
        local _pending=$((CJT_REFINE_PENDING_TASKS - processed_count))
        (( _pending < 0 )) && _pending=0
        CJT_REFINE_PENDING_TASKS=$_pending
      fi
      if [[ -n "${CJT_REFINE_REFINED_TASKS:-}" ]]; then
        CJT_REFINE_REFINED_TASKS=$((CJT_REFINE_REFINED_TASKS + processed_count))
      fi
      CJT_REFINE_PROCESSED_TASKS=$((CJT_REFINE_PROCESSED_TASKS + processed_count))
      CJT_REFINE_PROCESSED_STORIES=$((CJT_REFINE_PROCESSED_STORIES + 1))
    else
      CJT_REFINE_SKIPPED_STORIES=$((CJT_REFINE_SKIPPED_STORIES + 1))
      if (( pending_total > 0 )); then
        cjt::warn "  -> Story ${slug} left with ${pending_total} pending tasks (Codex failures)."
      fi
    fi
  done

  if [[ "${CJT_IGNORE_REFINE_STATE:-0}" != "1" ]]; then
    if (( using_db )); then
      cjt::state_mark_stage_completed "refine"
    else
      local remaining=0
      local count_helper=""
      count_helper="$(cjt::clone_python_tool "count_story_tasks.py")" || count_helper=""
      if [[ -z "$count_helper" ]]; then
        cjt::warn "Unable to prepare count_story_tasks helper; leaving refine stage pending"
        remaining=1
      else
        for entry in "${story_entries[@]}"; do
          local slug_entry="${entry##*/}"; slug_entry="${slug_entry%.json}"
          local total=""
          total="$(python3 "$count_helper" "$entry")"
          local total_status=$?
          if (( total_status != 0 )); then
            cjt::warn "Unable to count tasks for story ${slug_entry}; leaving refine stage pending"
            remaining=1
            break
          fi
          total=${total//$'\n'/}
          total=${total:-0}
          if [[ "$(cjt::state_get_refine_progress "$slug_entry" "$total")" != "done" ]]; then
            remaining=1
            break
          fi
        done
      fi
      if (( remaining == 0 )); then
        cjt::state_mark_stage_completed "refine"
      fi
    fi
  fi

  if [[ -n "${CJT_REFINE_TOTAL_TASKS:-}" ]]; then
    local processed_tasks="${CJT_REFINE_PROCESSED_TASKS:-0}"
    local refined_total="${CJT_REFINE_REFINED_TASKS:-0}"
    local pending_left="${CJT_REFINE_PENDING_TASKS:-0}"
    local processed_stories="${CJT_REFINE_PROCESSED_STORIES:-0}"
    local skipped_stories="${CJT_REFINE_SKIPPED_STORIES:-0}"
    cjt::log "Refinement summary: tasks processed=${processed_tasks}, total refined=${refined_total}, pending remaining=${pending_left}; stories processed=${processed_stories}, skipped=${skipped_stories}."
  fi
}

cjt::write_refine_task_prompt() {
  local tasks_file="${1:?tasks json required}"
  local task_index="${2:?task index required}"
  local prompt_file="${3:?prompt file required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "write_refine_task_prompt.py")" || return 1
  CJT_PROMPT_TITLE="${CJT_PROJECT_TITLE:-the project}" \
    python3 "$helper_path" \
      "$tasks_file" \
      "$task_index" \
      "$CJT_CONTEXT_FILE" \
      "$prompt_file" \
      "${CJT_SDS_CHUNKS_LIST:-}" \
      "${CJT_PDR_PATH:-}" \
      "${CJT_SQL_PATH:-}" \
      "${CJT_TASKS_DB_PATH:-}"
}


cjt::sync_refined_task_to_db() {
  local story_json="${1:?refined story json required}"
  local slug="${2:?story slug required}"
  local task_index="${3:?task index required}"
  if [[ "${CJT_SYNC_DB:-0}" != "1" ]]; then
    return
  fi
  if [[ "${CJT_DRY_RUN:-0}" == "1" ]]; then
    return
  fi
  if [[ -z "${CJT_TASKS_DB_PATH:-}" ]]; then
    cjt::warn "CJT_SYNC_DB is enabled but CJT_TASKS_DB_PATH is not set; skipping DB update for ${slug}"
    return
  fi
  if [[ ! -f "${CJT_TASKS_DB_PATH}" ]]; then
    cjt::warn "Tasks database not found at ${CJT_TASKS_DB_PATH}; skipping DB update for ${slug}"
    return
  fi
  if ! python3 "$CJT_ROOT_DIR/src/lib/create-jira-tasks/update_task_db.py" \
      "${CJT_TASKS_DB_PATH}" "${story_json}" "${slug}" "${task_index}"; then
    cjt::warn "Failed to update tasks database for ${slug} (index ${task_index})"
  fi
}

cjt::apply_refined_task() {
  local working_json="${1:?working story json required}"
  local refined_json="${2:?refined task json required}"
  local task_index="${3:?task index required}"
  local helper_path
  helper_path="$(cjt::clone_python_tool "apply_refined_task.py")" || return 1
  python3 "$helper_path" "$working_json" "$refined_json" "$task_index"
}

cjt::build_payload() {
  local out_file="$CJT_JSON_DIR/tasks_payload.json"
  python3 "$CJT_ROOT_DIR/src/lib/create-jira-tasks/to_payload.py" \
    "$CJT_JSON_DIR/epics.json" \
    "$CJT_JSON_STORIES_DIR" \
    "$CJT_JSON_TASKS_DIR" \
    "$CJT_JSON_REFINED_DIR" \
    "$out_file"
  cjt::log "Combined tasks payload → ${out_file}"
}

cjt::update_database() {
  if [[ "${CJT_INCREMENTAL_DB:-0}" == "1" ]]; then
    cjt::log "tasks.db already synchronized incrementally; skipping bulk rebuild"
    return
  fi
  local payload="$CJT_JSON_DIR/tasks_payload.json"
  [[ -f "$payload" ]] || cjt::die "Tasks payload missing: ${payload}"

  local tasks_dir="$CJT_PLAN_DIR/tasks"
  mkdir -p "$tasks_dir"
  local db_path="$tasks_dir/tasks.db"
  local parsed_json="$tasks_dir/tasks_generated.json"
  cp "$payload" "$parsed_json"

  local force_flag=0
  [[ "$CJT_FORCE" == "1" ]] && force_flag=1

  cjt::log "Updating tasks SQLite database (force=${force_flag})"
  python3 "$CJT_ROOT_DIR/src/lib/create-jira-tasks/to_sqlite.py" \
    "$parsed_json" "$db_path" "$force_flag"
  cjt::log "tasks.db updated at ${db_path}"
}

cjt::run_pipeline() {
  cjt::prepare_inputs
  cjt::generate_epics
  cjt::generate_stories
  cjt::generate_tasks
  cjt::build_payload
  cjt::update_database
}

return 0
