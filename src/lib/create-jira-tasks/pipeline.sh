#!/usr/bin/env bash
# shellcheck shell=bash
# create-jira-tasks pipeline helpers

if [[ -n "${GC_LIB_CREATE_JIRA_TASKS_PIPELINE_SH:-}" ]]; then
  return 0
fi
GC_LIB_CREATE_JIRA_TASKS_PIPELINE_SH=1

set -o errtrace

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
  python3 - "$CJT_STATE_FILE" "$stage" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
stage = sys.argv[2]
data = json.loads(path.read_text(encoding='utf-8'))
status = (data.get(stage) or {}).get('status')
sys.exit(0 if status == 'completed' else 1)
PY
}

cjt::state_mark_stage_completed() {
  local stage="$1"
  python3 - "$CJT_STATE_FILE" "$stage" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
stage = sys.argv[2]
data = json.loads(path.read_text(encoding='utf-8'))
section = data.setdefault(stage, {})
section['status'] = 'completed'
path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
PY
}

cjt::state_mark_stage_pending() {
  local stage="$1"
  python3 - "$CJT_STATE_FILE" "$stage" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
stage = sys.argv[2]
data = json.loads(path.read_text(encoding='utf-8'))
section = data.setdefault(stage, {})
if section.get('status') != 'pending':
    section['status'] = 'pending'
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
PY
}

cjt::state_story_is_completed() {
  local section="$1" slug="$2" file_path="$3"
  python3 - "$CJT_STATE_FILE" "$section" "$slug" "$file_path" <<'PY'
import json, sys
from pathlib import Path

state_path = Path(sys.argv[1])
section = sys.argv[2]
slug = sys.argv[3]
target = Path(sys.argv[4])
data = json.loads(state_path.read_text(encoding='utf-8'))
completed = set(data.get(section, {}).get('completed', []))
if slug in completed and not target.exists():
    completed.discard(slug)
    sect = data.setdefault(section, {})
    sect['completed'] = sorted(completed)
    sect['status'] = 'pending'
    state_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    sys.exit(1)
if slug in completed:
    sys.exit(0)
sect = data.setdefault(section, {})
if sect.get('status') == 'completed':
    sect['status'] = 'pending'
    state_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
sys.exit(1)
PY
}

cjt::state_mark_story_completed() {
  local section="$1" slug="$2"
  python3 - "$CJT_STATE_FILE" "$section" "$slug" <<'PY'
import json, sys
from pathlib import Path

state_path = Path(sys.argv[1])
section = sys.argv[2]
slug = sys.argv[3]
data = json.loads(state_path.read_text(encoding='utf-8'))
completed = set(data.setdefault(section, {}).setdefault('completed', []))
completed.add(slug)
data[section]['completed'] = sorted(completed)
state_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
PY
}

cjt::state_get_refine_progress() {
  local slug="$1" total="$2"
  python3 - "$CJT_STATE_FILE" "$slug" "$total" <<'PY'
import json, sys
from pathlib import Path

state_path = Path(sys.argv[1])
slug = sys.argv[2]
total = int(sys.argv[3])
data = json.loads(state_path.read_text(encoding='utf-8'))
stories = data.setdefault('refine', {}).setdefault('stories', {})
record = stories.get(slug)
if not record:
    print(0)
    sys.exit(0)
if record.get('status') == 'done':
    print('done')
    sys.exit(0)
next_task = int(record.get('next_task', 0))
if next_task >= total:
    record['status'] = 'done'
    record.pop('next_task', None)
    stories[slug] = record
    state_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print('done')
else:
    print(next_task)
PY
}

cjt::state_update_refine_progress() {
  local slug="$1" next_task="$2" total="$3"
  python3 - "$CJT_STATE_FILE" "$slug" "$next_task" "$total" <<'PY'
import json, sys
from pathlib import Path

state_path = Path(sys.argv[1])
slug = sys.argv[2]
next_task = int(sys.argv[3])
total = int(sys.argv[4])
data = json.loads(state_path.read_text(encoding='utf-8'))
stories = data.setdefault('refine', {}).setdefault('stories', {})
record = stories.setdefault(slug, {})
if next_task >= total:
    record['status'] = 'done'
    record.pop('next_task', None)
else:
    record['status'] = 'in-progress'
    record['next_task'] = next_task
stories[slug] = record
state_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
PY
}

