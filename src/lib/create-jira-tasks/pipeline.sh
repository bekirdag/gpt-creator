#!/usr/bin/env bash
# shellcheck shell=bash
# create-jira-tasks pipeline helpers

if [[ -n "${GC_LIB_CREATE_JIRA_TASKS_PIPELINE_SH:-}" ]]; then
  return 0
fi
GC_LIB_CREATE_JIRA_TASKS_PIPELINE_SH=1

set -o errtrace

CJT_DOC_FILES=()
CJT_SDS_SOURCE=""
CJT_SDS_CHUNKS_DIR=""
CJT_SDS_CHUNKS_LIST=""
CJT_PDR_PATH=""
CJT_SQL_PATH=""

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

cjt::derive_project_title() {
  local input="${1:-}"
  python3 - <<'PY' "$input"
import pathlib
import re
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else ''
if raw:
    path = pathlib.Path(raw)
    if path.exists():
        raw = path.name
raw = re.sub(r'[_\-]+', ' ', raw)
raw = re.sub(r'\s+', ' ', raw).strip()
if not raw:
    print("Project")
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
  CJT_TASKS_DIR="$CJT_PLAN_DIR/tasks"

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
  python3 - "$source_path" "$dest_path" <<'PY'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
dest = Path(sys.argv[2])
try:
    text = source.read_text(encoding='utf-8', errors='ignore')
except Exception:
    dest.write_text('', encoding='utf-8')
    raise SystemExit(0)

text = text.replace('\r\n', '\n').replace('\r', '\n')

if text.startswith('---\n'):
    end_idx = text.find('\n---', 4)
    if 0 <= end_idx <= 5000:
        text = text[end_idx + 4 :]

CODE_BLOCK_MAX_LINES = 120
CODE_BLOCK_MAX_CHARS = 4000

lines = text.split('\n')
cleaned = []
code_lines = []
in_code_block = False
code_fence = ''
code_header = ''
skipping_toc = False
toc_seen = False

def flush_code_block() -> None:
    if not code_lines:
        return
    body = '\n'.join(code_lines)
    if CODE_BLOCK_MAX_LINES > 0:
        body_lines = body.splitlines()
        if len(body_lines) > CODE_BLOCK_MAX_LINES:
            body_lines = body_lines[:CODE_BLOCK_MAX_LINES]
            body_lines.append('... (code block truncated)')
        body = '\n'.join(body_lines)
    if CODE_BLOCK_MAX_CHARS > 0 and len(body) > CODE_BLOCK_MAX_CHARS:
        body = body[:CODE_BLOCK_MAX_CHARS].rstrip() + '\n... (code block truncated)'
    cleaned.append(code_header or '```')
    cleaned.append(body)
    cleaned.append(code_header or '```')

for raw_line in lines:
    line = raw_line.replace('\t', '  ')
    stripped = line.strip()
    lower = stripped.lower()

    if in_code_block:
        if stripped.startswith(code_fence):
            flush_code_block()
            code_lines = []
            in_code_block = False
            code_fence = ''
            code_header = ''
        else:
            code_lines.append(raw_line)
        continue

    if stripped.startswith('<!--') and stripped.endswith('-->'):
        continue
    if stripped.startswith('<!--'):
        continue
    if stripped.endswith('-->'):
        continue

    if stripped.startswith('```') or stripped.startswith('~~~'):
        in_code_block = True
        code_fence = stripped[:3]
        code_header = stripped if len(stripped) > 3 else code_fence
        code_lines = []
        continue

    if skipping_toc:
        if not stripped or stripped.startswith('#'):
            skipping_toc = False
        elif re.match(r'^(\s*[-*+]\s|\s*\d+\.\s)', stripped) or '(#' in stripped:
            continue
        else:
            skipping_toc = False

    if re.match(r'^#{1,6}\s+(table of contents|contents)\b', lower):
        skipping_toc = True
        toc_seen = True
        continue
    if not toc_seen and stripped.startswith('- [') and '(#' in stripped:
        continue

    if not stripped:
        if cleaned and cleaned[-1] == '':
            continue
        cleaned.append('')
        continue

    if len(stripped) > 800:
        continue

    if re.fullmatch(r'[-=_*]{4,}', stripped):
        continue

    cleaned.append(stripped)

if in_code_block and code_lines:
    flush_code_block()

clean_text = '\n'.join(cleaned).strip()
clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
dest.write_text(clean_text + ('\n' if clean_text else ''), encoding='utf-8')
PY
}

cjt::append_file_with_char_limit() {
  local source_path="${1:?source path required}"
  local dest_path="${2:?destination path required}"
  local max_chars="${3:-0}"
  python3 - "$source_path" "$dest_path" "$max_chars" <<'PY'
import sys
from pathlib import Path

src = Path(sys.argv[1])
dest = Path(sys.argv[2])
max_chars = int(sys.argv[3])
if not src.exists():
    text = ''
else:
    text = src.read_text(encoding='utf-8', errors='ignore')
if max_chars > 0 and len(text) > max_chars:
    text = text[:max_chars].rstrip() + "\n... (truncated; see source for full details)\n"
if text and not text.endswith('\n'):
    text += '\n'
with dest.open('a', encoding='utf-8') as fh:
    fh.write(text)
PY
}

cjt::append_file_with_line_limit() {
  local source_path="${1:?source path required}"
  local dest_path="${2:?destination path required}"
  local max_lines="${3:-0}"
  local max_chars="${4:-0}"
  python3 - "$source_path" "$dest_path" "$max_lines" "$max_chars" <<'PY'
import sys
from pathlib import Path

src = Path(sys.argv[1])
dest = Path(sys.argv[2])
max_lines = int(sys.argv[3])
max_chars = int(sys.argv[4])
if not src.exists():
    text = ''
else:
    text = src.read_text(encoding='utf-8', errors='ignore')
lines = text.splitlines()
truncated = False
if max_lines > 0 and len(lines) > max_lines:
    lines = lines[:max_lines]
    truncated = True
snippet = '\n'.join(lines)
if max_chars > 0 and len(snippet) > max_chars:
    snippet = snippet[:max_chars].rstrip()
    truncated = True
if snippet and not snippet.endswith('\n'):
    snippet += '\n'
with dest.open('a', encoding='utf-8') as fh:
    fh.write(snippet)
    if truncated:
        fh.write("... (truncated; see consolidated context for more)\n\n")
    elif snippet:
        fh.write('\n')
PY
}

