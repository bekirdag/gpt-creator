#!/usr/bin/env bash
# gpt-creator · generate-db.sh
# Generate DB layer (Prisma by default) from an existing MySQL DB or SQL dump.
# Falls back to adapter-assisted generation if introspection isn't available.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  CODEX_MODEL="${CODEX_MODEL:-gpt-5.1-codex}"
  log(){ printf "[generate-db] %s\n" "$*"; }
  die(){ printf "[generate-db][ERROR] %s\n" "$*" >&2; exit 1; }
fi

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing dependency: $1"; }

gc_clone_python_tool() {
  local script_name="${1:?python script name required}"
  local root="${2:-${PROJECT_ROOT:-${ROOT_DIR:-$PWD}}}"
  local cli_root="${GC_ROOT:-${CLI_ROOT:-$ROOT_DIR}}"
  local scripts_root="${GC_SCRIPTS_ROOT:-${cli_root}/scripts}"

  if [[ -z "$root" ]]; then
    die "Unable to determine project root while preparing ${script_name}"
  fi

  local source_path="${scripts_root}/python/${script_name}"
  if [[ ! -f "$source_path" ]]; then
    die "Python helper missing at ${source_path}"
  fi

  local target_dir="${root}/${GC_WORK_DIR_NAME:-.gpt-creator}/shims/python"
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
  helper_path="$(gc_clone_python_tool "humanize_name.py" "$PROJECT_ROOT")" || return 1
  python3 "$helper_path" "${1:-}"
}

usage() {
  (
    set -a
    # shellcheck disable=SC2034
    GEN_DB_CODEX_MODEL_DEFAULT="${ADAPTER_MODEL:-gpt-5.1-codex}"
    set +a
    gc_cli_render_template "help/generate_db_usage.txt"
  )
}

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ORM="prisma"
DB_URL="${DATABASE_URL:-}"
SQL_DUMP=""
OUT_DIR="apps/api"
MODEL="${ADAPTER_MODEL:-gpt-5.1-codex}"
: "${ADAPTER_NAME:=${GC_ACTIVE_AGENT_ADAPTER:-${CODEX_ADAPTER:-codex_cli}}}"
: "${ADAPTER_MODEL:=${GC_ACTIVE_MODEL:-${DEFAULT_LLM:-${CODEX_MODEL:-gpt-5.1-codex}}}}"
: "${ADAPTER_CMD:=${CODEX_BIN:-codex}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --orm) ORM="${2:-}"; shift 2;;
    --db-url) DB_URL="${2:-}"; shift 2;;
    --sql) SQL_DUMP="${2:-}"; shift 2;;
    --out) OUT_DIR="${2:-}"; shift 2;;
    --model) MODEL="${2:-}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

if [[ -n "${GC_PROJECT_TITLE:-}" ]]; then
  PROJECT_LABEL="$GC_PROJECT_TITLE"
else
  PROJECT_LABEL="$(humanize_name "$PROJECT_ROOT")"
fi
[[ -n "$PROJECT_LABEL" ]] || PROJECT_LABEL="Project"
project_label_lower="$(printf '%s' "$PROJECT_LABEL" | tr '[:upper:]' '[:lower:]')"
if [[ "$project_label_lower" == "project" ]]; then
  PROJECT_LABEL_PROMPT="this project"
else
  PROJECT_LABEL_PROMPT="the ${PROJECT_LABEL}"
fi

API_DIR="${PROJECT_ROOT}/${OUT_DIR}"
PRISMA_DIR="${API_DIR}/prisma"
mkdir -p "${PRISMA_DIR}"

log "Target ORM : ${ORM}"
log "API dir    : ${API_DIR}"
[[ -n "${DB_URL}" ]] && log "DB URL     : (provided)" || true
[[ -n "${SQL_DUMP}" ]] && log "SQL dump   : ${SQL_DUMP}" || true

pnpm_or_npx() {
  if command -v pnpm >/dev/null 2>&1; then pnpm dlx "$@"; else npx "$@"; fi
}