cjt::abs_path() {
  local path="${1:-}"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$path"
  else
    python3 - <<'PY' "$path"
import pathlib, sys
target = pathlib.Path(sys.argv[1] or '.')
print(target.expanduser().resolve())
PY
  fi
}

cjt::slugify() {
  local value="${1:-}"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  value="$(printf '%s' "$value" | tr -cs 'a-z0-9' '-')"
  value="$(printf '%s' "$value" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${value:-item}"
}

cjt::init() {
  CJT_PROJECT_ROOT="${1:?project root required}"
  CJT_MODEL="${2:-${CODEX_MODEL:-gpt-5-codex}}"
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

  mkdir -p "$CJT_PROMPTS_DIR" "$CJT_OUTPUT_DIR" "$CJT_JSON_DIR" \
    "$CJT_JSON_STORIES_DIR" "$CJT_JSON_TASKS_DIR" "$CJT_JSON_REFINED_DIR" "$CJT_TMP_DIR"

  local codex_bin="${CODEX_BIN:-${CODEX_CMD:-codex}}"
  if ! command -v "$codex_bin" >/dev/null 2>&1; then
    cjt::warn "Codex CLI '${codex_bin}' not found on PATH; commands will run in dry-run mode."
    CJT_DRY_RUN=1
  fi

  CJT_CODEX_CMD="$codex_bin"
  cjt::state_init
}

