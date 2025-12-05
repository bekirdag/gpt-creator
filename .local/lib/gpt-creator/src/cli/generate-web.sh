#!/usr/bin/env bash
# gpt-creator :: generate-web — uses the active adapter to scaffold Vue 3 website (Vite) from UI pages + samples + style
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
: "${ADAPTER_CMD:=${CODEX_CMD:-codex}}"
: "${ADAPTER_NAME:=${GC_ACTIVE_AGENT_ADAPTER:-${CODEX_ADAPTER:-codex_cli}}}"
: "${STAGING_DIR:=${PROJECT_ROOT}/.gpt-creator/staging}"
: "${WORK_DIR:=${PROJECT_ROOT}/.gpt-creator/staging/generate-web}"
: "${WEB_DIR:=${PROJECT_ROOT}/apps/web}"

mkdir -p "${WORK_DIR}/prompts" "${WEB_DIR}"

STYLE_CSS="${STYLE_CSS:-}"
SAMPLES_DIR="${SAMPLES_DIR:-}"
UI_DOC="${UI_DOC:-}"

INSTALL_DEPS=1

show_help() {
  env \
    GEN_WEB_OUT_DEFAULT="${WEB_DIR}" \
    gc_cli_render_template "help/generate_web_usage.txt"
}

# Arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --style) STYLE_CSS="$2"; shift 2 ;;
    --samples) SAMPLES_DIR="$2"; shift 2 ;;
    --ui-doc) UI_DOC="$2"; shift 2 ;;
    --out)
      mkdir -p "$2"
      WEB_DIR="$(cd "$2" && pwd)"
      shift 2 ;;
    --no-install) INSTALL_DEPS=0; shift ;;
    -n|--dry-run) GC_DRY_RUN=1; shift ;;
    -h|--help) show_help; exit 0 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

# Discover defaults
if [[ -z "$STYLE_CSS" ]]; then
  STYLE_CSS="$(resolve_doc "${STAGING_DIR}/page_samples/style.css" '*style*.css' '*style*sheet*.md')"
fi

[[ -n "$SAMPLES_DIR" ]] || for cand in \
   "${STAGING_DIR}/page_samples" \
   "${PROJECT_ROOT}/page_samples"
do [[ -d "$cand" ]] && SAMPLES_DIR="$cand" && break; done

if [[ -z "$UI_DOC" ]]; then
  UI_DOC="$(resolve_doc "${STAGING_DIR}/ui-pages.md" '*ui*pages*.md' '*website*ui*pages*.md')"
fi

[[ -f "$UI_DOC" ]] || die "UI pages doc not found. Set --ui-doc."
[[ -d "$SAMPLES_DIR" ]] || log_warn "Sample HTML directory not found; proceeding without."
[[ -f "$STYLE_CSS" ]] || log_warn "Style CSS/tokens not found; proceeding without."

PROMPT_FILE="${WORK_DIR}/prompts/generate-web.prompt.md"
env \
  GEN_WEB_UI_DOC="${UI_DOC}" \
  GEN_WEB_STYLE="${STYLE_CSS:-<none>}" \
  GEN_WEB_SAMPLES="${SAMPLES_DIR:-<none>}" \
  gc_cli_render_template "prompts/generate_web.prompt.md.tmpl" > "$PROMPT_FILE"

log_info "Prepared adapter prompt → $PROMPT_FILE"
log_info "Output directory       → $WEB_DIR"

mkdir -p "$WEB_DIR"

run_adapter() {
  local prompt="$1"
  local out="$2"
  local out_md="${out}/adapter.out.md"
  if [[ -n "${GC_DRY_RUN:-}" ]]; then
    log_info "[dry-run] Skipping model invocation; prompt at ${prompt}"
    printf '{"status":"dry-run","label":"generate-web"}\n' > "${out}/adapter.out.json"
    return 0
  fi
  case "${ADAPTER_NAME}" in
    command)
      log_info "Running command adapter for web generation (cmd='${ADAPTER_MODEL}')"
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

run_adapter "$PROMPT_FILE" "$WEB_DIR"

if [[ "${INSTALL_DEPS}" -eq 1 && -z "${GC_DRY_RUN:-}" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$WEB_DIR" && pnpm install)
    (cd "$WEB_DIR" && pnpm build || true)
  else
    log_warn "pnpm not found; skipping install/build."
  fi
fi

if [[ -s "${WEB_DIR}/adapter.out.md" ]]; then
  log_info "Web generation script finished."
else
  die "Web generation did not produce adapter.out.md in ${WEB_DIR}; check logs above."
fi
