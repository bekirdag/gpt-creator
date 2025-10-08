#!/usr/bin/env bash
# shellcheck shell=bash
# create-sds pipeline helpers
 
if [[ -n "${GC_LIB_CREATE_SDS_PIPELINE_SH:-}" ]]; then
  return 0
fi
GC_LIB_CREATE_SDS_PIPELINE_SH=1

set -o errtrace

csds::log()  { printf '\033[36m[create-sds]\033[0m %s\n' "$*"; }
csds::warn() { printf '\033[33m[create-sds][WARN]\033[0m %s\n' "$*"; }
csds::err()  { printf '\033[31m[create-sds][ERROR]\033[0m %s\n' "$*" >&2; }
csds::die()  { csds::err "$*"; exit 1; }

csds::abs_path() {
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

csds::slugify() {
  local value="${1:-}"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  value="$(printf '%s' "$value" | tr -cs 'a-z0-9' '-')"
  value="$(printf '%s' "$value" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${value:-section}"
}

csds::codex_has_subcommand() {
  local subcmd="$1"
  if ! command -v "$CSDS_CODEX_CMD" >/dev/null 2>&1; then
    return 1
  fi
  "$CSDS_CODEX_CMD" --help 2>/dev/null | grep -Eqi "(^|[[:space:]/-])${subcmd}([[:space:]/-]|$)" || return 1
}

csds::run_codex() {
  local prompt_file="${1:?prompt file required}"
  local output_file="${2:?output file required}"
  local label="${3:-codex}"

  if [[ "$CSDS_DRY_RUN" == "1" ]]; then
    csds::warn "[dry-run] Skipping Codex invocation for ${label}"
    printf '{"status": "dry-run", "label": "%s"}\n' "$label" >"$output_file"
    return 0
  fi

  mkdir -p "$(dirname "$output_file")"

  if csds::codex_has_subcommand chat; then
    local cmd=("$CSDS_CODEX_CMD" chat --model "$CSDS_MODEL" --prompt-file "$prompt_file" --output "$output_file")
    csds::log "Running Codex (${label}) with model ${CSDS_MODEL}"
    if ! "${cmd[@]}"; then
      csds::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if csds::codex_has_subcommand exec; then
    local args=("$CSDS_CODEX_CMD" exec --model "$CSDS_MODEL" --full-auto --sandbox workspace-write --skip-git-repo-check)
    if [[ -n "${CODEX_PROFILE:-}" ]]; then
      args+=(--profile "$CODEX_PROFILE")
    fi
    if [[ -n "$CSDS_PROJECT_ROOT" ]]; then
      args+=(--cd "$CSDS_PROJECT_ROOT")
    fi
    if [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
      args+=(-c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\"")
    fi
    args+=(--output-last-message "$output_file")
    csds::log "Running Codex (${label}) with model ${CSDS_MODEL} via exec"
    if ! "${args[@]}" < "$prompt_file"; then
      csds::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if csds::codex_has_subcommand generate; then
    local cmd=("$CSDS_CODEX_CMD" generate --model "$CSDS_MODEL" --prompt-file "$prompt_file" --output "$output_file")
    csds::log "Running Codex (${label}) with model ${CSDS_MODEL} via generate"
    if ! "${cmd[@]}"; then
      csds::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  csds::warn "Codex CLI '${CSDS_CODEX_CMD}' is unavailable; writing dry-run marker for ${label}."
  printf '{"status": "codex-missing", "label": "%s"}\n' "$label" >"$output_file"
  return 0
}

csds::extract_json() {
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

csds::init() {
  CSDS_PROJECT_ROOT="${1:?project root required}"
  CSDS_MODEL="${2:-${CODEX_MODEL:-gpt-5-codex}}"
  CSDS_DRY_RUN="${3:-0}"
  CSDS_FORCE="${4:-0}"

  CSDS_PROJECT_ROOT="$(csds::abs_path "$CSDS_PROJECT_ROOT")"
  [[ -d "$CSDS_PROJECT_ROOT" ]] || csds::die "Project root not found: $CSDS_PROJECT_ROOT"

  CSDS_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

  source "$CSDS_ROOT_DIR/src/constants.sh"
  source "$CSDS_ROOT_DIR/src/gpt-creator.sh"
  [[ -f "$CSDS_ROOT_DIR/src/lib/path.sh" ]] && source "$CSDS_ROOT_DIR/src/lib/path.sh"

  CSDS_WORK_DIR="$(gc::ensure_workspace "$CSDS_PROJECT_ROOT")"
  CSDS_STAGING_DIR="$CSDS_WORK_DIR/staging"
  CSDS_PLAN_DIR="$CSDS_STAGING_DIR/plan"
  CSDS_PIPELINE_DIR="$CSDS_PLAN_DIR/create-sds"
  CSDS_PROMPTS_DIR="$CSDS_PIPELINE_DIR/prompts"
  CSDS_OUTPUT_DIR="$CSDS_PIPELINE_DIR/out"
  CSDS_JSON_DIR="$CSDS_PIPELINE_DIR/json"
  CSDS_SECTIONS_DIR="$CSDS_PIPELINE_DIR/sections"
  CSDS_ASSEMBLY_DIR="$CSDS_PLAN_DIR/sds"
  CSDS_TMP_DIR="$CSDS_PIPELINE_DIR/tmp"

  mkdir -p "$CSDS_PROMPTS_DIR" "$CSDS_OUTPUT_DIR" "$CSDS_JSON_DIR" \
    "$CSDS_SECTIONS_DIR" "$CSDS_ASSEMBLY_DIR" "$CSDS_TMP_DIR"

  CSDS_CODEX_CMD="${CODEX_BIN:-${CODEX_CMD:-codex}}"
  if ! command -v "$CSDS_CODEX_CMD" >/dev/null 2>&1; then
    csds::warn "Codex CLI '$CSDS_CODEX_CMD' not found; enabling dry-run mode."
    CSDS_DRY_RUN=1
  fi

  csds::locate_pdr
  csds::prepare_context
}

csds::locate_pdr() {
  local candidates=(
    "$CSDS_STAGING_DIR/pdr.md"
    "$CSDS_STAGING_DIR/docs/pdr.md"
    "$CSDS_STAGING_DIR/docs/pdr.markdown"
    "$CSDS_STAGING_DIR/docs/pdr.txt"
    "$CSDS_STAGING_DIR/plan/pdr/pdr.md"
  )

  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      CSDS_PDR_PATH="$candidate"
      break
    fi
  done

  if [[ -z "${CSDS_PDR_PATH:-}" ]]; then
    CSDS_PDR_PATH="$(find "$CSDS_STAGING_DIR" -maxdepth 3 -type f -iname '*pdr*.md' | head -n1 || true)"
  fi

  [[ -n "${CSDS_PDR_PATH:-}" && -f "$CSDS_PDR_PATH" ]] || csds::die "Unable to locate staged PDR document under ${CSDS_STAGING_DIR}. Run 'gpt-creator create-pdr' or add the PDR to staging."

  csds::log "Using PDR source → ${CSDS_PDR_PATH}"
}

csds::prepare_context() {
  CSDS_CONTEXT_FILE="$CSDS_PIPELINE_DIR/pdr_context.md"
  cp "$CSDS_PDR_PATH" "$CSDS_CONTEXT_FILE"

  local max_lines=2000
  CSDS_CONTEXT_SNIPPET="$CSDS_PIPELINE_DIR/pdr_context_snippet.md"
  if ! head -n "$max_lines" "$CSDS_PDR_PATH" >"$CSDS_CONTEXT_SNIPPET"; then
    cp "$CSDS_PDR_PATH" "$CSDS_CONTEXT_SNIPPET"
  fi
}

csds::write_toc_prompt() {
  local prompt_file="${1:?prompt file required}"
  local snippet="${2:?snippet path required}"

  mkdir -p "$(dirname "$prompt_file")"
  {
    cat <<'CSDS_TOC'
You are Codex, acting as the lead systems architect. Draft a System Design Specification (SDS) that realises the Product Requirements Document (PDR) provided below.

Process:
1. Read the PDR excerpt to understand product goals and constraints.
2. Identify architecture domains first: platform overview, runtime topology, service/module boundaries, data flows, integration points, and operational concerns.
3. Decompose each domain into progressively detailed sections and subsections covering diagrams, contracts, databases, APIs, deployment, observability, security, scalability, and runbooks.
4. Before writing narrative content, output a complete SDS table of contents ordered from strategic architecture down to granular implementation details.

Respond with strict JSON using this schema:
{
  "document_title": "System Design Specification",
  "sections": [
    {
      "title": "Top-level heading",
      "summary": "1-3 sentence synopsis of scope",
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
- Order sections top-down: architecture overview → component design → data & storage → integration & interface contracts → infrastructure & operations → testing, observability, and risk management.
- Provide at least five top-level sections spanning architecture, data, interfaces, infrastructure, and quality/operability.
- Populate subsection arrays whenever deeper guidance is needed; leave empty only when no additional breakdown is required.
- Output JSON only.

## PDR Excerpt
CSDS_TOC
    cat "$snippet"
    cat <<'CSDS_TOC'

## End PDR Excerpt
CSDS_TOC
  } >"$prompt_file"
}

csds::generate_toc() {
  local prompt_file="$CSDS_PROMPTS_DIR/toc.prompt.md"
  local output_file="$CSDS_OUTPUT_DIR/toc.raw.txt"
  local json_file="$CSDS_JSON_DIR/toc.json"

  if [[ -f "$json_file" && "$CSDS_FORCE" != "1" ]]; then
  csds::log "SDS table of contents already exists; skipping Codex call"
    return
  fi

  csds::log "Preparing SDS table of contents prompt"
  csds::write_toc_prompt "$prompt_file" "$CSDS_CONTEXT_SNIPPET"

  csds::log "Requesting SDS table of contents from Codex"
  if csds::run_codex "$prompt_file" "$output_file" "sds-toc"; then
    csds::extract_json "$output_file" "$json_file"
  else
    csds::die "Codex failed while generating the SDS table of contents"
  fi
}

csds::build_manifest() {
  local toc_json="$CSDS_JSON_DIR/toc.json"
  local manifest_json="$CSDS_JSON_DIR/manifest.json"
  local flat_json="$CSDS_JSON_DIR/manifest_flat.json"

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

csds::manifest_has_nodes() {
  [[ -f "$CSDS_JSON_DIR/manifest.json" ]] || return 1
  python3 - "$CSDS_JSON_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
nodes = data.get('nodes') or []
sys.exit(0 if nodes else 1)
PY
}

csds::manifest_node_json() {
  local slug="${1:?slug required}"
  python3 - "$CSDS_JSON_DIR/manifest.json" "$slug" <<'PY'
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

csds::manifest_generation_order() {
  python3 - "$CSDS_JSON_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
for slug in manifest.get('generation_order') or []:
    print(slug)
PY
}

csds::write_section_prompt() {
  local slug="${1:?slug required}"
  local prompt_file="${2:?prompt file required}"

  local node_json
  node_json="$(csds::manifest_node_json "$slug")"

  python3 - <<'PY' "$node_json" "$CSDS_JSON_DIR/manifest.json" "$CSDS_CONTEXT_SNIPPET" "$prompt_file"
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
lines.append("You are Codex, documenting a System Design Specification (SDS) based on the Product Requirements Document excerpt below.")
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
lines.append("## PDR excerpt (truncated)")
lines.append(snippet)
lines.append("")
lines.append("## Writing instructions")
lines.append(f"1. Begin with the heading `{heading_token} {title} {{#{slug}}}` (adjust wording if needed, but keep the level and anchor).")
lines.append("2. Articulate the architectural intent for this section, then specify components, interactions, and data contracts in increasing detail.")
lines.append("3. Map requirements from the PDR into concrete technical decisions: technologies, responsibilities, data models, interfaces, and operational policies.")
lines.append("4. If diagrams are referenced, describe their structure textually (component, sequence, deployment) so engineers can implement them.")
lines.append("5. Cover scalability, reliability, security, observability, and DevOps implications relevant to this scope.")
lines.append("6. Call out assumptions explicitly and flag open questions or risks.")
lines.append("7. Close with bullet lists for 'Open Questions & Risks' and 'Verification Strategy'.")
lines.append("")
lines.append("## Output requirements")
lines.append("Return Markdown only for this section. Do not include front-matter, global TOC, or commentary outside the section.")

prompt_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY
}

csds::section_output_path() {
  local slug="${1:?slug required}"
  local node_json
  node_json="$(csds::manifest_node_json "$slug")"
  python3 - <<'PY' "$node_json"
import json
import sys

node = json.loads(sys.argv[1])
label = (node.get('label') or '').replace('.', '-')
slug = node.get('slug') or 'section'
print(f"{label}_{slug}.md")
PY
}

csds::generate_sections() {
  if ! csds::manifest_has_nodes; then
    csds::die "No sections found in manifest; cannot generate SDS content."
  fi

  local slug
  while IFS= read -r slug; do
    [[ -n "$slug" ]] || continue
    local filename
    filename="$(csds::section_output_path "$slug")"
    local section_path="$CSDS_SECTIONS_DIR/$filename"
    local prompt_path="$CSDS_PROMPTS_DIR/${filename%.md}.prompt.md"
    local raw_output="$CSDS_OUTPUT_DIR/${filename%.md}.raw.md"

    if [[ -f "$section_path" && "$CSDS_FORCE" != "1" ]]; then
      csds::log "Section '${slug}' already exists; skipping"
      continue
    fi

    csds::log "Preparing section prompt for ${slug}"
    csds::write_section_prompt "$slug" "$prompt_path"

    csds::log "Generating section content for ${slug}"
    if csds::run_codex "$prompt_path" "$raw_output" "sds-section-${slug}"; then
      if [[ ! -s "$raw_output" ]]; then
        csds::die "Codex produced no output for section ${slug}; inspect ${raw_output}"
      fi
      cp "$raw_output" "$section_path"
    else
      csds::die "Codex generation failed for section ${slug}; inspect ${raw_output}"
    fi
  done < <(csds::manifest_generation_order)
}

csds::write_markdown_toc() {
  local toc_json="$CSDS_JSON_DIR/manifest.json"
  local toc_md="$CSDS_ASSEMBLY_DIR/table_of_contents.md"

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

csds::assemble_document() {
  local final_path="$CSDS_ASSEMBLY_DIR/sds.md"
  local toc_json="$CSDS_JSON_DIR/toc.json"

  csds::write_markdown_toc

  local manifest_json="$CSDS_JSON_DIR/manifest.json"
  local sections_dir="$CSDS_SECTIONS_DIR"
  local toc_markdown="$CSDS_ASSEMBLY_DIR/table_of_contents.md"

  local document_title
  document_title=$(python3 - <<'PY' "$toc_json"
import json, sys
from pathlib import Path

toc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(toc.get('document_title') or 'System Design Specification')
PY
)

  local tmp_file="${final_path}.tmp"
  : >"$tmp_file"
  {
    printf '# %s\n\n' "$document_title"
    printf '_Generated by gpt-creator create-sds_\n\n'
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
  csds::log "SDS assembled → ${final_path}"
}

csds::write_review_prompt() {
  local sds_file="${1:?sds path required}"
  local prompt_file="${2:?prompt file required}"
  local pdr_excerpt="$CSDS_CONTEXT_SNIPPET"

  mkdir -p "$(dirname "$prompt_file")"
  {
    cat <<'PROMPT'
You are a lead systems architect performing a final quality review of a System Design Specification (SDS).

Goals:
- Confirm the SDS is complete and prescriptive enough for engineering teams to build the entire platform described in the PDR.
- Ensure every section (architecture, data, integrations, infra, reliability, security, compliance, observability, rollout) is internally consistent and aligned with the others.
- Detect gaps, contradictions, or missing implementation detail and resolve them by updating the SDS content.
- Keep terminology, component interfaces, data contracts, and operational considerations synchronized throughout the document.

Method:
1. Study the PDR excerpt to anchor product requirements.
2. Audit the SDS end-to-end, validating that architecture decisions satisfy the PDR while staying coherent.
3. Rewrite or expand the SDS so it is self-consistent, implementation-ready, and efficient—no redundant or conflicting guidance.
4. Output the improved SDS in Markdown only. Do not include commentary, checklists, or code fences.

## PDR Excerpt
PROMPT
    cat "$pdr_excerpt"
    cat <<'PROMPT'

## Current SDS
PROMPT
    cat "$sds_file"
    cat <<'PROMPT'

## End SDS
PROMPT
  } >"$prompt_file"
}

csds::extract_review_markdown() {
  local input_file="${1:?input file required}"
  local output_file="${2:?output file required}"
  python3 - "$input_file" "$output_file" <<'PY'
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = raw_path.read_text(encoding='utf-8').strip()

if text.startswith('```'):
    lines = text.splitlines()
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        text = '\n'.join(lines).strip()

out_path.write_text(text + ('\n' if not text.endswith('\n') else ''), encoding='utf-8')
PY
}

csds::review_document() {
  local final_path="$CSDS_ASSEMBLY_DIR/sds.md"
  if [[ ! -f "$final_path" ]]; then
    csds::warn "SDS not found at ${final_path}; skipping review"
    return
  fi

  if [[ "$CSDS_DRY_RUN" == "1" ]]; then
    csds::warn "[dry-run] Skipping automated SDS review"
    return
  fi

  local prompt_file="$CSDS_PROMPTS_DIR/review.prompt.md"
  local raw_file="$CSDS_OUTPUT_DIR/review.raw.txt"
  local reviewed_file="$CSDS_TMP_DIR/sds.reviewed.md"

  csds::log "Reviewing assembled SDS for completeness and consistency"
  csds::write_review_prompt "$final_path" "$prompt_file"

  if csds::run_codex "$prompt_file" "$raw_file" "sds-review"; then
    csds::extract_review_markdown "$raw_file" "$reviewed_file"
    if [[ -s "$reviewed_file" ]]; then
      local backup="${final_path%.md}.initial.md"
      if [[ ! -f "$backup" ]]; then
        cp "$final_path" "$backup"
      fi
      mv "$reviewed_file" "$final_path"
      csds::log "SDS review completed → ${final_path} (backup saved at ${backup})"
    else
      csds::warn "Review output was empty; keeping original SDS"
    fi
  else
    csds::warn "Codex review step failed; retaining original SDS"
  fi
}

csds::run_pipeline() {
  csds::generate_toc
  csds::build_manifest
  csds::generate_sections
  csds::assemble_document
  csds::review_document
}

return 0