cjt::chunk_doc_by_headings() {
  local source_file="${1:?source file required}"
  local chunk_dir="${2:?chunk directory required}"
  local out_list="${3:?chunk list file required}"
  python3 - <<'PY' "$source_file" "$chunk_dir" "$out_list"
import re
import sys
from pathlib import Path


def main(source_path: Path, chunk_dir: Path, out_list: Path) -> None:
    text = source_path.read_text(encoding='utf-8', errors='ignore')
    lines = text.splitlines()

    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunks = []

    heading_re = re.compile(r'^(#+)\s*(.+)$')
    current = []
    current_heading = 'Introduction'
    current_label = ''
    index = 0

    def flush() -> None:
        nonlocal index, current
        nonlocal current_heading, current_label
        if not current:
            return
        index += 1
        chunk_path = chunk_dir / f"chunk_{index:03d}.md"
        chunk_path.write_text('\n'.join(current).strip() + '\n', encoding='utf-8')
        chunks.append((str(chunk_path), current_label, current_heading))
        current = []

    for line in lines:
        match = heading_re.match(line)
        if match:
            flush()
            heading_text = match.group(2).strip()
            label_match = re.match(r'((?:\d+\.)*\d+)', heading_text)
            current_label = label_match.group(1) if label_match else ''
            current_heading = heading_text
            current = [line]
        else:
            current.append(line)

    flush()

    if not chunks:
        chunk_path = chunk_dir / "chunk_001.md"
        chunk_path.write_text(text, encoding='utf-8')
        chunks.append((str(chunk_path), '', 'Full Document'))

    out_lines = ["|".join(part.replace('\n', ' ').strip() for part in chunk) for chunk in chunks]
    out_list.write_text('\n'.join(out_lines) + ('\n' if out_lines else ''), encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))

PY
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
  : "${CJT_CONTEXT_FULL_CHAR_LIMIT:=15000}"
  : "${CJT_CONTEXT_SNIPPET_LINES:=80}"
  : "${CJT_CONTEXT_SNIPPET_CHAR_LIMIT:=6000}"

  local cleaned_dir="$CJT_PIPELINE_DIR/cleaned-docs"
  mkdir -p "$cleaned_dir" "$CJT_TMP_DIR"

  : > "$CJT_CONTEXT_FILE"
  : > "$CJT_CONTEXT_SNIPPET_FILE"

  {
    echo "# Consolidated Project Context"
    echo "(Source: .gpt-creator staging copy)"
    echo
  } >> "$CJT_CONTEXT_FILE"

  {
    echo "# Context Excerpt"
    echo "The following snippets provide quick access to key sections. Refer to the consolidated context for additional detail."
    echo
  } >> "$CJT_CONTEXT_SNIPPET_FILE"

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

    printf '----- FILE: %s -----\n' "$rel_path" >> "$CJT_CONTEXT_FILE"
    if [[ -s "$cleaned_path" ]]; then
      cjt::append_file_with_char_limit "$cleaned_path" "$CJT_CONTEXT_FILE" "$CJT_CONTEXT_FULL_CHAR_LIMIT"
    else
      printf '(empty after sanitization)\n\n' >> "$CJT_CONTEXT_FILE"
    fi

    printf '## %s\n' "$rel_path" >> "$CJT_CONTEXT_SNIPPET_FILE"
    if [[ -s "$cleaned_path" ]]; then
      cjt::append_file_with_line_limit "$cleaned_path" "$CJT_CONTEXT_SNIPPET_FILE" "$CJT_CONTEXT_SNIPPET_LINES" "$CJT_CONTEXT_SNIPPET_CHAR_LIMIT"
    else
      printf '(empty after sanitization)\n\n' >> "$CJT_CONTEXT_SNIPPET_FILE"
    fi

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
    CJT_SDS_SOURCE="$sds_candidate"
    CJT_SDS_CHUNKS_DIR="$CJT_PIPELINE_DIR/sds-chunks"
    CJT_SDS_CHUNKS_LIST="$CJT_SDS_CHUNKS_DIR/list.txt"
    cjt::chunk_doc_by_headings "$sds_clean_path" "$CJT_SDS_CHUNKS_DIR" "$CJT_SDS_CHUNKS_LIST"
  else
    CJT_SDS_SOURCE=""
    CJT_SDS_CHUNKS_DIR=""
    CJT_SDS_CHUNKS_LIST=""
  fi

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
  python3 - "$json_file" "$index" <<'PY'
import json, sys
from pathlib import Path

json_path = Path(sys.argv[1])
index = int(sys.argv[2])

try:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)

tasks = payload.get("tasks") or []
if 0 <= index < len(tasks):
    title = (tasks[index].get("title") or "").strip()
    print(title)
else:
    print("")
PY
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
import ast
import json
import math
import string
import sys
from pathlib import Path
from typing import Any

raw_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
text = raw_path.read_text(encoding='utf-8')

UNICODE_QUOTE_MAP = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
})
CODE_FENCE_LANG_HINTS = (
    "javascript",
    "typescript",
    "jsonschema",
    "jsonc",
    "json5",
    "jsonl",
    "json",
    "js",
    "ts",
    "python",
    "py",
    "text",
    "txt",
)
VALID_SIMPLE_ESCAPES = {'"', '\\', '/', 'b', 'f', 'n', 'r', 't'}
HEX_DIGITS = set(string.hexdigits)
STRUCTURE_BONUS_KEYS = {
    "epics",
    "epic_id",
    "user_stories",
    "story",
    "story_id",
    "stories",
    "tasks",
    "task",
    "task_groups",
    "items",
    "work_items",
    "acceptance_criteria",
    "dependencies",
}
SPECIAL_LITERAL_REPLACEMENTS = [
    ("-Infinity", "null"),
    ("Infinity", "null"),
    ("NaN", "null"),
    ("undefined", "null"),
    ("None", "null"),
]
IDENTIFIER_CHARS = set(string.ascii_letters + string.digits + "_$")

def is_identifier_char(ch: str) -> bool:
    return bool(ch) and ch in IDENTIFIER_CHARS

def normalize_unicode_quotes(value: str) -> str:
    return value.translate(UNICODE_QUOTE_MAP)

def strip_code_fences(value: str) -> str:
    lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            remainder = stripped.lstrip("`~").lstrip()
            if remainder:
                lowered = remainder.lower()
                for hint in CODE_FENCE_LANG_HINTS:
                    if lowered.startswith(hint):
                        remainder = remainder[len(hint):]
                        remainder = remainder.lstrip(" \t:-=")
                        lowered = remainder.lower()
                        break
            if remainder:
                indent = len(line) - len(line.lstrip())
                lines.append(" " * indent + remainder)
            continue
        lines.append(line)
    return "\n".join(lines)

