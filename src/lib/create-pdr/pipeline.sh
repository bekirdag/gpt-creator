#!/usr/bin/env bash
# shellcheck shell=bash
# create-pdr pipeline helpers

if [[ -n "${GC_LIB_CREATE_PDR_PIPELINE_SH:-}" ]]; then
  return 0
fi
GC_LIB_CREATE_PDR_PIPELINE_SH=1

set -o errtrace

cpdr::log()  { printf '\033[36m[create-pdr]\033[0m %s\n' "$*"; }
cpdr::warn() { printf '\033[33m[create-pdr][WARN]\033[0m %s\n' "$*"; }
cpdr::err()  { printf '\033[31m[create-pdr][ERROR]\033[0m %s\n' "$*" >&2; }
cpdr::die()  { cpdr::err "$*"; exit 1; }

cpdr::abs_path() {
  local path="${1:-}"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$path"
  else
    python3 - <<'PY' "$path"
import pathlib
import sys

target = pathlib.Path(sys.argv[1] or '.')
print(target.expanduser().resolve())
PY
  fi
}

cpdr::slugify() {
  local value="${1:-}"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  value="$(printf '%s' "$value" | tr -cs 'a-z0-9' '-')"
  value="$(printf '%s' "$value" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${value:-section}"
}

cpdr::codex_has_subcommand() {
  local subcmd="$1"
  if ! command -v "$CPDR_CODEX_CMD" >/dev/null 2>&1; then
    return 1
  fi
  "$CPDR_CODEX_CMD" --help 2>/dev/null | grep -Eqi "(^|[[:space:]/-])${subcmd}([[:space:]/-]|$)" || return 1
}

