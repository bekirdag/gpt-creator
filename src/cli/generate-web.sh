#!/usr/bin/env bash
# gpt-creator :: generate-web — uses Codex to scaffold Vue 3 website (Vite) from UI pages + samples + style
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
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

: "${PROJECT_ROOT:=${ROOT_DIR}}"
: "${CODEX_MODEL:=gpt-5-high}"
: "${CODEX_CMD:=codex}"
: "${STAGING_DIR:=${PROJECT_ROOT}/.gpt-creator/staged}"
: "${WORK_DIR:=${PROJECT_ROOT}/.gpt-creator/work}"
: "${WEB_DIR:=${PROJECT_ROOT}/apps/web}"

mkdir -p "${WORK_DIR}/prompts" "${WEB_DIR}"

STYLE_CSS="${STYLE_CSS:-}"
SAMPLES_DIR="${SAMPLES_DIR:-}"
UI_DOC="${UI_DOC:-}"

INSTALL_DEPS=1

show_help() {
  (
    set -a
    GEN_WEB_OUT_DEFAULT="${WEB_DIR}"
    set +a
    gc_cli_render_template "help/generate_web_usage.txt"
  )
}

# Arg parse
while [[ $# -gt 0 ]]; do
  case "$1" in
    --style) STYLE_CSS="$2"; shift 2 ;;
    --samples) SAMPLES_DIR="$2"; shift 2 ;;
    --ui-doc) UI_DOC="$2"; shift 2 ;;
    --out) WEB_DIR="$(cd "$2" && pwd)"; shift 2 ;;
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
(
  set -a
  GEN_WEB_UI_DOC="${UI_DOC}"
  GEN_WEB_STYLE="${STYLE_CSS:-<none>}"
  GEN_WEB_SAMPLES="${SAMPLES_DIR:-<none>}"
  set +a
  gc_cli_render_template "prompts/generate_web.prompt.md.tmpl"
) > "$PROMPT_FILE"

log_info "Prepared Codex prompt → $PROMPT_FILE"
log_info "Output directory       → $WEB_DIR"

mkdir -p "$WEB_DIR"

run_codex() {
  local prompt="$1"
  local out="$2"
  if [[ -n "${GC_DRY_RUN:-}" ]]; then
    log_info "[dry-run] Would call Codex ${CODEX_CMD} --model ${CODEX_MODEL}"
    return 0
  fi
  if command -v "${CODEX_CMD}" >/dev/null 2>&1; then
    if "${CODEX_CMD}" --help 2>/dev/null | grep -qi "chat"; then
      "${CODEX_CMD}" chat --model "${CODEX_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
    else
      "${CODEX_CMD}" generate --model "${CODEX_MODEL}" --prompt-file "${prompt}" --out-dir "${out}"
    fi
  else
    die "Codex CLI not found: ${CODEX_CMD}. Set CODEX_CMD or install client."
  fi
}

run_codex "$PROMPT_FILE" "$WEB_DIR"

if [[ "${INSTALL_DEPS}" -eq 1 && -z "${GC_DRY_RUN:-}" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$WEB_DIR" && pnpm install)
    (cd "$WEB_DIR" && pnpm build || true)
  else
    log_warn "pnpm not found; skipping install/build."
  fi
fi

log_info "Web generation script finished."