cjt::prepare_inputs() {
  cjt::log "Discovering documentation under $CJT_PROJECT_ROOT"
  local manifest
  manifest="$(gc::discover "$CJT_PROJECT_ROOT")"
  printf '%s\n' "$manifest" > "$CJT_PIPELINE_DIR/discovery.yaml"

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

cjt::build_context_files() {
  cjt::collect_source_files
  {
    echo "# Consolidated Project Context"
    echo "(Source: .gpt-creator staging copy)"
    echo
    local file
    for file in "${CJT_DOC_FILES[@]}"; do
      echo "----- FILE: $(basename "$file") -----"
      sed -e 's/\t/  /g' "$file"
      echo
    done
  } > "$CJT_CONTEXT_FILE"

  {
    echo "# Context Excerpt"
    echo "The following snippets provide quick access to key sections. Refer to the full context file for complete details."
    echo
    local file count
    for file in "${CJT_DOC_FILES[@]}"; do
      echo "## $(basename "$file")"
      if [[ -s "$file" ]]; then
        sed -n '1,160p' "$file"
        local total_lines
        total_lines=$(wc -l <"$file" 2>/dev/null || echo 0)
        if (( total_lines > 160 )); then
          echo "... (truncated; see full context for additional details)"
        fi
        echo
      else
        echo "(empty file)"
      fi
    done
  } > "$CJT_CONTEXT_SNIPPET_FILE"
}

cjt::codex_has_subcommand() {
  local subcmd="$1"
  "$CJT_CODEX_CMD" --help 2>/dev/null | grep -Eqi "(^|[[:space:]/-])${subcmd}([[:space:]/-]|$)"
}

cjt::run_codex() {
  local prompt_file="${1:?prompt file required}"
  local output_file="${2:?output file required}"
  local label="${3:-codex}"

  if [[ "$CJT_DRY_RUN" == "1" ]]; then
    cjt::warn "[dry-run] Skipping Codex invocation for $label"
    printf '{"status": "dry-run", "label": "%s"}\n' "$label" >"$output_file"
    return 0
  fi

  mkdir -p "$(dirname "$output_file")"
  local model="$CJT_MODEL"

  if cjt::codex_has_subcommand chat; then
    local cmd=("$CJT_CODEX_CMD" chat --model "$model" --prompt-file "$prompt_file" --output "$output_file")
    cjt::log "Running Codex (${label}) with model $CJT_MODEL"
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
    if [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
      args+=(-c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\"")
    fi
    args+=(--output-last-message "$output_file")
    cjt::log "Running Codex (${label}) with model $CJT_MODEL via exec"
    if ! "${args[@]}" < "$prompt_file"; then
      cjt::warn "Codex invocation failed for ${label}."
      return 1
    fi
    return 0
  fi

  if cjt::codex_has_subcommand generate; then
    local cmd=("$CJT_CODEX_CMD" generate --model "$model" --prompt-file "$prompt_file" --output "$output_file")
    cjt::log "Running Codex (${label}) with model $CJT_MODEL via generate"
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
  python3 - "$infile" "$outfile" <<'PY'
import json
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = raw_path.read_text(encoding='utf-8').strip()

# Attempt to locate the first JSON object/array in the text
stack = []
start = None
for idx, ch in enumerate(text):
    if ch in '{[':
        if not stack:
            start = idx
        stack.append(ch)
    elif ch in '}]':
        if stack:
            opening = stack.pop()
            if not stack and start is not None:
                snippet = text[start:idx+1]
                try:
                    data = json.loads(snippet)
                except json.JSONDecodeError:
                    continue
                else:
                    out_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
                    sys.exit(0)
if start is None:
    raise SystemExit("No JSON payload found in Codex output")
raise SystemExit("Failed to parse Codex JSON output")
PY
}

cjt::generate_epics() {
  local prompt_file="$CJT_PROMPTS_DIR/epics.prompt.md"
  local raw_output="$CJT_OUTPUT_DIR/epics.raw.txt"
  local json_output="$CJT_JSON_DIR/epics.json"

  if cjt::state_stage_is_completed "epics" && [[ -f "$json_output" ]]; then
    cjt::log "Epics already generated; skipping"
    return
  fi

  cjt::state_mark_stage_pending "epics"

  cjt::log "Creating Jira epics prompt"
  cjt::write_epics_prompt "$prompt_file"

  cjt::log "Generating Jira epics"
  if cjt::run_codex "$prompt_file" "$raw_output" "epic-generation"; then
    cjt::wrap_json_extractor "$raw_output" "$json_output"
  else
    cjt::die "Codex failed while generating epics"
  fi

  cjt::state_mark_stage_completed "epics"
}

cjt::write_epics_prompt() {
  local prompt_file="${1:?prompt file required}"
  {
    echo "You are a senior delivery lead creating Jira epics for the Bhavani Yoga product."
    echo
    echo "Project scope: only Website (customer-facing) and Admin/Backoffice experiences. Ignore DevOps, infrastructure, and tooling work."
    echo "Investigate the provided documentation thoroughly before proposing epics. Cover end-to-end functionality, including sunny-day flows and edge cases."
    echo
    echo "## Documentation Index"
    local file
    for file in "${CJT_DOC_FILES[@]}"; do
      echo "- ${file#$CJT_PROJECT_ROOT/}"
    done
    echo
    echo "## Context Excerpt"
    sed 's/\x1b\[[0-9;]*m//g' "$CJT_CONTEXT_SNIPPET_FILE"
    echo
    cat <<'PROMPT'
## Requirements
- Create a comprehensive backlog of Jira epics that covers every piece of functionality the website and admin/backoffice must deliver.
- Use identifiers `WEB-XX` for website-facing epics and `ADM-XX` for admin/backoffice epics. Start numbering at 01.
- Ensure the epics collectively span navigation, authentication, content, commerce/workflows, reporting, localization, accessibility, error states, and any other requirements found in the docs.
- Provide rich acceptance criteria per epic describing what success looks like (include non-functional needs such as performance, security, accessibility when applicable).
- Note any cross-epic dependencies.
- Include a short call-out of the primary user roles touched by the epic.

## Output format (JSON only)
{
  "epics": [
    {
      "epic_id": "WEB-01",
      "title": "Global shell, navigation, and layout",
      "summary": "High-level objective for the epic",
      "acceptance_criteria": ["Clear measurable criteria ..."],
      "dependencies": ["ADM-02"],
      "primary_roles": ["Visitor", "Member", "Admin"],
      "scope": "web"
    }
  ]
}

Return strictly valid JSON; do not include markdown fences or commentary.
PROMPT
  } > "$prompt_file"
}

cjt::generate_stories() {
  local epics_json="$CJT_JSON_DIR/epics.json"
  [[ -f "$epics_json" ]] || cjt::die "Epics JSON not found: ${epics_json}"

  if cjt::state_stage_is_completed "stories"; then
    cjt::log "User stories already generated; skipping"
    return
  fi

  cjt::state_mark_stage_pending "stories"

  local epic_ids
  mapfile -t epic_ids < <(python3 - "$epics_json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
epics = payload.get('epics') or []
for epic in epics:
    eid = (epic.get('epic_id') or '').strip()
    if eid:
        print(eid)
PY
)

  local epic_id
  for epic_id in "${epic_ids[@]}"; do
    local slug="$(cjt::slugify "$epic_id")"
    local prompt_file="$CJT_PROMPTS_DIR/story_${slug}.prompt.md"
    local raw_file="$CJT_OUTPUT_DIR/story_${slug}.raw.txt"
    local json_file="$CJT_JSON_DIR/story_${slug}.json"
    if cjt::state_story_is_completed "stories" "$slug" "$json_file"; then
      cjt::log "Story generation already completed for ${epic_id} (${slug}); skipping"
      continue
    fi
    cjt::write_story_prompt "$epic_id" "$prompt_file"
    cjt::log "Generating user stories for ${epic_id}"
    if cjt::run_codex "$prompt_file" "$raw_file" "stories-${epic_id}"; then
      cjt::wrap_json_extractor "$raw_file" "$json_file"
      cjt::split_story_json "$json_file"
      cjt::state_mark_story_completed "stories" "$slug"
    else
      cjt::die "Codex failed while generating stories for ${epic_id}"
    fi
  done

  cjt::state_mark_stage_completed "stories"
}

cjt::split_story_json() {
  local story_bundle="${1:?story bundle required}"
  python3 - "$story_bundle" "$CJT_JSON_STORIES_DIR" <<'PY'
import json
import sys
from pathlib import Path

bundle_path = Path(sys.argv[1])
stories_dir = Path(sys.argv[2])

payload = json.loads(bundle_path.read_text(encoding='utf-8'))
epic_id = payload.get('epic_id') or ''

stories = payload.get('user_stories') or []
for story in stories:
    sid = story.get('story_id') or ''
    if not sid:
        continue
    slug = ''.join(ch.lower() if ch.isalnum() else '-' for ch in sid)
    slug = '-'.join(filter(None, slug.split('-')))
    story_out = {
        'epic_id': epic_id,
        'story': story
    }
    (stories_dir / f"{slug}.json").write_text(json.dumps(story_out, indent=2) + '\n', encoding='utf-8')
PY
}

cjt::write_story_prompt() {
  local epic_id="${1:?epic id required}"
  local prompt_file="${2:?prompt file required}"
  local epics_json="$CJT_JSON_DIR/epics.json"
  python3 - "$epics_json" "$epic_id" "$prompt_file" "$CJT_CONTEXT_SNIPPET_FILE" <<'PY'
import json
import sys
from pathlib import Path

epics_path = Path(sys.argv[1])
epic_id = sys.argv[2]
prompt_path = Path(sys.argv[3])
context_snippet = Path(sys.argv[4]).read_text(encoding='utf-8')

data = json.loads(epics_path.read_text(encoding='utf-8'))
match = None
for epic in data.get('epics', []):
    if str(epic.get('epic_id')).strip().lower() == epic_id.lower():
        match = epic
        break

if not match:
    raise SystemExit(f"Epic {epic_id} not found in epics.json")

with prompt_path.open('w', encoding='utf-8') as fh:
    fh.write("You are a lead product analyst expanding Jira epics into granular user stories for the Bhavani Yoga build.\n\n")
    fh.write("Only focus on the website and admin/backoffice surfaces. Ignore DevOps/infra.\n\n")
    fh.write("## Target epic\n")
    json.dump(match, fh, indent=2)
    fh.write("\n\n")
    fh.write("## Shared documentation excerpt\n")
    fh.write(context_snippet)
    fh.write("\n\n")
    fh.write("## Requirements\n")
    fh.write("- Produce exhaustive user stories that cover sunny-day flows, edge cases, validation errors, state transitions, and accessibility requirements for this epic.\n")
    fh.write("- Use identifiers following the pattern '<epic-id>-US-XX'. Start numbering at 01.\n")
    fh.write("- Provide a user story narrative (role, goal, benefit) and detailed description of scope.\n")
    fh.write("- List acceptance criteria as bullet-equivalent strings (cover positive and negative cases).\n")
    fh.write("- Note any dependencies on other epics/stories when relevant.\n")
    fh.write("- Tag each story with domains (e.g., Web-FE, Web-BE, Admin-FE, Admin-BE).\n")
    fh.write("- Capture primary user roles touched by the story.\n")
    fh.write("\n")
    fh.write("## Output (JSON only)\n")
    fh.write("{\n  \"epic_id\": \"%s\",\n  \"user_stories\": [\n    {\n      \"story_id\": \"%s-US-01\",\n      \"title\": \"\",\n      \"narrative\": \"As a <role> I want ... so that ...\",\n      \"description\": \"Detailed scope and notes...\",\n      \"acceptance_criteria\": [\"...\"],\n      \"tags\": [\"Web-FE\"],\n      \"dependencies\": [\"WEB-02-US-02\"],\n      \"user_roles\": [\"Visitor\"],\n      \"non_functional\": [\"WCAG 2.2 AA\"]\n    }\n  ]\n}\n" % (epic_id, epic_id))
    fh.write("\nReturn strictly valid JSON without fences or extra commentary.\n")
PY
}

cjt::generate_tasks() {
  local stories
  mapfile -t stories < <(find "$CJT_JSON_STORIES_DIR" -maxdepth 1 -type f -name '*.json' | sort)
  if cjt::state_stage_is_completed "tasks"; then
    cjt::log "Tasks already generated; skipping"
    return
  fi

  cjt::state_mark_stage_pending "tasks"
  local story_file
  for story_file in "${stories[@]}"; do
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
    else
      cjt::die "Codex failed while generating tasks for story ${slug}"
    fi
  done

  cjt::state_mark_stage_completed "tasks"
}

cjt::write_task_prompt() {
  local story_file="${1:?story json required}"
  local prompt_file="${2:?prompt file required}"
  python3 - "$story_file" "$CJT_CONTEXT_SNIPPET_FILE" "$prompt_file" <<'PY'
import json
import sys
from pathlib import Path

story_path = Path(sys.argv[1])
context = Path(sys.argv[2]).read_text(encoding='utf-8')
prompt_path = Path(sys.argv[3])

story_payload = json.loads(story_path.read_text(encoding='utf-8'))

epic_id = story_payload.get('epic_id')
story = story_payload.get('story')
if not story:
    raise SystemExit(f"Story payload missing in {story_path}")

with prompt_path.open('w', encoding='utf-8') as fh:
    fh.write("You are a delivery engineer decomposing a single user story into actionable Jira tasks.\n\n")
    fh.write("Consider frontend, backend, admin UI, data, security, accessibility, analytics, and QA needs.\n\n")
    fh.write("## User story\n")
    json.dump(story, fh, indent=2)
    fh.write("\n\n")
    fh.write("## Epic context\n")
    json.dump({"epic_id": epic_id}, fh, indent=2)
    fh.write("\n\n")
    fh.write("## Documentation excerpt\n")
    fh.write(context)
    fh.write("\n\n")
    fh.write("## Requirements\n")
    fh.write("- Create tasks that cover sunny day, error handling, edge cases, observability, analytics, and release readiness.\n")
    fh.write("- Assign tasks to the appropriate roles: Architect, Dev/Ops, Project Manager, UI/UX designer, BE dev, FE dev, Test Eng.\n")
    fh.write("- Include dependencies when a task relies on another.\n")
    fh.write("- Add tags such as [Web-FE], [Web-BE], [Admin-FE], [Admin-BE], [API], [DB], [Design], [QA].\n")
    fh.write("- Provide Story points (integer) per task; align with the effort described.\n")
    fh.write("- Reference relevant documentation sections (e.g., 'SDS §10.1.1', 'SQL dump table users').\n")
    fh.write("- Spell out API endpoints, payload structures, data validation, and state transitions.\n")
    fh.write("- Cover testing requirements (unit, integration, E2E).\n")
    fh.write("\n")
    fh.write("## Output JSON schema\n")
    fh.write("{\n  \"story_id\": \"...\",\n  \"story_title\": \"...\",\n  \"tasks\": [\n    {\n      \"id\": \"WEB-01-T01\",\n      \"title\": \"...\",\n      \"description\": \"Detailed instructions...\",\n      \"acceptance_criteria\": [\"...\"],\n      \"tags\": [\"Web-FE\"],\n      \"assignees\": [\"FE dev\"],\n      \"estimate\": 5,\n      \"story_points\": 5,\n      \"dependencies\": [\"WEB-01-T00\"],\n      \"document_references\": [\"SDS §10.1.1\"],\n      \"endpoints\": [\"GET /api/v1/...\"],\n      \"data_contracts\": [\"Request payloads, DB tables, indexes, policies, RBAC\"],\n      \"qa_notes\": [\"Unit tests, integration tests\"],\n      \"user_roles\": [\"Visitor\"]\n    }\n  ]\n}\n")
    fh.write("Return strictly valid JSON with all required fields.\n")
PY
}

cjt::refine_tasks() {
  if [[ "$CJT_SKIP_REFINE" == "1" ]]; then
    cjt::log "Skipping task refinement (per flag)"
    return
  fi
  local task_files
  mapfile -t task_files < <(find "$CJT_JSON_TASKS_DIR" -maxdepth 1 -type f -name '*.json' | sort)
  if cjt::state_stage_is_completed "refine"; then
    cjt::log "Task refinement already completed; skipping"
    return
  fi

  cjt::state_mark_stage_pending "refine"
  local file
  for file in "${task_files[@]}"; do
    local slug="${file##*/}"; slug="${slug%.json}"
    local working_copy="$CJT_TMP_DIR/refine_${slug}.json"
    cp "$file" "$working_copy"

    local task_total
    task_total=$(python3 - <<'PY' "$working_copy"
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    print(0)
else:
    tasks = payload.get('tasks') or []
    print(len(tasks))
PY
)
    if [[ -z "$task_total" ]]; then
      task_total=0
    fi
    if (( task_total == 0 )); then
      cjt::warn "No tasks found for story ${slug}; skipping refinement"
      rm -f "$CJT_JSON_REFINED_DIR/${slug}.json" 2>/dev/null || true
      cjt::state_update_refine_progress "$slug" 0 0
      continue
    fi

    local progress
    progress="$(cjt::state_get_refine_progress "$slug" "$task_total")"
    if [[ "$progress" == "done" && -f "$CJT_JSON_REFINED_DIR/${slug}.json" ]]; then
      cjt::log "Refinement already completed for story ${slug}; skipping"
      continue
    fi
    local start_index=0
    if [[ "$progress" != "done" ]]; then
      start_index=${progress:-0}
    fi
    cjt::log "Refining tasks for story ${slug} (${task_total} tasks, starting at index ${start_index})"
    local idx
    local story_success=1
    for (( idx=start_index; idx<task_total; idx++ )); do
      local task_num
      printf -v task_num "%03d" $((idx + 1))
      local prompt_file="$CJT_PROMPTS_DIR/refine_${slug}_task_${task_num}.prompt.md"
      local raw_file="$CJT_OUTPUT_DIR/refine_${slug}_task_${task_num}.raw.txt"
      local json_file="$CJT_TMP_DIR/refine_${slug}_task_${task_num}.json"

      cjt::write_refine_task_prompt "$working_copy" "$idx" "$prompt_file"
      local attempt=0
      local max_attempts=2
      local prompt_augmented=0
      local success=0
      while (( attempt < max_attempts )); do
        (( attempt++ ))
        rm -f "$raw_file" "$json_file" 2>/dev/null || true
        if ! cjt::run_codex "$prompt_file" "$raw_file" "refine-${slug}-task-${task_num}"; then
          cjt::warn "Codex invocation failed for ${slug} task ${task_num} (attempt ${attempt}/${max_attempts})"
          continue
        fi
        if cjt::wrap_json_extractor "$raw_file" "$json_file"; then
          cjt::apply_refined_task "$working_copy" "$json_file" "$idx"
          cjt::state_update_refine_progress "$slug" $((idx + 1)) "$task_total"
          success=1
          break
        fi
        if (( prompt_augmented == 0 )); then
          cat >>"$prompt_file" <<'REM'

## Reminder
- Output a single JSON object conforming to the schema above.
- Do not include explanations, markdown code fences, or commentary outside the JSON.
- If a field is not applicable use an empty array or omit it; do not return prose.
REM
          prompt_augmented=1
        fi
        cjt::warn "Codex produced non-JSON output for ${slug} task ${task_num}; retrying (${attempt}/${max_attempts})."
      done
      if (( success == 0 )); then
        cjt::warn "Unable to obtain JSON output for ${slug} task ${task_num}; keeping prior content"
        story_success=0
        break
      fi
    done

    local final_story="$CJT_JSON_REFINED_DIR/${slug}.json"
    mkdir -p "$(dirname "$final_story")"
    cp "$working_copy" "$final_story"
    if (( story_success == 1 )); then
      cjt::state_update_refine_progress "$slug" "$task_total" "$task_total"
    fi
  done

  local remaining=0
  for file in "${task_files[@]}"; do
    local slug="${file##*/}"; slug="${slug%.json}"
    local total
    total=$(python3 - <<'PY' "$file"
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    print(0)
else:
    print(len(payload.get('tasks') or []))
PY
)
    total=${total//$'\n'/}
    total=${total:-0}
    if [[ "$(cjt::state_get_refine_progress "$slug" "$total")" != "done" ]]; then
      remaining=1
      break
    fi
  done
  if (( remaining == 0 )); then
    cjt::state_mark_stage_completed "refine"
  fi
}

cjt::write_refine_task_prompt() {
  local tasks_file="${1:?tasks json required}"
  local task_index="${2:?task index required}"
  local prompt_file="${3:?prompt file required}"
  python3 - "$tasks_file" "$task_index" "$CJT_CONTEXT_FILE" "$prompt_file" <<'PY'
import json
import sys
from pathlib import Path

story_path = Path(sys.argv[1])
task_index = int(sys.argv[2])
context = Path(sys.argv[3]).read_text(encoding='utf-8')
prompt_path = Path(sys.argv[4])

story_payload = json.loads(story_path.read_text(encoding='utf-8'))
tasks = story_payload.get('tasks') or []
if task_index < 0 or task_index >= len(tasks):
    raise SystemExit(f"Task index {task_index} out of range for {story_path}")

story_id = story_payload.get('story_id') or ''
story_title = story_payload.get('story_title') or ''
epic_id = story_payload.get('epic_id') or ''
target_task = tasks[task_index]

with prompt_path.open('w', encoding='utf-8') as fh:
    fh.write("You are validating and enriching a Jira task for the Bhavani Yoga delivery team.\n")
    fh.write("Only website and admin/backoffice scopes are in play—ignore DevOps and infra.\n\n")

    fh.write("## Project documentation excerpt\n")
    fh.write(context)
    fh.write("\n\n")

    fh.write("## User story context\n")
    story_ctx = {
        "epic_id": epic_id,
        "story_id": story_id,
        "story_title": story_title,
        "story_description": story_payload.get('description') or '',
        "story_acceptance_criteria": story_payload.get('acceptance_criteria') or [],
        "story_tags": story_payload.get('tags') or [],
        "story_roles": story_payload.get('user_roles') or []
    }
    json.dump(story_ctx, fh, indent=2)
    fh.write("\n\n")

    fh.write("## Current task draft\n")
    json.dump(target_task, fh, indent=2)
    fh.write("\n\n")

    fh.write("## Requirements\n")
    fh.write("- Ensure the task aligns with PDR, SDS, SQL schema, and OpenAPI definitions.\n")
    fh.write("- Spell out endpoints, payload contracts (values, types, validation), database tables/indexes/keys, caching/idempotency, and policy/RBAC expectations.\n")
    fh.write("- Cover sunny-day, edge cases, error handling, observability, analytics, and QA (unit/integration/E2E).\n")
    fh.write("- Populate structured fields: title, description, acceptance_criteria, tags, assignees, story_points, estimate, dependencies, document_references, endpoints, data_contracts, qa_notes, analytics, observability, user_roles, policy.\n")
    fh.write("- Use the approved assignee list: Architect, Dev/Ops, Project Manager, UI/UX designer, BE dev, FE dev, Test Eng.\n")
    fh.write("- Tags should follow the format [Web-FE], [Web-BE], [Admin-FE], [Admin-BE], [API], [DB], [Design], [QA], etc.\n")
    fh.write("- Provide story_points as an integer (1..13) and keep dependencies referencing other task IDs when relevant.\n")
    fh.write("- Return rich acceptance criteria that are testable and cover negative paths.\n")
    fh.write("- Do not include markdown fences or commentary outside the JSON response.\n\n")

    task_id = target_task.get('id') or target_task.get('task_id') or 'TASK-ID'
    fh.write("## Output format (JSON only)\n")
    fh.write("{\n  \"task\": {\n    \"id\": \"%s\",\n    \"title\": \"...\",\n    \"description\": \"...\",\n    \"acceptance_criteria\": [\"...\"],\n    \"tags\": [\"Web-FE\"],\n    \"assignees\": [\"FE dev\"],\n    \"estimate\": 5,\n    \"story_points\": 5,\n    \"dependencies\": [\"%s\"],\n    \"document_references\": [\"SDS §10.1.1\"],\n    \"endpoints\": [\"GET /api/v1/...\"],\n    \"data_contracts\": [\"Request payload...\"],\n    \"qa_notes\": [\"Unit tests\"],\n    \"analytics\": [\"Track ...\"],\n    \"observability\": [\"Metrics ...\"],\n    \"user_roles\": [\"Visitor\"],\n    \"policy\": [\"Role mapping...\"],\n    \"idempotency\": \"Describe behaviour...\",\n    \"rate_limits\": \"Document limits...\"\n  }\n}\n" % (task_id, task_id))
    fh.write("Ensure the JSON uses double quotes and escapes newline characters inside string values.\n")
PY
}

cjt::apply_refined_task() {
  local working_json="${1:?working story json required}"
  local refined_json="${2:?refined task json required}"
  local task_index="${3:?task index required}"
  python3 - "$working_json" "$refined_json" "$task_index" <<'PY'
import json
import sys
from pathlib import Path

working_path = Path(sys.argv[1])
refined_path = Path(sys.argv[2])
task_index = int(sys.argv[3])

if not refined_path.exists():
    raise SystemExit(0)

try:
    refined_payload = json.loads(refined_path.read_text(encoding='utf-8'))
except json.JSONDecodeError:
    raise SystemExit(0)

if isinstance(refined_payload, dict):
    task_data = refined_payload.get('task', refined_payload)
else:
    task_data = None

if not isinstance(task_data, dict):
    raise SystemExit(0)

if not any(key in task_data for key in ("title", "description", "acceptance_criteria", "tags")):
    raise SystemExit(0)

try:
    story_payload = json.loads(working_path.read_text(encoding='utf-8'))
except json.JSONDecodeError:
    raise SystemExit(0)

tasks = story_payload.get('tasks')
if not isinstance(tasks, list) or task_index < 0 or task_index >= len(tasks):
    raise SystemExit(0)

existing = tasks[task_index]
if not isinstance(existing, dict):
    raise SystemExit(0)

for key, value in task_data.items():
    if value is None:
       continue
    existing[key] = value

story_payload['tasks'][task_index] = existing
working_path.write_text(json.dumps(story_payload, indent=2) + "\n", encoding='utf-8')
PY
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
  cjt::refine_tasks
  cjt::build_payload
  cjt::update_database
}

return 0
