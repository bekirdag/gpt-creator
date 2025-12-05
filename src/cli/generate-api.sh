#!/usr/bin/env bash
# gpt-creator :: generate-api — uses the active adapter to scaffold NestJS API from OpenAPI + docs
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

# shellcheck disable=SC1091
if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  source "${ROOT_DIR}/src/constants.sh"
fi

type log_info >/dev/null 2>&1 || log_info(){ printf "[%s] \033[1mINFO\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_warn >/dev/null 2>&1 || log_warn(){ printf "[%s] \033[33mWARN\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_err  >/dev/null 2>&1 || log_err(){  printf "[%s] \033[31mERROR\033[0m %s\n" "$(date +%H:%M:%S)" "$*" >&2; }
type die      >/dev/null 2>&1 || die(){ log_err "$*"; exit 1; }

resolve_doc() {
  local primary="$1"; shift
  if [[ -f "$primary" ]]; then
    printf '%s\n' "$primary"
    return
  fi
  local pattern candidate
  for pattern in "$@"; do
    candidate="$(find "$PROJECT_ROOT" -maxdepth 2 -type f -iname "$pattern" 2>/dev/null | head -n1)"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '\n'
}

: "${PROJECT_ROOT:=${PWD}}"
# Use the standard CLI default model.
: "${ADAPTER_MODEL:=${GC_ACTIVE_MODEL:-${DEFAULT_LLM:-${CODEX_MODEL:-gpt-5.1-codex}}}}"
: "${ADAPTER_NAME:=${GC_ACTIVE_AGENT_ADAPTER:-${CODEX_ADAPTER:-codex_cli}}}"
: "${ADAPTER_CMD:=${CODEX_CMD:-codex}}"
: "${STAGING_DIR:=${PROJECT_ROOT}/.gpt-creator/staging}"
: "${WORK_DIR:=${PROJECT_ROOT}/.gpt-creator/staging/generate-api}"
: "${API_DIR:=${PROJECT_ROOT}/apps/api}"

mkdir -p "${WORK_DIR}/prompts" "${API_DIR}"

OPENAPI_PATH="${OPENAPI_PATH:-}"
OUT_DIR="${API_DIR}"
INSTALL_DEPS=1

show_help() {
  (
    set -a
    # shellcheck disable=SC2034
    GEN_API_OUT_DEFAULT="${OUT_DIR}"
    set +a
    gc_cli_render_template "help/generate_api_usage.txt"
  )
}

# Arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --openapi) OPENAPI_PATH="$2"; shift 2 ;;
    --out)
      mkdir -p "$2"
      OUT_DIR="$(cd "$2" && pwd)"
      shift 2
      ;;
    --no-install) INSTALL_DEPS=0; shift ;;
    -n|--dry-run) GC_DRY_RUN=1; shift ;;
    -h|--help) show_help; exit 0 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

# Discover OpenAPI spec if not provided
if [[ -z "${OPENAPI_PATH}" ]]; then
  for cand in \
      "${STAGING_DIR}/openapi.yaml" \
      "${STAGING_DIR}/openapi.yml" \
      "${STAGING_DIR}/openapi.json" \
      "${STAGING_DIR}/openAPI.txt" \
      "${PROJECT_ROOT}/openapi.yaml" \
      "${PROJECT_ROOT}/openAPI.txt"
  do
    [[ -f "$cand" ]] && OPENAPI_PATH="$cand" && break
  done
fi

[[ -f "${OPENAPI_PATH}" ]] || die "OpenAPI not found. Looked for staged openapi.*; set --openapi."

# Collect context document paths (best-effort)
PDR="$(resolve_doc "${STAGING_DIR}/pdr.md" '*pdr*.md')"; PDR="${PDR:-<missing>}"
SDS="$(resolve_doc "${STAGING_DIR}/sds.md" '*sds*.md' '*system*design*spec*.md')"; SDS="${SDS:-<missing>}"
RFP="$(resolve_doc "${STAGING_DIR}/rfp.md" '*rfp*.md' '*request*for*proposal*.md')"; RFP="${RFP:-<missing>}"
IA="$(resolve_doc "${STAGING_DIR}/ui-pages.md" '*ui*pages*.md' '*website*ui*pages*.md')"; IA="${IA:-<missing>}"
SQL="$(resolve_doc "${STAGING_DIR}/schema.sql" '*schema.sql' '*sql_dump*.sql' '*.sql')"; SQL="${SQL:-<missing>}"