try_mysql_ping() {
  if [[ -z "${DB_URL}" ]]; then return 1; fi
  if ! command -v mysql >/dev/null 2>&1; then return 1; fi
  local proto="${DB_URL%%://*}"
  [[ "${proto}" != "mysql" ]] && return 1
  local rest="${DB_URL#mysql://}"
  local userpass="${rest%%@*}"; local hostportdb="${rest#*@}"
  local user="${userpass%%:*}"; local pass="${userpass#*:}"
  local host="${hostportdb%%:*}"; local portdb="${hostportdb#*:}"
  local port="${portdb%%/*}"; local db="${portdb#*/}"
  MYSQL_PWD="${pass}" mysql -u "${user}" -h "${host}" -P "${port}" -e "USE \`${db}\`; SELECT 1;" >/dev/null 2>&1
}

# Step 0: optional SQL import (via db.sh)
if [[ -n "${SQL_DUMP}" ]]; then
  [[ -f "${SQL_DUMP}" ]] || die "SQL dump not found: ${SQL_DUMP}"
  log "Importing SQL dump via db.sh ..."
  bash "${ROOT_DIR}/src/cli/db.sh" import "${SQL_DUMP}" || die "Import failed"
  if [[ -f "${ROOT_DIR}/.env.local" ]]; then
    # shellcheck disable=SC1090
    source "${ROOT_DIR}/.env.local"
    DB_URL="${DATABASE_URL:-${DB_URL}}"
    [[ -n "${DB_URL}" ]] && log "Discovered DATABASE_URL from .env.local"
  fi
fi

case "${ORM}" in
  prisma)
    need_cmd node
    if [[ ! -f "${PRISMA_DIR}/schema.prisma" ]]; then
      log "Bootstrapping Prisma schema (placeholder)"
      gc_cli_render_template "generate/prisma_placeholder.schema.prisma" > "${PRISMA_DIR}/schema.prisma"
    fi
    if try_mysql_ping; then
      log "Introspecting database → Prisma schema"
      ( cd "${API_DIR}" && DATABASE_URL="${DB_URL}" pnpm_or_npx prisma@5 db pull )
      log "Generating Prisma client"
      ( cd "${API_DIR}" && DATABASE_URL="${DB_URL}" pnpm_or_npx prisma@5 generate )
      log "Done. Prisma schema at: ${PRISMA_DIR}/schema.prisma"
      exit 0
    fi
    log "DB not reachable. Falling back to adapter-assisted schema synthesis."
    ;;
  typeorm)
    log "TypeORM selected. Proceeding with adapter-assisted entity synthesis."
    ;;
  *)
    die "Unsupported ORM: ${ORM}"
    ;;
esac

# Step 2: Adapter-assisted synthesis (fallback)

PROMPT_DIR="${PROJECT_ROOT}/${GC_WORK_DIR_NAME:-.gpt-creator}/prompts"
mkdir -p "${PROMPT_DIR}"

gc_cli_render_template "prompts/generate_db.system.md" > "${PROMPT_DIR}/db.system.md"

  (
    set -a
    # shellcheck disable=SC2034
    GEN_DB_PROJECT_LABEL="${PROJECT_LABEL_PROMPT}"
    set +a
    gc_cli_render_template "prompts/generate_db.task.md.tmpl"
  ) > "${PROMPT_DIR}/db.task.md"