cpdr::run_codex() {
  local prompt_file="${1:?prompt file required}"
  local output_file="${2:?output file required}"
  local label="${3:-codex}"

  if [[ "$CPDR_DRY_RUN" == "1" ]]; then
    cpdr::warn "[dry-run] Skipping Codex invocation for ${label}"
    printf '{"status": "dry-run", "label": "%s"}\n' "$label" >"$output_file"
    return 0
  fi

  mkdir -p "$(dirname "$output_file")"

  if cpdr::codex_has_subcommand chat; then
    local cmd=("$CPDR_CODEX_CMD" chat --model "$CPDR_MODEL" --prompt-file "$prompt_file" --output "$output_file")
    cpdr::log "Running Codex (${label}) with model ${CPDR_MODEL}"
    if ! "${cmd[@]}"; then
      cpdr::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if cpdr::codex_has_subcommand exec; then
    local args=("$CPDR_CODEX_CMD" exec --model "$CPDR_MODEL" --full-auto --sandbox workspace-write --skip-git-repo-check)
    if [[ -n "${CODEX_PROFILE:-}" ]]; then
      args+=(--profile "$CODEX_PROFILE")
    fi
    if [[ -n "$CPDR_PROJECT_ROOT" ]]; then
      args+=(--cd "$CPDR_PROJECT_ROOT")
    fi
    if [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
      args+=(-c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\"")
    fi
    args+=(--output-last-message "$output_file")
    cpdr::log "Running Codex (${label}) with model ${CPDR_MODEL} via exec"
    if ! "${args[@]}" < "$prompt_file"; then
      cpdr::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if cpdr::codex_has_subcommand generate; then
    local cmd=("$CPDR_CODEX_CMD" generate --model "$CPDR_MODEL" --prompt-file "$prompt_file" --output "$output_file")
    cpdr::log "Running Codex (${label}) with model ${CPDR_MODEL} via generate"
    if ! "${cmd[@]}"; then
      cpdr::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  cpdr::warn "Codex CLI '${CPDR_CODEX_CMD}' is unavailable; writing dry-run marker for ${label}."
  printf '{"status": "codex-missing", "label": "%s"}\n' "$label" >"$output_file"
  return 0
}

cpdr::clone_python_tool() {
  local script_name="${1:?python script name required}"
  local project_root="${2:-${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}}"

  if declare -f gc_clone_python_tool >/dev/null 2>&1; then
    gc_clone_python_tool "$script_name" "$project_root"
    return
  fi

  local cli_root
  if [[ -n "${CPDR_ROOT_DIR:-}" ]]; then
    cli_root="$CPDR_ROOT_DIR"
  else
    cli_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  fi

  local source_path="${cli_root}/scripts/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    cpdr::die "Python helper missing at ${source_path}"
  fi

  local work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  local target_dir="${project_root%/}/${work_dir_name}/shims/python"
  local target_path="${target_dir}/${script_name}"

  if [[ ! -d "$target_dir" ]]; then
    mkdir -p "$target_dir" || cpdr::die "Failed to create ${target_dir}"
  fi

  if [[ ! -f "$target_path" || "$source_path" -nt "$target_path" ]]; then
    cp "$source_path" "$target_path" || cpdr::die "Failed to copy ${script_name} helper"
  fi

  printf '%s\n' "$target_path"
}

cpdr::extract_json() {
  local infile="${1:?input file required}"
  local outfile="${2:?output file required}"
  local helper_path
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  helper_path="$(cpdr::clone_python_tool "extract_json.py" "$project_root")" || return 1
  python3 "$helper_path" "$infile" "$outfile"
}

cpdr::init() {
  CPDR_PROJECT_ROOT="${1:?project root required}"
  CPDR_MODEL="${2:-${CODEX_MODEL:-gpt-5-codex}}"
  CPDR_DRY_RUN="${3:-0}"
  CPDR_FORCE="${4:-0}"

  CPDR_PROJECT_ROOT="$(cpdr::abs_path "$CPDR_PROJECT_ROOT")"
  [[ -d "$CPDR_PROJECT_ROOT" ]] || cpdr::die "Project root not found: $CPDR_PROJECT_ROOT"

  CPDR_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

  source "$CPDR_ROOT_DIR/src/constants.sh"
  source "$CPDR_ROOT_DIR/src/gpt-creator.sh"
  [[ -f "$CPDR_ROOT_DIR/src/lib/path.sh" ]] && source "$CPDR_ROOT_DIR/src/lib/path.sh"

  CPDR_WORK_DIR="$(gc::ensure_workspace "$CPDR_PROJECT_ROOT")"
  CPDR_STAGING_DIR="$CPDR_WORK_DIR/staging"
  CPDR_PLAN_DIR="$CPDR_STAGING_DIR/plan"
  CPDR_PIPELINE_DIR="$CPDR_PLAN_DIR/create-pdr"
  CPDR_PROMPTS_DIR="$CPDR_PIPELINE_DIR/prompts"
  CPDR_OUTPUT_DIR="$CPDR_PIPELINE_DIR/out"
  CPDR_JSON_DIR="$CPDR_PIPELINE_DIR/json"
  CPDR_SECTIONS_DIR="$CPDR_PIPELINE_DIR/sections"
  CPDR_ASSEMBLY_DIR="$CPDR_PLAN_DIR/pdr"
  CPDR_TMP_DIR="$CPDR_PIPELINE_DIR/tmp"

  mkdir -p "$CPDR_PROMPTS_DIR" "$CPDR_OUTPUT_DIR" "$CPDR_JSON_DIR" \
    "$CPDR_SECTIONS_DIR" "$CPDR_ASSEMBLY_DIR" "$CPDR_TMP_DIR"

  CPDR_CODEX_CMD="${CODEX_BIN:-${CODEX_CMD:-codex}}"
  if ! command -v "$CPDR_CODEX_CMD" >/dev/null 2>&1; then
    cpdr::warn "Codex CLI '$CPDR_CODEX_CMD' not found; enabling dry-run mode."
    CPDR_DRY_RUN=1
  fi

  cpdr::locate_rfp
  cpdr::prepare_context
}

cpdr::locate_rfp() {
  local candidates=(
    "$CPDR_STAGING_DIR/rfp.md"
    "$CPDR_STAGING_DIR/docs/rfp.md"
    "$CPDR_STAGING_DIR/docs/rfp.txt"
    "$CPDR_STAGING_DIR/docs/rfp.markdown"
    "$CPDR_STAGING_DIR/inputs/rfp.md"
  )

  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      CPDR_RFP_PATH="$candidate"
      break
    fi
  done

  if [[ -z "${CPDR_RFP_PATH:-}" ]]; then
    CPDR_RFP_PATH="$(find "$CPDR_STAGING_DIR" -maxdepth 3 -type f -iname '*rfp*.md' | head -n1 || true)"
  fi

  if [[ -z "${CPDR_RFP_PATH:-}" || ! -f "$CPDR_RFP_PATH" ]]; then
    cpdr::die "Unable to locate RFP under ${CPDR_STAGING_DIR}. Provide an RFP via 'gpt-creator bootstrap --rfp <file>' or place one at .gpt-creator/staging/docs/rfp.md before rerunning."
  fi

  cpdr::log "Using RFP source → ${CPDR_RFP_PATH}"
}

cpdr::prepare_context() {
  CPDR_CONTEXT_FILE="$CPDR_PIPELINE_DIR/rfp_context.md"
  cp "$CPDR_RFP_PATH" "$CPDR_CONTEXT_FILE"

  local max_lines=2000
  CPDR_CONTEXT_SNIPPET="$CPDR_PIPELINE_DIR/rfp_context_snippet.md"
  if ! head -n "$max_lines" "$CPDR_RFP_PATH" >"$CPDR_CONTEXT_SNIPPET"; then
    cp "$CPDR_RFP_PATH" "$CPDR_CONTEXT_SNIPPET"
  fi
}

cpdr::write_toc_prompt() {
  local prompt_file="${1:?prompt file required}"
  local snippet="${2:?snippet path required}"
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "write_toc_prompt.py" "$project_root")" || return 1
  python3 "$helper_path" "$prompt_file" "$snippet"
}

