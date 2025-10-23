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

cpdr::extract_json() {
  local infile="${1:?input file required}"
  local outfile="${2:?output file required}"
  python3 - "$infile" "$outfile" <<'PY'
import json
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = raw_path.read_text(encoding='utf-8')

stack = []
start = None
for idx, ch in enumerate(text):
    if ch in '{[':
        if not stack:
            start = idx
        stack.append(ch)
    elif ch in '}]':
        if stack:
            stack.pop()
            if not stack and start is not None:
                snippet = text[start:idx+1]
                try:
                    data = json.loads(snippet)
                except json.JSONDecodeError:
                    continue
                out_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
                sys.exit(0)

raise SystemExit("Failed to locate JSON payload in Codex output")
PY
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

  mkdir -p "$(dirname "$prompt_file")"
  {
    cat <<'EOF'
You are Codex, drafting a Product Requirements Document (PDR) from a Request for Proposal (RFP).

Follow this process:
1. Study the RFP excerpt.
2. Identify the highest-level themes first (vision, goals, product scope, user segments, success metrics, operating constraints).
3. Break each theme into progressively more detailed sections and subsections, going from high-level strategy down to detailed requirements, policies, integrations, and validation.
4. Propose a complete table of contents for the PDR before any narrative is written.

Output strict JSON matching this schema:
{
  "document_title": "string",
  "sections": [
    {
      "title": "Top level heading",
      "summary": "1-3 sentence overview of what belongs in this section",
      "subsections": [
        {
          "title": "Sub heading",
          "summary": "Short summary",
          "subsections": [
            {
              "title": "Nested heading",
              "summary": "Short summary"
            }
          ]
        }
      ]
    }
  ]
}

Rules:
- Order sections from highest-level concepts down to implementation and validation details.
- Provide at least three top-level sections.
- Each subsection list may be empty, but include the key subsections necessary to cover the RFP requirements.
- Do not include prose outside the JSON response.

## RFP Excerpt
EOF
    cat "$snippet"
    cat <<'EOF'

## End RFP Excerpt
EOF
  } >"$prompt_file"
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

  python3 - "$toc_json" "$manifest_json" "$flat_json" <<'PY'
import json
import re
import sys
from pathlib import Path

toc_path, manifest_path, flat_path = sys.argv[1:4]
toc = json.loads(Path(toc_path).read_text(encoding='utf-8'))
sections = toc.get('sections') or []

slug_re = re.compile(r'[^a-z0-9]+')

def slugify(text, seen):
    base = slug_re.sub('-', (text or '').lower()).strip('-') or 'section'
    slug = base
    idx = 2
    while slug in seen:
        slug = f"{base}-{idx}"
        idx += 1
    seen.add(slug)
    return slug

nodes = []
seen = set()

def walk(node, path, parent):
    title = (node.get('title') or '').strip()
    summary = (node.get('summary') or '').strip()
    slug = slugify(title or 'section', seen)
    label = '.'.join(str(i + 1) for i in path)
    breadcrumbs = []
    parent_slug = None
    parent_label = None
    if parent is not None:
        breadcrumbs = parent['breadcrumbs'] + [parent['title']]
        parent_slug = parent['slug']
        parent_label = parent['label']
    entry = {
        'slug': slug,
        'title': title,
        'summary': summary,
        'label': label,
        'level': len(path),
        'path': path,
        'parent_slug': parent_slug,
        'parent_label': parent_label,
        'breadcrumbs': breadcrumbs,
        'children_titles': [ (child.get('title') or '').strip() for child in (node.get('subsections') or []) ],
    }
    nodes.append(entry)
    for idx, child in enumerate(node.get('subsections') or []):
        walk(child, path + [idx], entry)

for idx, section in enumerate(sections):
    walk(section, [idx], None)

nodes_by_path = sorted(nodes, key=lambda item: item['path'])
nodes_generation_order = sorted(nodes, key=lambda item: (item['level'], item['path']))

manifest = {
    'toc': toc,
    'nodes': nodes_by_path,
    'generation_order': [item['slug'] for item in nodes_generation_order],
}

Path(manifest_path).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
Path(flat_path).write_text(json.dumps(nodes_by_path, indent=2) + '\n', encoding='utf-8')
PY
}

cpdr::manifest_has_nodes() {
  [[ -f "$CPDR_JSON_DIR/manifest.json" ]] || return 1
  python3 - "$CPDR_JSON_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
nodes = data.get('nodes') or []
sys.exit(0 if nodes else 1)
PY
}

cpdr::manifest_node_json() {
  local slug="${1:?slug required}"
  python3 - "$CPDR_JSON_DIR/manifest.json" "$slug" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
slug = sys.argv[2]
for node in manifest.get('nodes') or []:
    if node.get('slug') == slug:
        print(json.dumps(node))
        sys.exit(0)
raise SystemExit(f"Node not found for slug: {slug}")
PY
}

cpdr::manifest_generation_order() {
  python3 - "$CPDR_JSON_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
for slug in manifest.get('generation_order') or []:
    print(slug)
PY
}