# Collect likely inputs
ATTACH=()
add_if() { [[ -f "$1" ]] && ATTACH+=("$1"); }
STAGING_ROOT="${PROJECT_ROOT}/${GC_WORK_DIR_NAME:-.gpt-creator}/staging"
if [[ -d "$STAGING_ROOT" ]]; then
  for candidate in     "$STAGING_ROOT/docs/pdr.md"     "$STAGING_ROOT/docs/sds.md"     "$STAGING_ROOT/docs/rfp.md"     "$STAGING_ROOT/docs/jira.md"     "$STAGING_ROOT/docs/ui-pages.md"; do
    add_if "$candidate"
  done
  for f in "$STAGING_ROOT"/openapi/* "$STAGING_ROOT"/sql/* "$STAGING_ROOT"/diagrams/*; do
    [[ -f "$f" ]] || continue
    add_if "$f"
  done
fi

if (( ${#ATTACH[@]} == 0 )); then
  while IFS= read -r -d '' f; do
    add_if "$f"
  done < <(find "$ROOT_DIR" -maxdepth 2 -type f \
    \( -iname '*pdr*.md' -o -iname '*sds*.md' -o -iname '*rfp*.md' -o -iname '*jira*.md' \
       -o -iname 'openapi.yaml' -o -iname 'openapi.yml' -o -iname 'openapi.json' \
       -o -iname '*.sql' -o -iname '*.mmd' \) -print0)
fi

if (( ${#ATTACH[@]} > 0 )); then
  mapfile -t ATTACH < <(printf '%s\n' "${ATTACH[@]}" | awk '!seen[$0]++')
fi

log "Attachments discovered: ${#ATTACH[@]} file(s)"

# Try a generic adapter call (command adapter, adapter CLI, or llm_client_factory)
OUT_SYNTH="${PRISMA_DIR}/schema.prisma"
COMBINED_PROMPT="$(mktemp "${PROMPT_DIR}/db.combined.XXXXXX")"
cat "${PROMPT_DIR}/db.system.md" "${PROMPT_DIR}/db.task.md" > "${COMBINED_PROMPT}"
if (( ${#ATTACH[@]} > 0 )); then
  printf "\n\n## Attachments (paths)\n" >> "${COMBINED_PROMPT}"
  printf -- "- %s\n" "${ATTACH[@]}" >> "${COMBINED_PROMPT}"
fi

case "${ADAPTER_NAME}" in
  command)
    log "Running command adapter to synthesize ORM schema (cmd='${MODEL}') → ${OUT_SYNTH}"
    if eval "${MODEL} < \"${COMBINED_PROMPT}\" > \"${OUT_SYNTH}\""; then
      log "Adapter wrote: ${OUT_SYNTH}"
      rm -f "${COMBINED_PROMPT}"
      exit 0
    fi
    rm -f "${COMBINED_PROMPT}"
    die "Command adapter failed to synthesize schema."
    ;;
  codex_cli|openai_cli|openai)
    command -v "${ADAPTER_CMD}" >/dev/null 2>&1 || die "Adapter CLI not found (set ADAPTER_CMD/CODEX_BIN)."
    log "Invoking adapter=${ADAPTER_NAME} model=${MODEL} to synthesize ORM schema → ${OUT_SYNTH}"
    if [[ "${ADAPTER_NAME}" == "codex_cli" ]]; then
      if "${ADAPTER_CMD}" chat --model "${MODEL}" --system-file "${PROMPT_DIR}/db.system.md" --input-file "${PROMPT_DIR}/db.task.md" "${ATTACH[@]/#/--file=}" > "${OUT_SYNTH}"; then
        log "Adapter wrote: ${OUT_SYNTH}"
        rm -f "${COMBINED_PROMPT}"
        exit 0
      fi
    else
      if "${ADAPTER_CMD}" exec --model "${MODEL}" < "${COMBINED_PROMPT}" > "${OUT_SYNTH}"; then
        log "Adapter wrote: ${OUT_SYNTH}"
        rm -f "${COMBINED_PROMPT}"
        exit 0
      fi
    fi
    die "Adapter CLI invocation failed."
    ;;
  *)
    if [[ -z "${GC_SCRIPTS_ROOT:-}" ]]; then
      die "GC_SCRIPTS_ROOT not set; cannot locate llm client for adapter '${ADAPTER_NAME}'."
    fi
    local_py_path="${GC_SCRIPTS_ROOT}/python"
    log "Invoking adapter=${ADAPTER_NAME} model=${MODEL} via llm_client_factory → ${OUT_SYNTH}"
    local llm_helper="${GC_SCRIPTS_ROOT:-${ROOT_DIR}/scripts}/python/llm_client_prompt_to_file.py"
    [[ -f "$llm_helper" ]] || llm_helper="${ROOT_DIR}/tools/scripts/python/llm_client_prompt_to_file.py"
    PYTHONPATH="${local_py_path}:${PYTHONPATH:-}" "${PYTHON_BIN:-python3}" "$llm_helper" "$ADAPTER_NAME" "$MODEL" "$COMBINED_PROMPT" "$OUT_SYNTH"
    rm -f "${COMBINED_PROMPT}"
    log "Adapter wrote: ${OUT_SYNTH}"
    ;;
esac