cpdr::generate_toc() {
  local prompt_file="$CPDR_PROMPTS_DIR/toc.prompt.md"
  local output_file="$CPDR_OUTPUT_DIR/toc.raw.txt"
  local json_file="$CPDR_JSON_DIR/toc.json"

  if [[ -f "$json_file" && "$CPDR_FORCE" != "1" ]]; then
    cpdr::log "Table of contents already exists; skipping Codex call"
    return
  fi

  cpdr::log "Preparing table of contents prompt"
  cpdr::write_toc_prompt "$prompt_file" "$CPDR_CONTEXT_SNIPPET"

  cpdr::log "Requesting table of contents from Codex"
  if cpdr::run_codex "$prompt_file" "$output_file" "pdr-toc"; then
    cpdr::extract_json "$output_file" "$json_file"
  else
    cpdr::die "Codex failed while generating the table of contents"
  fi
}

cpdr::build_manifest() {
  local toc_json="$CPDR_JSON_DIR/toc.json"
  local manifest_json="$CPDR_JSON_DIR/manifest.json"
  local flat_json="$CPDR_JSON_DIR/manifest_flat.json"

  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "build_manifest.py" "$project_root")" || return 1
  python3 "$helper_path" "$toc_json" "$manifest_json" "$flat_json"
}

cpdr::manifest_has_nodes() {
  [[ -f "$CPDR_JSON_DIR/manifest.json" ]] || return 1
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "manifest_has_nodes.py" "$project_root")" || return 1
  python3 "$helper_path" "$CPDR_JSON_DIR/manifest.json"
}

cpdr::manifest_node_json() {
  local slug="${1:?slug required}"
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "manifest_node_json.py" "$project_root")" || return 1
  python3 "$helper_path" "$CPDR_JSON_DIR/manifest.json" "$slug"
}

cpdr::manifest_generation_order() {
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "manifest_generation_order.py" "$project_root")" || return 1
  python3 "$helper_path" "$CPDR_JSON_DIR/manifest.json"
}

cpdr::write_section_prompt() {
  local slug="${1:?slug required}"
  local prompt_file="${2:?prompt file required}"

  local node_json
  node_json="$(cpdr::manifest_node_json "$slug")"

  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "write_section_prompt.py" "$project_root")" || return 1
  python3 "$helper_path" "$node_json" "$CPDR_JSON_DIR/manifest.json" "$CPDR_CONTEXT_SNIPPET" "$prompt_file"
}

cpdr::section_output_path() {
  local slug="${1:?slug required}"
  local node_json
  node_json="$(cpdr::manifest_node_json "$slug")"
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "section_output_path.py" "$project_root")" || return 1
  python3 "$helper_path" "$node_json"
}

cpdr::generate_sections() {
  if ! cpdr::manifest_has_nodes; then
    cpdr::die "No sections found in manifest; cannot generate PDR content."
  fi

  local slug
  while IFS= read -r slug; do
    [[ -n "$slug" ]] || continue
    local filename
    filename="$(cpdr::section_output_path "$slug")"
    local section_path="$CPDR_SECTIONS_DIR/$filename"
    local prompt_path="$CPDR_PROMPTS_DIR/${filename%.md}.prompt.md"
    local raw_output="$CPDR_OUTPUT_DIR/${filename%.md}.raw.md"

    if [[ -f "$section_path" && "$CPDR_FORCE" != "1" ]]; then
      cpdr::log "Section '${slug}' already exists; skipping"
      continue
    fi

    cpdr::log "Preparing section prompt for ${slug}"
    cpdr::write_section_prompt "$slug" "$prompt_path"

    cpdr::log "Generating section content for ${slug}"
    if cpdr::run_codex "$prompt_path" "$raw_output" "pdr-section-${slug}"; then
      if [[ ! -s "$raw_output" ]]; then
        cpdr::die "Codex produced no output for section ${slug}; inspect ${raw_output}"
      fi
      cp "$raw_output" "$section_path"
    else
      cpdr::die "Codex generation failed for section ${slug}; inspect ${raw_output}"
    fi
  done < <(cpdr::manifest_generation_order)
}