def strip_json_comments(payload: str) -> str:
    result = []
    length = len(payload)
    i = 0
    in_string = False
    string_char = ""
    escape = False
    while i < length:
        ch = payload[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == string_char:
                in_string = False
                string_char = ""
            i += 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            result.append(ch)
            i += 1
            continue

        if ch == '#':
            i += 1
            while i < length and payload[i] not in '\r\n':
                i += 1
            continue

        if ch == '/' and i + 1 < length:
            nxt = payload[i + 1]
            if nxt == '/':
                i += 2
                while i < length and payload[i] not in '\r\n':
                    i += 1
                continue
            if nxt == '*':
                i += 2
                while i + 1 < length and not (payload[i] == '*' and payload[i + 1] == '/'):
                    i += 1
                i = min(i + 2, length)
                continue

        result.append(ch)
        i += 1
    return ''.join(result)

def escape_invalid_backslashes(payload: str) -> str:
    result = []
    length = len(payload)
    i = 0
    in_string = False
    string_char = ""
    while i < length:
        ch = payload[i]
        if in_string:
            if ch == '\\':
                if i + 1 >= length:
                    result.append('\\')
                    result.append('\\')
                    i += 1
                    continue
                nxt = payload[i + 1]
                if nxt == 'u':
                    hex_seq = payload[i + 2:i + 6]
                    if len(hex_seq) < 4 or any(c not in HEX_DIGITS for c in hex_seq):
                        result.append('\\')
                        result.append('\\')
                        i += 1
                        continue
                    result.append('\\')
                    result.append('u')
                    result.extend(hex_seq)
                    i += 6
                    continue
                if nxt not in VALID_SIMPLE_ESCAPES:
                    result.append('\\')
                    result.append('\\')
                    i += 1
                    continue
                result.append('\\')
                result.append(nxt)
                i += 2
                continue
            result.append(ch)
            if ch == string_char:
                in_string = False
                string_char = ""
            i += 1
            continue
        result.append(ch)
        if ch in ('"', "'"):
            in_string = True
            string_char = ch
        i += 1
    return ''.join(result)

def remove_trailing_commas(payload: str) -> str:
    result = []
    length = len(payload)
    i = 0
    in_string = False
    string_char = ""
    escape = False
    while i < length:
        ch = payload[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == string_char:
                in_string = False
                string_char = ""
            i += 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            result.append(ch)
            i += 1
            continue

        if ch == ',':
            j = i + 1
            while j < length and payload[j] in ' \t\r\n':
                j += 1
            if j < length and payload[j] in '}]':
                i += 1
                continue

        result.append(ch)
        i += 1
    return ''.join(result)

def replace_invalid_literals(payload: str) -> tuple[str, list[str]]:
    result = []
    length = len(payload)
    i = 0
    in_string = False
    string_char = ""
    escape = False
    replaced_tokens: list[str] = []
    while i < length:
        ch = payload[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == string_char:
                in_string = False
                string_char = ""
            i += 1
            continue

        if ch in ('"', "'"):
            in_string = True
            string_char = ch
            result.append(ch)
            i += 1
            continue

        matched = False
        for token, replacement in SPECIAL_LITERAL_REPLACEMENTS:
            if payload.startswith(token, i):
                prev = payload[i - 1] if i > 0 else ''
                end = i + len(token)
                nxt = payload[end] if end < length else ''
                if (prev and is_identifier_char(prev)) or (nxt and is_identifier_char(nxt)):
                    continue
                result.append(replacement)
                replaced_tokens.append(token)
                i = end
                matched = True
                break
        if matched:
            continue

        result.append(ch)
        i += 1

    if replaced_tokens:
        return ''.join(result), replaced_tokens
    return payload, []

def has_invalid_numbers(value: Any) -> bool:
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, dict):
        return any(has_invalid_numbers(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(has_invalid_numbers(v) for v in value)
    return False

def normalize_literal(value):
    if isinstance(value, dict):
        return {str(k): normalize_literal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_literal(v) for v in value]
    return value

def coerce_python_literal(candidate: str) -> tuple[bool, Any]:
    try:
        parsed = ast.literal_eval(candidate)
    except (ValueError, SyntaxError):
        return False, None
    normalized = normalize_literal(parsed)
    try:
        json.dumps(normalized)
    except (TypeError, ValueError):
        return False, None
    return True, normalized

def try_json_load(candidate: str):
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return False, None, exc
    if has_invalid_numbers(data):
        return False, None, ValueError("JSON contains NaN or Infinity")
    return True, data, None

def parse_candidate(candidate: str):
    candidate = candidate.strip()
    if not candidate:
        return False, None, [], None

    candidate = normalize_unicode_quotes(candidate)
    notes: list[str] = []
    last_error = None

    success, parsed, err = try_json_load(candidate)
    if success:
        return True, parsed, notes, None
    last_error = err

    stripped_comments = strip_json_comments(candidate)
    if stripped_comments != candidate:
        candidate = stripped_comments
        notes.append("Removed JavaScript/Python-style comments from JSON payload.")
        success, parsed, err = try_json_load(candidate)
        if success:
            return True, parsed, notes, None
        last_error = err

    no_trailing = remove_trailing_commas(candidate)
    if no_trailing != candidate:
        candidate = no_trailing
        notes.append("Removed trailing commas from JSON payload.")
        success, parsed, err = try_json_load(candidate)
        if success:
            return True, parsed, notes, None
        last_error = err

    normalized_literals, replaced_tokens = replace_invalid_literals(candidate)
    if replaced_tokens:
        candidate = normalized_literals
        replacements_note = ", ".join(dict.fromkeys(replaced_tokens))
        notes.append(f"Replaced invalid literal(s) {replacements_note} with null.")
        success, parsed, err = try_json_load(candidate)
        if success:
            return True, parsed, notes, None
        last_error = err

    escaped_backslashes = escape_invalid_backslashes(candidate)
    if escaped_backslashes != candidate:
        candidate = escaped_backslashes
        notes.append("Escaped stray backslashes in JSON payload.")
        success, parsed, err = try_json_load(candidate)
        if success:
            return True, parsed, notes, None
        last_error = err

    literal_success, literal = coerce_python_literal(candidate)
    if literal_success:
        notes.append("Coerced Python-style literal to valid JSON.")
        return True, literal, notes, None

    return False, None, notes, last_error

def candidate_score(data: Any, snippet: str) -> float:
    score = min(len(snippet.strip()), 8000) / 10.0
    if isinstance(data, dict):
        keys = {str(k).lower() for k in data.keys()}
        score += 40 + len(keys) * 2
        score += sum(8 for key in STRUCTURE_BONUS_KEYS if key in keys)
    elif isinstance(data, list):
        score += 30 + len(data) * 1.2
    else:
        score += 5
    return score

def emit_payload(data, notes):
    if notes:
        note = "; ".join(dict.fromkeys(notes))
        print(f"[create-jira-tasks][json] {note}", file=sys.stderr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    sys.exit(0)

clean_text = normalize_unicode_quotes(strip_code_fences(text)).lstrip("\ufeff").strip()

last_error = None
success, parsed, notes, last_error = parse_candidate(clean_text)
if success:
    emit_payload(parsed, notes)

stack = []
start = None
string_char = None
escape_next = False
last_failed_snippet = None
best_payload = None
best_notes: list[str] = []
best_score = -1.0
best_snippet = ""

for idx, ch in enumerate(clean_text):
    if not stack:
        if ch in '{[':
            start = idx
            stack.append('}' if ch == '{' else ']')
            string_char = None
            escape_next = False
        continue

    if string_char is not None:
        if escape_next:
            escape_next = False
        elif ch == '\\':
            escape_next = True
        elif ch == string_char:
            string_char = None
        continue

    if ch in ('"', "'"):
        string_char = ch
        continue

    if ch in '{[':
        stack.append('}' if ch == '{' else ']')
        continue

    if ch in '}]':
        if not stack:
            continue
        expected = stack.pop()
        if ch != expected:
            stack.clear()
            start = None
            string_char = None
            escape_next = False
            continue
        if not stack and start is not None:
            snippet = clean_text[start:idx+1]
            success, parsed, notes, err = parse_candidate(snippet)
            if success:
                score = candidate_score(parsed, snippet)
                if score > best_score or (score == best_score and len(snippet) > len(best_snippet)):
                    best_payload = parsed
                    best_notes = notes
                    best_score = score
                    best_snippet = snippet
            last_failed_snippet = snippet.strip()
            if err is not None:
                last_error = err
            start = None
            string_char = None
            escape_next = False
        continue

if best_payload is not None:
    emit_payload(best_payload, best_notes)

if last_failed_snippet:
    preview = last_failed_snippet[:500]
    error_msg = f"{last_error}" if last_error else "unable to parse JSON"
    raise SystemExit(f"Failed to parse Codex JSON output ({error_msg}). Partial preview:\n{preview}")

raise SystemExit("No JSON payload found in Codex output")
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
  local project_label="${CJT_PROJECT_TITLE:-this project}"
  {
    printf "You are a senior delivery lead creating Jira epics for the %s initiative.\n\n" "$project_label"
    echo "Project scope: prioritize the customer-facing and admin/backoffice experiences described in the documentation."
    echo "Ignore DevOps, infrastructure, and tooling work unless explicitly documented."
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

  local epic_id
  while IFS= read -r epic_id; do
    [[ -n "$epic_id" ]] || continue
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
  done < <(python3 - "$epics_json" <<'PY'
import json
import os
import sys
from datetime import datetime
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
epics = payload.get('epics') or []
for epic in epics:
    eid = (epic.get('epic_id') or '').strip()
    if eid:
        print(eid)
PY
  )

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
  local project_label="${CJT_PROJECT_TITLE:-the product}"
  CJT_PROMPT_TITLE="$project_label" python3 - "$epics_json" "$epic_id" "$prompt_file" "$CJT_CONTEXT_SNIPPET_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

epics_path = Path(sys.argv[1])
epic_id = sys.argv[2]
prompt_path = Path(sys.argv[3])
context_snippet = Path(sys.argv[4]).read_text(encoding='utf-8')
project_label = os.environ.get('CJT_PROMPT_TITLE', 'the product').strip() or 'the product'

data = json.loads(epics_path.read_text(encoding='utf-8'))
match = None
for epic in data.get('epics', []):
    if str(epic.get('epic_id')).strip().lower() == epic_id.lower():
        match = epic
        break

if not match:
    raise SystemExit(f"Epic {epic_id} not found in epics.json")

with prompt_path.open('w', encoding='utf-8') as fh:
    fh.write(f"You are a lead product analyst expanding Jira epics into granular user stories for the {project_label} initiative.\n\n")
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
  if cjt::state_stage_is_completed "tasks"; then
    cjt::log "Tasks already generated; skipping"
    return
  fi

  cjt::state_mark_stage_pending "tasks"
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
      cjt::inline_refine_story_tasks "$json_file" "$slug"
    else
      cjt::die "Codex failed while generating tasks for story ${slug}"
    fi
  done < <(find "$CJT_JSON_STORIES_DIR" -maxdepth 1 -type f -name '*.json' | sort)

  cjt::state_mark_stage_completed "tasks"
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

  local refine_data
  refine_data=$(python3 - <<'PY' "$working" "$refine_mode"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
mode = sys.argv[2].strip().lower()
payload = json.loads(path.read_text(encoding='utf-8'))
tasks = payload.get("tasks") or []

REQUIRED_TEXT_FIELDS = ("title", "description")
REQUIRED_LIST_FIELDS = (
    "acceptance_criteria",
    "tags",
    "assignees",
    "document_references",
    "endpoints",
    "data_contracts",
    "qa_notes",
)

def normalized_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        striped = value.strip()
        return [striped] if striped else []
    return []

def is_positive(value, zero_ok=False):
    try:
        if isinstance(value, str):
            value = float(value.strip())
        return value >= 0 if zero_ok else value > 0
    except Exception:
        return False

def needs_refine(task: dict) -> bool:
    for field in REQUIRED_TEXT_FIELDS:
        if not isinstance(task.get(field), str) or not task.get(field).strip():
            return True
    for field in REQUIRED_LIST_FIELDS:
        if not normalized_list(task.get(field)):
            return True
    if not is_positive(task.get("story_points"), zero_ok=False):
        return True
    if not is_positive(task.get("estimate"), zero_ok=False):
        return True
    return False

mode = {"auto": "auto", "automatic": "auto", "all": "all"}.get(mode, mode)
indices = []
for idx, task in enumerate(tasks):
    if mode == "all":
        indices.append(idx)
    elif mode == "auto":
        if needs_refine(task):
            indices.append(idx)
    else:
        indices = []
        break

print(len(tasks))
for idx in indices:
    print(idx)
PY
)

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
  python3 - "$story_file" "$CJT_CONTEXT_SNIPPET_FILE" "$prompt_file" "${CJT_SDS_CHUNKS_LIST:-}" <<'PY'
import json
import os
import re
import sys
from pathlib import Path

story_path = Path(sys.argv[1])
context_raw = Path(sys.argv[2]).read_text(encoding='utf-8')
prompt_path = Path(sys.argv[3])
sds_chunk_list = Path(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None

story_payload = json.loads(story_path.read_text(encoding='utf-8'))

epic_id = story_payload.get('epic_id')
story = story_payload.get('story')
if not story:
    raise SystemExit(f"Story payload missing in {story_path}")

def extract_keywords(story_data: dict) -> set[str]:
    fields = []
    for key in ("title", "narrative", "description"):
        value = story_data.get(key) or ""
        if isinstance(value, str):
            fields.append(value)
    extra = story_data.get("acceptance_criteria")
    if isinstance(extra, list):
        fields.extend(str(item) for item in extra if item)
    joined = " ".join(fields).lower()
    raw_tokens = re.findall(r"[a-z0-9][a-z0-9\-_/]{2,}", joined)
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "system",
        "user",
        "story",
        "should",
        "will",
        "must",
        "allow",
        "support",
        "able",
        "data",
        "api",
        "admin",
    }
    keywords = {token.strip("-_/") for token in raw_tokens if len(token) > 3}
    return {kw for kw in keywords if kw and kw not in stopwords}

def score_text(text: str, keywords: set[str]) -> int:
    if not text:
        return 0
    lower = text.lower()
    return sum(lower.count(keyword) for keyword in keywords)

def summarize_text(text: str, char_limit: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if char_limit > 0 and len(text) > char_limit:
        trimmed = text[:char_limit].rstrip()
        return f"{trimmed}\n... (truncated; consult source for full details)"
    return text

def parse_context_sections(blob: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = "Overview"
    current_lines: list[str] = []
    for line in blob.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip() or "Section"
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    deduped = []
    seen = set()
    for title, text in sections:
        key = (title, text[:200])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((title, text))
    return deduped

def choose_context_sections(blob: str, keywords: set[str]) -> list[tuple[str, str]]:
    max_sections = int(os.environ.get("CJT_TASK_CONTEXT_SECTION_LIMIT", "5"))
    char_limit = int(os.environ.get("CJT_TASK_CONTEXT_SECTION_CHAR_LIMIT", "1200"))
    sections = parse_context_sections(blob)
    if not sections:
        return []
    scored = []
    for title, text in sections:
        snippet = summarize_text(text, char_limit)
        score = score_text(text, keywords)
        scored.append((score, title, snippet))
    scored.sort(key=lambda item: item[0], reverse=True)
    filtered = [entry for entry in scored if entry[0] > 0][:max_sections]
    if not filtered:
        filtered = scored[:max_sections]
    return [(title, snippet) for _, title, snippet in filtered if snippet]

def load_sds_chunks(list_path: Path) -> list[tuple[str, str, str, str]]:
    entries: list[tuple[str, str, str, str]] = []
    for line in list_path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        parts = line.split('|', 2)
        chunk_path = Path(parts[0].strip())
        label = parts[1].strip() if len(parts) > 1 else ''
        heading = parts[2].strip() if len(parts) > 2 else ''
        if not chunk_path.exists():
            continue
        try:
            content = chunk_path.read_text(encoding='utf-8').strip()
        except Exception:
            continue
        if content:
            entries.append((chunk_path.name, label, heading, content))
    return entries

def choose_sds_chunks(entries: list[tuple[str, str, str, str]], keywords: set[str]) -> tuple[list[str], list[tuple[str, str]], int]:
    if not entries:
        return [], [], 0
    overview_limit = int(os.environ.get("CJT_TASK_SDS_OVERVIEW_LIMIT", "6"))
    chunk_limit = int(os.environ.get("CJT_TASK_SDS_CHUNK_LIMIT", "5"))
    snippet_char_limit = int(os.environ.get("CJT_TASK_SDS_SNIPPET_CHAR_LIMIT", "600"))
    scored = []
    for name, label, heading, content in entries:
        meta = " ".join(filter(None, (name, label, heading)))
        combined = f"{meta}\n{content}"
        score = score_text(combined, keywords)
        scored.append((score, name, label, heading, content))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [entry for entry in scored if entry[0] > 0][:chunk_limit]
    if not selected:
        selected = scored[:chunk_limit]
    overview_entries = selected[:overview_limit]
    prepared: list[tuple[str, str]] = []
    for _, name, label, heading, content in selected:
        ref = f"SDS {label}" if label else (heading or name)
        prepared.append((ref, summarize_text(content, snippet_char_limit)))
    overview_list: list[str] = []
    for _, name, label, heading, _ in overview_entries:
        ref = f"SDS {label}" if label else (heading or name)
        overview_list.append(ref)
    omitted_total = max(0, len(entries) - len(selected))
    return overview_list, prepared, omitted_total

story_keywords = extract_keywords(story)
context_sections = choose_context_sections(context_raw, story_keywords)

sds_overview: list[str] = []
sds_snippets: list[tuple[str, str]] = []
sds_omitted = 0
if sds_chunk_list and sds_chunk_list.exists():
    sds_entries = load_sds_chunks(sds_chunk_list)
    if sds_entries:
        sds_overview, sds_snippets, sds_omitted = choose_sds_chunks(sds_entries, story_keywords)

with prompt_path.open('w', encoding='utf-8') as fh:
    fh.write("You are a delivery engineer decomposing a single user story into actionable Jira tasks.\n\n")
    fh.write("Consider frontend, backend, admin UI, data, security, accessibility, analytics, and QA needs.\n\n")
    fh.write("## User story\n")
    json.dump(story, fh, indent=2)
    fh.write("\n\n")
    fh.write("## Epic context\n")
    json.dump({"epic_id": epic_id}, fh, indent=2)
    fh.write("\n\n")
    fh.write("## Focused project documentation excerpts\n")
    if context_sections:
        for title, snippet in context_sections:
            fh.write(f"### {title}\n")
            fh.write(snippet)
            if not snippet.endswith("\n"):
                fh.write("\n")
            fh.write("\n")
    else:
        fh.write("(No high-confidence documentation sections matched; consult the consolidated context if needed.)\n\n")
    fh.write("## Requirements\n")
    fh.write("- Create tasks that cover sunny day, error handling, edge cases, observability, analytics, and release readiness.\n")
    fh.write("- Assign tasks to the appropriate roles: Architect, Dev/Ops, Project Manager, UI/UX designer, BE dev, FE dev, Test Eng.\n")
    fh.write("- Include dependencies when a task relies on another.\n")
    fh.write("- Add tags such as [Web-FE], [Web-BE], [Admin-FE], [Admin-BE], [API], [DB], [Design], [QA].\n")
    fh.write("- Provide Story points (integer) per task; align with the effort described.\n")
    fh.write("- Reference relevant documentation sections (e.g., 'SDS §10.1.1', 'SQL dump table users').\n")
    fh.write("- Spell out API endpoints, payload structures, data validation, and state transitions.\n")
    fh.write("- Cover testing requirements (unit, integration, E2E).\n")
    fh.write("- Cross-check each detail against the staged PDR, SDS, OpenAPI, SQL, and sample documents; bring the task into alignment with any mismatches you find.\n")
    fh.write("- If information is missing from the task, enrich it with specifics derived from the docs (fields, DB tables, endpoints, validations, RBAC, analytics, etc.).\n")
    fh.write("\n")
    if sds_snippets:
        fh.write("## SDS sections overview\n")
        for ref in sds_overview:
            fh.write(f"- {ref}\n")
        if sds_omitted > 0:
            fh.write(f"- ...(additional {sds_omitted} sections omitted; see full SDS for details)\n")
        fh.write("\n## SDS source snippets\n")
        for ref, snippet in sds_snippets:
            fh.write(f"### {ref}\n")
            fh.write(snippet)
            if not snippet.endswith("\n"):
                fh.write("\n")
            fh.write("\n")
        if sds_omitted > 0:
            fh.write(f"(Additional {sds_omitted} SDS sections not shown; reference the overview and full SDS document for complete context.)\n\n")
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
      task_total=$(python3 - <<'PY' "$working_copy"
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
    local refine_data
    refine_data=$(python3 - <<'PY' "$working_copy" "$refine_mode"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
mode = (sys.argv[2] if len(sys.argv) > 2 else "auto").strip().lower()
payload = json.loads(path.read_text(encoding="utf-8"))
tasks = payload.get("tasks") or []

pending = payload.get("pending_indices")
indices = []
if isinstance(pending, list) and pending:
    for value in pending:
        try:
            idx = int(value)
        except Exception:
            continue
        if 0 <= idx < len(tasks):
            indices.append(idx)
else:
    indices = list(range(len(tasks)))

def normalized_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return [stripped]
    return []

def is_positive(value, zero_ok=False):
    if isinstance(value, (int, float)):
        return value >= 0 if zero_ok else value > 0
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except Exception:
            return False
        return number >= 0 if zero_ok else number > 0
    return False

REQUIRED_TEXT_FIELDS = ("title", "description")
REQUIRED_LIST_FIELDS = (
    "acceptance_criteria",
    "tags",
    "assignees",
    "document_references",
    "endpoints",
    "data_contracts",
    "qa_notes",
)

def needs_refine(task):
    for field in REQUIRED_TEXT_FIELDS:
        if not isinstance(task.get(field), str) or not task.get(field).strip():
            return True
    for field in REQUIRED_LIST_FIELDS:
        if not normalized_list(task.get(field)):
            return True
    if not is_positive(task.get("story_points"), zero_ok=False):
        return True
    if not is_positive(task.get("estimate"), zero_ok=False):
        return True
    return False

mode_map = {
    "auto": "auto",
    "automatic": "auto",
    "all": "all",
    "pending": "pending",
}
mode = mode_map.get(mode, mode)

if mode in {"off", "disabled", "none", "skip", "0"}:
    print("SKIP")
    sys.exit(0)

selected = []
if mode == "all" or mode == "pending":
    selected = indices
else:  # default auto
    for idx in indices:
        task = tasks[idx] if idx < len(tasks) else {}
        if needs_refine(task):
            selected.append(idx)

print(len(indices))
for idx in selected:
    print(idx)
PY
)
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
      for entry in "${story_entries[@]}"; do
        local slug_entry="${entry##*/}"; slug_entry="${slug_entry%.json}"
        local total
        total=$(python3 - <<'PY' "$entry"
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
        if [[ "$(cjt::state_get_refine_progress "$slug_entry" "$total")" != "done" ]]; then
          remaining=1
          break
        fi
      done
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
  local project_name_label="${CJT_PROJECT_TITLE:-the project}"
  CJT_PROMPT_TITLE="$project_name_label" python3 - \
    "$tasks_file" \
    "$task_index" \
    "$CJT_CONTEXT_FILE" \
    "$prompt_file" \
    "${CJT_SDS_CHUNKS_LIST:-}" \
    "${CJT_PDR_PATH:-}" \
    "${CJT_SQL_PATH:-}" \
    "${CJT_TASKS_DB_PATH:-}" <<'PY'
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

tasks_path = Path(sys.argv[1])
task_index = int(sys.argv[2])
context_path = Path(sys.argv[3])
prompt_path = Path(sys.argv[4])
sds_list_path = Path(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] else None
pdr_path = Path(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] else None
sql_path = Path(sys.argv[7]) if len(sys.argv) > 7 and sys.argv[7] else None
db_path = Path(sys.argv[8]) if len(sys.argv) > 8 and sys.argv[8] else None
project_base = os.environ.get("CJT_PROMPT_TITLE", "the project").strip() or "the project"
project_label = f"{project_base} delivery team"

CONTEXT_SECTION_LIMIT = int(os.environ.get("CJT_REFINE_CONTEXT_SECTION_LIMIT", "4"))
CONTEXT_SECTION_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_CONTEXT_SECTION_CHAR_LIMIT", "900"))
PDR_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_PDR_CHAR_LIMIT", "1200"))
SQL_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_SQL_CHAR_LIMIT", "1200"))
SDS_OVERVIEW_LIMIT = int(os.environ.get("CJT_REFINE_SDS_OVERVIEW_LIMIT", "4"))
SDS_CHUNK_LIMIT = int(os.environ.get("CJT_REFINE_SDS_CHUNK_LIMIT", "3"))
SDS_SNIPPET_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_SDS_SNIPPET_CHAR_LIMIT", "450"))
OTHER_TASKS_LIMIT = int(os.environ.get("CJT_REFINE_OTHER_TASKS_LIMIT", "5"))
OTHER_TASKS_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_OTHER_TASKS_CHAR_LIMIT", "160"))

payload = json.loads(tasks_path.read_text(encoding="utf-8"))
tasks = payload.get("tasks") or []
if task_index < 0 or task_index >= len(tasks):
    raise SystemExit(f"Task index {task_index} out of range for {tasks_path}")

target_task = tasks[task_index]
story = payload.get("story") or {}
epic_id = payload.get("epic_id") or story.get("epic_id") or ""
epic_title = payload.get("epic_title") or story.get("epic_title") or ""
story_id = payload.get("story_id") or story.get("story_id") or ""
story_title = payload.get("story_title") or story.get("title") or ""
story_description = story.get("description") or payload.get("story_description") or ""
story_roles = story.get("user_roles") or payload.get("story_roles") or []
story_acceptance = story.get("acceptance_criteria") or payload.get("story_acceptance_criteria") or []
story_slug = payload.get("story_slug") or tasks_path.stem

context_blob = ""
if context_path.exists():
    context_blob = context_path.read_text(encoding="utf-8", errors="ignore")

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "system", "user", "story",
    "should", "will", "must", "allow", "support", "able", "data", "api", "admin",
    "task", "jira"
}

REQUIRED_TEXT_FIELDS = ("title", "description")
REQUIRED_LIST_FIELDS = (
    "acceptance_criteria",
    "tags",
    "assignees",
    "document_references",
    "endpoints",
    "data_contracts",
    "qa_notes",
)

def normalized_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return [stripped]
    return []

def is_positive(value, zero_ok=False):
    if isinstance(value, (int, float)):
        return value >= 0 if zero_ok else value > 0
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except Exception:
            return False
        return number >= 0 if zero_ok else number > 0
    return False

def detect_gaps(task):
    gaps = []
    for field in REQUIRED_TEXT_FIELDS:
        val = task.get(field)
        if not isinstance(val, str) or not val.strip():
            gaps.append(f"{field.replace('_', ' ')} missing or blank")
    for field in REQUIRED_LIST_FIELDS:
        if not normalized_list(task.get(field)):
            gaps.append(f"{field.replace('_', ' ')} missing or empty")
    if not is_positive(task.get("story_points")):
        gaps.append("story_points should be a positive integer (1-13)")
    if not is_positive(task.get("estimate")):
        gaps.append("estimate should be a positive number of hours")
    return gaps

def extract_keywords(story_data, task_data):
    parts = []
    for key in ("title", "narrative", "description"):
        value = story_data.get(key)
        if isinstance(value, str):
            parts.append(value)
    acceptance = story_data.get("acceptance_criteria")
    if isinstance(acceptance, list):
        parts.extend(str(item) for item in acceptance if item)
    for key in ("title", "description", "document_references", "endpoints", "data_contracts", "qa_notes", "tags"):
        value = task_data.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if item)
    joined = " ".join(parts).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9\-_/]{2,}", joined)
    keywords = {token.strip("-_/") for token in tokens if len(token) > 3}
    return {kw for kw in keywords if kw and kw not in STOPWORDS}

def score_text(text, keywords):
    if not text:
        return 0
    lower = text.lower()
    return sum(lower.count(keyword) for keyword in keywords)

def summarize_text(text, char_limit):
    text = text.strip()
    if not text:
        return ""
    if char_limit > 0 and len(text) > char_limit:
        return text[:char_limit].rstrip() + "\n... (truncated; consult source for full details)"
    return text

def parse_context_sections(blob):
    sections = []
    current_title = "Context"
    current_lines = []
    for line in blob.splitlines():
        if line.startswith("----- FILE:"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.split(":", 1)[-1].strip() or "Context"
            current_lines = []
        elif line.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip() or "Context"
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    deduped = []
    seen = set()
    for title, text in sections:
        key = (title, text[:200])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((title, text))
    return deduped

def choose_context_sections(blob, keywords):
    sections = parse_context_sections(blob)
    if not sections:
        return []
    scored = []
    for title, text in sections:
        snippet = summarize_text(text, CONTEXT_SECTION_CHAR_LIMIT)
        score = score_text(text, keywords)
        scored.append((score, title, snippet))
    scored.sort(key=lambda item: item[0], reverse=True)
    filtered = [entry for entry in scored if entry[0] > 0][:CONTEXT_SECTION_LIMIT]
    if not filtered:
        filtered = scored[:CONTEXT_SECTION_LIMIT]
    return [(title, snippet) for _, title, snippet in filtered if snippet]

def load_sds_chunks(list_path):
    if not list_path or not list_path.exists():
        return []
    entries = []
    for line in list_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        chunk_path = Path(parts[0].strip())
        label = parts[1].strip() if len(parts) > 1 else ""
        heading = parts[2].strip() if len(parts) > 2 else ""
        if not chunk_path.exists():
            continue
        try:
            content = chunk_path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if content:
            entries.append((chunk_path.name, label, heading, content))
    return entries

def choose_sds_chunks(entries, keywords):
    if not entries:
        return [], [], 0
    scored = []
    for name, label, heading, content in entries:
        meta = " ".join(filter(None, (name, label, heading)))
        combined = f"{meta}\n{content}"
        score = score_text(combined, keywords)
        scored.append((score, name, label, heading, content))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [entry for entry in scored if entry[0] > 0][:SDS_CHUNK_LIMIT]
    if not selected:
        selected = scored[:SDS_CHUNK_LIMIT]
    overview_entries = selected[:SDS_OVERVIEW_LIMIT]
    prepared = []
    for _, name, label, heading, content in selected:
        ref = f"SDS {label}" if label else (heading or name)
        prepared.append((ref, summarize_text(content, SDS_SNIPPET_CHAR_LIMIT)))
    overview_list = []
    for _, name, label, heading, _ in overview_entries:
        ref = f"SDS {label}" if label else (heading or name)
        overview_list.append(ref)
    omitted_total = max(0, len(entries) - len(selected))
    return overview_list, prepared, omitted_total

def safe_excerpt(path, char_limit):
    if not path or not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""
    if char_limit > 0 and len(text) > char_limit:
        text = text[:char_limit].rstrip() + "\n... (truncated; consult source for full details)"
    return text

def load_other_tasks(db_path, story_slug, current_index):
    if not db_path or not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    lines = []
    try:
        for row in conn.execute(
            "SELECT position, task_id, title, status, dependencies_json FROM tasks WHERE story_slug = ? ORDER BY position",
            (story_slug,),
        ):
            pos = int(row["position"] or 0)
            if pos == current_index:
                continue
            identifier = (row["task_id"] or "").strip() or f"Task #{pos + 1:02d}"
            title = (row["title"] or "").strip() or "Untitled"
            status = (row["status"] or "pending").strip()
            deps_summary = ""
            deps_raw = row["dependencies_json"] or ""
            if deps_raw:
                try:
                    parsed = json.loads(deps_raw)
                    if isinstance(parsed, list) and parsed:
                        deps_summary = ", ".join(str(item).strip() for item in parsed if str(item).strip())
                except Exception:
                    deps_summary = deps_raw
            line = f"- {identifier}: {title} [status: {status}]"
            if deps_summary:
                line += f" (depends on: {deps_summary})"
            if len(line) > OTHER_TASKS_CHAR_LIMIT:
                line = line[:OTHER_TASKS_CHAR_LIMIT].rstrip() + "..."
            lines.append(line)
            if len(lines) >= OTHER_TASKS_LIMIT:
                break
    finally:
        conn.close()
    return lines

def single_line_summary(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "…"
    return text

keywords = extract_keywords(story, target_task)
context_sections = choose_context_sections(context_blob, keywords)

sds_overview = []
sds_snippets = []
sds_omitted = 0
entries = load_sds_chunks(sds_list_path)
if entries:
    sds_overview, sds_snippets, sds_omitted = choose_sds_chunks(entries, keywords)

pdr_excerpt = safe_excerpt(pdr_path, PDR_CHAR_LIMIT)
sql_excerpt = safe_excerpt(sql_path, SQL_CHAR_LIMIT)
other_tasks = load_other_tasks(db_path, story_slug, task_index)
gaps = detect_gaps(target_task)

story_summary = {
    "epic_id": epic_id,
    "epic_title": epic_title,
    "story_id": story_id,
    "story_title": story_title,
    "story_description": story_description,
    "story_roles": story_roles,
    "story_acceptance_criteria": story_acceptance,
}

with prompt_path.open("w", encoding="utf-8") as fh:
    fh.write(f"You are the {project_label}, refining a Jira task so it is implementation-ready.\n")
    fh.write("Fill in missing details using the focused context while preserving correct scope.\n\n")

    fh.write("## Story summary\n")
    json.dump(story_summary, fh, indent=2)
    fh.write("\n\n")

    fh.write("## Focused documentation references\n")
    if context_sections:
        for title, snippet in context_sections:
            summary = single_line_summary(snippet, CONTEXT_SECTION_CHAR_LIMIT)
            fh.write(f"- {title}: {summary}\n")
        fh.write("\n")
    else:
        fh.write("(No high-signal sections detected; reference the consolidated context if needed.)\n\n")

    if pdr_excerpt:
        fh.write("## PDR reference\n")
        fh.write(f"- {single_line_summary(pdr_excerpt, PDR_CHAR_LIMIT)}\n\n")

    if sql_excerpt:
        fh.write("## Database schema reference\n")
        fh.write(f"- {single_line_summary(sql_excerpt, SQL_CHAR_LIMIT)}\n\n")

    if sds_snippets:
        fh.write("## SDS references\n")
        for ref in sds_overview:
            fh.write(f"- {ref}\n")
        if sds_omitted > 0:
            fh.write(f"- ...(additional {sds_omitted} sections omitted; consult full SDS)\n")
        for ref, snippet in sds_snippets:
            summary = single_line_summary(snippet, SDS_SNIPPET_CHAR_LIMIT)
            fh.write(f"  - {ref}: {summary}\n")
        fh.write("\n")

    if other_tasks:
        fh.write("## Related tasks in backlog\n")
        fh.write("Align dependencies, naming, and scope with these existing tasks.\n")
        fh.write("\n".join(other_tasks))
        fh.write("\n\n")

    fh.write("## Current task draft\n")
    json.dump(target_task, fh, indent=2)
    fh.write("\n\n")

    if gaps:
        fh.write("## Gaps detected\n")
        for gap in gaps:
            fh.write(f"- {gap}\n")
        fh.write("\n")

    fh.write("## Requirements\n")
    fh.write("- Preserve the task ID and keep existing accurate details; enrich missing or incorrect fields.\n")
    fh.write("- Ground updates in the provided documentation, PDR, SDS snippets, schema excerpt, and backlog snapshot.\n")
    fh.write("- Cover sunny-day, error, and edge-case flows plus observability, analytics, QA, security, and policy impacts.\n")
    fh.write("- Provide explicit endpoints, payload contracts, database tables/indexes, caching/idempotency, RBAC, analytics, and rate limits when relevant.\n")
    fh.write("- Use approved assignee roles (Architect, Dev/Ops, Project Manager, UI/UX designer, BE dev, FE dev, Test Eng) and tags ([Web-FE], [Web-BE], [Admin-FE], [Admin-BE], [API], [DB], [Design], [QA], etc.).\n")
    fh.write("- Supply integer story_points (1..13) and realistic hour estimates; adjust dependencies when needed.\n")
    fh.write("- Return strictly valid JSON with no markdown fences or commentary outside the JSON object.\n\n")

    task_id = target_task.get("id") or target_task.get("task_id") or "TASK-ID"
    fh.write("## Output JSON schema\n")
    fh.write(
        "{\n"
        "  \"task\": {\n"
        f"    \"id\": \"{task_id}\",\n"
        "    \"title\": \"...\",\n"
        "    \"description\": \"...\",\n"
        "    \"acceptance_criteria\": [\"...\"],\n"
        "    \"tags\": [\"Web-FE\"],\n"
        "    \"assignees\": [\"FE dev\"],\n"
        "    \"estimate\": 5,\n"
        "    \"story_points\": 5,\n"
        "    \"dependencies\": [\"WEB-01-T00\"],\n"
        "    \"document_references\": [\"SDS §10.1.1\"],\n"
        "    \"endpoints\": [\"GET /api/v1/...\"],\n"
        "    \"data_contracts\": [\"Request payload...\"],\n"
        "    \"qa_notes\": [\"Tests...\"],\n"
        "    \"analytics\": [\"Events...\"],\n"
        "    \"observability\": [\"Metrics...\"],\n"
        "    \"user_roles\": [\"Visitor\"],\n"
        "    \"policy\": [\"RBAC mapping...\"],\n"
        "    \"idempotency\": \"Describe behaviour...\",\n"
        "    \"rate_limits\": \"Document limits...\"\n"
        "  }\n"
        "}\n"
    )
    fh.write("Return strictly valid JSON only.\n")
PY
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
  python3 - "$working_json" "$refined_json" "$task_index" <<'PY'
import json
import os
import sys
from datetime import datetime
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

dry_run = os.environ.get('CJT_DRY_RUN', '0') == '1'
if not dry_run:
    existing['refined'] = 1
    existing['refined_at'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

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