PROMPT_FILE="${WORK_DIR}/prompts/generate-api.prompt.md"

(
  set -a
  export GEN_API_OPENAPI="${OPENAPI_PATH}"
  export GEN_API_PDR="${PDR}"
  export GEN_API_SDS="${SDS}"
  export GEN_API_IA="${IA}"
  export GEN_API_RFP="${RFP}"
  export GEN_API_SQL="${SQL}"
  set +a
  gc_cli_render_template "prompts/generate_api.prompt.md.tmpl"
) > "$PROMPT_FILE"

log_info "Prepared adapter prompt → $PROMPT_FILE"
log_info "Output directory         → $OUT_DIR"

mkdir -p "$OUT_DIR"

# Wrapper to invoke the active adapter and capture output.
run_adapter() {
  local prompt="$1"
  local out="$2"
  local out_md="${out}/adapter.out.md"
  if [[ -n "${GC_DRY_RUN:-}" ]]; then
    log_info "[dry-run] Skipping model invocation; prompt at ${prompt}"
    printf '{"status":"dry-run","label":"generate-api"}\n' > "${out}/adapter.out.json"
    return 0
  fi
  case "${ADAPTER_NAME}" in
    command)
      log_info "Running command adapter for API generation (cmd='${ADAPTER_MODEL}')"
      eval "${ADAPTER_MODEL} < \"${prompt}\" > \"${out_md}\""
      ;;
    codex_cli|openai_cli|openai)
      if ! command -v "${ADAPTER_CMD}" >/dev/null 2>&1; then
        die "Adapter CLI not found: ${ADAPTER_CMD}. Set ADAPTER_CMD/CODEX_CMD or install client."
      fi
      if [[ "${ADAPTER_NAME}" == "codex_cli" ]]; then
        if "${ADAPTER_CMD}" --help 2>/dev/null | grep -qi "exec"; then
          "${ADAPTER_CMD}" exec --model "${ADAPTER_MODEL}" < "${prompt}" > "${out_md}"
        else
          "${ADAPTER_CMD}" chat --model "${ADAPTER_MODEL}" --prompt-file "${prompt}" --out-dir "${out}" || \
            "${ADAPTER_CMD}" generate --model "${ADAPTER_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
          [[ -f "${out}/output.md" ]] && cp "${out}/output.md" "${out_md}"
        fi
      else
        "${ADAPTER_CMD}" exec --model "${ADAPTER_MODEL}" < "${prompt}" > "${out_md}"
      fi
      ;;
    *)
      local llm_helper="${GC_SCRIPTS_ROOT:-${ROOT_DIR}/scripts}/python/llm_client_prompt_to_file.py"
      [[ -f "$llm_helper" ]] || llm_helper="${ROOT_DIR}/tools/scripts/python/llm_client_prompt_to_file.py"
      PYTHONPATH="${GC_SCRIPTS_ROOT:-${ROOT_DIR}/scripts}/python:${PYTHONPATH:-}" \
        "${PYTHON_BIN:-python3}" "$llm_helper" "$ADAPTER_NAME" "$ADAPTER_MODEL" "$prompt" "$out_md"
      ;;
  esac
  log_info "Adapter output saved → ${out_md}"
}

run_adapter "$PROMPT_FILE" "$OUT_DIR"

if [[ "${INSTALL_DEPS}" -eq 1 && -z "${GC_DRY_RUN:-}" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$OUT_DIR" && pnpm install)
    (cd "$OUT_DIR" && pnpm build || true)
  else
    log_warn "pnpm not found; skipping install/build."
  fi
fi

if [[ -s "${OUT_DIR}/adapter.out.md" ]]; then
  log_info "API generation script finished."
else
  die "API generation did not produce adapter.out.md in ${OUT_DIR}; check logs above."
fi