cpdr::write_markdown_toc() {
  local toc_json="$CPDR_JSON_DIR/manifest.json"
  local toc_md="$CPDR_ASSEMBLY_DIR/table_of_contents.md"

  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "write_markdown_toc.py" "$project_root")" || return 1
  python3 "$helper_path" "$toc_json" "$toc_md"
}

cpdr::assemble_document() {
  local final_path="$CPDR_ASSEMBLY_DIR/pdr.md"
  local toc_json="$CPDR_JSON_DIR/toc.json"

  cpdr::write_markdown_toc

  local manifest_json="$CPDR_JSON_DIR/manifest.json"
  local sections_dir="$CPDR_SECTIONS_DIR"
  local toc_markdown="$CPDR_ASSEMBLY_DIR/table_of_contents.md"

  local document_title
  document_title=$(python3 - <<'PY' "$toc_json"
import json, sys
from pathlib import Path

toc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(toc.get('document_title') or 'Product Requirements Document')
PY
)

  local tmp_file="${final_path}.tmp"
  : >"$tmp_file"
  {
    printf '# %s\n\n' "$document_title"
    printf '_Generated by gpt-creator create-pdr_\n\n'
  } >>"$tmp_file"

  cat "$toc_markdown" >>"$tmp_file"
  printf '\n' >>"$tmp_file"

  python3 - <<'PY' "$manifest_json" "$sections_dir" "$tmp_file"
import json
import sys
from pathlib import Path

manifest_path, sections_dir, out_file = sys.argv[1:4]
manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
sections_root = Path(sections_dir)
out = Path(out_file)

for node in manifest.get('nodes') or []:
    label = (node.get('label') or '').replace('.', '-')
    slug = node.get('slug') or 'section'
    filename = f"{label}_{slug}.md"
    content_path = sections_root / filename
    if content_path.exists():
        with out.open('a', encoding='utf-8') as fh:
            fh.write(f"<a id=\"{slug}\"></a>\n")
        section_text = content_path.read_text(encoding='utf-8').strip()
        if section_text:
            with out.open('a', encoding='utf-8') as fh:
                fh.write(section_text)
                fh.write('\n\n')
PY

  mv "$tmp_file" "$final_path"
  cpdr::log "PDR assembled → ${final_path}"
}

cpdr::write_review_prompt() {
  local pdr_file="${1:?pdr path required}"
  local prompt_file="${2:?prompt file required}"
  local rfp_excerpt="$CPDR_CONTEXT_SNIPPET"

  mkdir -p "$(dirname "$prompt_file")"
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "write_review_prompt.py" "$project_root")" || return 1
  python3 "$helper_path" "$pdr_file" "$rfp_excerpt" "$prompt_file"
}

cpdr::extract_review_markdown() {
  local input_file="${1:?input file required}"
  local output_file="${2:?output file required}"
  local project_root="${CPDR_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
  local helper_path
  helper_path="$(cpdr::clone_python_tool "extract_review_markdown.py" "$project_root")" || return 1
  python3 "$helper_path" "$input_file" "$output_file"
}

cpdr::review_document() {
  local final_path="$CPDR_ASSEMBLY_DIR/pdr.md"
  if [[ ! -f "$final_path" ]]; then
    cpdr::warn "PDR not found at ${final_path}; skipping review"
    return
  fi

  if [[ "$CPDR_DRY_RUN" == "1" ]]; then
    cpdr::warn "[dry-run] Skipping automated PDR review"
    return
  fi

  local prompt_file="$CPDR_PROMPTS_DIR/review.prompt.md"
  local raw_file="$CPDR_OUTPUT_DIR/review.raw.txt"
  local reviewed_file="$CPDR_TMP_DIR/pdr.reviewed.md"

  cpdr::log "Reviewing assembled PDR for completeness and consistency"
  cpdr::write_review_prompt "$final_path" "$prompt_file"

  if cpdr::run_codex "$prompt_file" "$raw_file" "pdr-review"; then
    cpdr::extract_review_markdown "$raw_file" "$reviewed_file"
    if [[ -s "$reviewed_file" ]]; then
      local backup="${final_path%.md}.initial.md"
      if [[ ! -f "$backup" ]]; then
        cp "$final_path" "$backup"
      fi
      mv "$reviewed_file" "$final_path"
      cpdr::log "PDR review completed → ${final_path} (backup saved at ${backup})"
    else
      cpdr::warn "Review output was empty; keeping original PDR"
    fi
  else
    cpdr::warn "Codex review step failed; retaining original PDR"
  fi
}

cpdr::run_pipeline() {
  cpdr::generate_toc
  cpdr::build_manifest
  cpdr::generate_sections
  cpdr::assemble_document
  cpdr::review_document
  gc::refresh_doc_catalog "$CPDR_PROJECT_ROOT" "$CPDR_STAGING_DIR"
}

return 0