cpdr::write_section_prompt() {
  local slug="${1:?slug required}"
  local prompt_file="${2:?prompt file required}"

  local node_json
  node_json="$(cpdr::manifest_node_json "$slug")"

  python3 - <<'PY' "$node_json" "$CPDR_JSON_DIR/manifest.json" "$CPDR_CONTEXT_SNIPPET" "$prompt_file"
import json
import sys
from pathlib import Path

node = json.loads(sys.argv[1])
manifest = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
snippet = Path(sys.argv[3]).read_text(encoding='utf-8')
prompt_path = Path(sys.argv[4])

slug = node['slug']
title = node.get('title') or ''
summary = node.get('summary') or ''
label = node.get('label') or ''
level = int(node.get('level') or 1)
breadcrumbs = node.get('breadcrumbs') or []
children = node.get('children_titles') or []
heading_level = max(2, min(level + 1, 6))
heading_token = '#' * heading_level

parent = None
parent_slug = node.get('parent_slug')
if parent_slug:
    for candidate in manifest.get('nodes') or []:
        if candidate.get('slug') == parent_slug:
            parent = candidate
            break

lines = []
lines.append("You are Codex, authoring a Product Requirements Document (PDR) based on the provided RFP excerpt.")
lines.append("")
lines.append("## Section metadata")
lines.append(f"- Slug: {slug}")
lines.append(f"- Outline label: {label}")
lines.append(f"- Heading depth: {level}")
lines.append(f"- Markdown heading token: {heading_token}")
if breadcrumbs:
    lines.append(f"- Parent chain: {' > '.join(breadcrumbs)}")
lines.append(f"- Title: {title}")
if summary:
    lines.append(f"- Outline summary: {summary}")
if parent and parent.get('summary'):
    lines.append(f"- Parent summary: {parent['summary']}")
if children:
    lines.append("- Planned child headings:")
    for child in children:
        if child:
            lines.append(f"  * {child}")

lines.append("")
lines.append("## RFP excerpt (truncated)")
lines.append(snippet)
lines.append("")
lines.append("## Writing instructions")
lines.append(f"1. Begin with the heading `{heading_token} {title} {{#{slug}}}` (you may adjust the wording, but keep the heading level and anchor).")
lines.append("2. Summarize the section at the appropriate fidelity: higher levels focus on narrative, scope, and success criteria; deeper levels provide concrete requirements, data flows, policies, and validation steps.")
lines.append("3. Align content strictly with the RFP while resolving gaps with reasonable assumptions explicitly marked as such.")
lines.append("4. Use ordered lists, bullet points, and sub-subheadings sparingly to improve structure, but do not create headings beyond the assigned level for this pass.")
lines.append("5. Reference downstream subsections (if any) but leave their detailed execution to later iterations.")
lines.append("6. Close with a short 'Key Considerations' bullet list anchoring the most important commitments for this section.")
lines.append("")
lines.append("## Output requirements")
lines.append("Return Markdown only for this section. Do not include front-matter, global TOC, or commentary outside the section.")

prompt_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY
}

cpdr::section_output_path() {
  local slug="${1:?slug required}"
  local node_json
  node_json="$(cpdr::manifest_node_json "$slug")"
  python3 - <<'PY' "$node_json"
import json
import sys

node = json.loads(sys.argv[1])
label = (node.get('label') or '').replace('.', '-')
slug = node.get('slug') or 'section'
print(f"{label}_{slug}.md")
PY
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

  python3 - "$toc_json" "$toc_md" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
out_path = Path(sys.argv[2])

def walk(nodes, depth):
    lines = []
    for node in nodes:
        title = node.get('title') or ''
        label = node.get('label') or ''
        indent = '  ' * (node.get('level', depth) - 1)
        display = f"{label} {title}".strip()
        slug = node.get('slug') or ''
        if slug:
            lines.append(f"{indent}- [{display}](#{slug})")
        else:
            lines.append(f"{indent}- {display}")
    return '\n'.join(lines)

lines = []
lines.append('## Table of Contents')
lines.append('')
lines.append(walk(manifest.get('nodes') or [], 1))
lines.append('')
out_path.write_text('\n'.join(lines), encoding='utf-8')
PY
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
  {
    cat <<'PROMPT'
You are a principal product strategist performing a final quality review of a Product Requirements Document (PDR).

Goals:
- Confirm the PDR is comprehensive enough for engineering, design, compliance, and go-to-market teams to build and launch the product described in the RFP.
- Ensure every section of the PDR is internally consistent, aligned with neighbouring sections, and free of contradictions.
- Identify gaps or ambiguous areas that would block execution, and resolve them by updating the PDR content.
- Guarantee terminology, roles, success metrics, and scope stay synchronized across all sections.

Method:
1. Read the RFP excerpt to anchor requirements.
2. Audit the current PDR, checking that vision, scope, user journeys, functional specs, non-functional requirements, compliance, analytics, rollout, and success metrics interlock without conflicts.
3. Revise the PDR directly so it is self-consistent, implementation-ready, and efficient—no redundant or conflicting guidance.
4. Output the improved PDR in Markdown. Do not include commentary, checklists, or code fences—return the updated document only.

## RFP Excerpt
PROMPT
    cat "$rfp_excerpt"
    cat <<'PROMPT'

## Current PDR
PROMPT
    cat "$pdr_file"
    cat <<'PROMPT'

## End PDR
PROMPT
  } >"$prompt_file"
}

cpdr::extract_review_markdown() {
  local input_file="${1:?input file required}"
  local output_file="${2:?output file required}"
  python3 - "$input_file" "$output_file" <<'PY'
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = raw_path.read_text(encoding='utf-8').strip()

if text.startswith('```'):
    fence = text.splitlines()
    if fence and fence[0].startswith('```'):
        fence = fence[1:]
        if fence and fence[-1].startswith('```'):
            fence = fence[:-1]
        text = '\n'.join(fence).strip()

out_path.write_text(text + ('\n' if not text.endswith('\n') else ''), encoding='utf-8')
PY
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
