#!/usr/bin/env bash
# gpt-creator :: generate-web — uses Codex to scaffold Vue 3 website (Vite) from UI pages + samples + style
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck disable=SC1091
if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  source "${ROOT_DIR}/src/constants.sh"
fi

type log_info >/dev/null 2>&1 || log_info(){ printf "[%s] \033[1mINFO\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_warn >/dev/null 2>&1 || log_warn(){ printf "[%s] \033[33mWARN\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_err  >/dev/null 2>&1 || log_err(){  printf "[%s] \033[31mERROR\033[0m %s\n" "$(date +%H:%M:%S)" "$*" >&2; }
type die      >/dev/null 2>&1 || die(){ log_err "$*"; exit 1; }

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
  cat <<EOF
generate-web — scaffold Vue 3 public website (Vite)

Usage:
  gpt-creator generate web [options]

Options:
  --style <file>       Path to site CSS (e.g., bhavani.css or style_sheet.md tokens)
  --samples <dir>      Path to page_samples directory (with *.html)
  --ui-doc <file>      Path to "Yoga website UI pages.md"
  --out <dir>          Output directory (default: ${WEB_DIR})
  --no-install         Skip pnpm install/build
  -n, --dry-run        Create prompt only; do not call Codex
  -h, --help           Show help
EOF
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
[[ -n "$STYLE_CSS" ]] || for cand in \
   "${STAGING_DIR}/page_samples/style.css" \
   "${PROJECT_ROOT}/page_samples/style.css" \
   "${PROJECT_ROOT}/bhavani.css" \
   "${PROJECT_ROOT}/style_sheet.md"
do [[ -f "$cand" ]] && STYLE_CSS="$cand" && break; done

[[ -n "$SAMPLES_DIR" ]] || for cand in \
   "${STAGING_DIR}/page_samples" \
   "${PROJECT_ROOT}/page_samples"
do [[ -d "$cand" ]] && SAMPLES_DIR="$cand" && break; done

[[ -n "$UI_DOC" ]] || for cand in \
   "${STAGING_DIR}/ui-pages.md" \
   "${PROJECT_ROOT}/Yoga website UI pages.md"
do [[ -f "$cand" ]] && UI_DOC="$cand" && break; done

[[ -f "$UI_DOC" ]] || die "UI pages doc not found. Set --ui-doc."
[[ -d "$SAMPLES_DIR" ]] || log_warn "Sample HTML directory not found; proceeding without."
[[ -f "$STYLE_CSS" ]] || log_warn "Style CSS/tokens not found; proceeding without."

PROMPT_FILE="${WORK_DIR}/prompts/generate-web.prompt.md"

cat > "$PROMPT_FILE" <<'PROMPT'
System:
You are Codex (gpt-5-high) generating a production-ready Vue 3 + Vite website aligned with the UI pages spec. Implement routes, components, AA accessibility, and URL-synced filters for Program. Use the provided style sheet/tokens; incorporate sample HTML as reference when shaping components.

Context:
- UI Pages spec: {{UI_DOC}}
- Style / tokens: {{STYLE_CSS}}
- Sample pages (if present): {{SAMPLES_DIR}}

Deliverables (write to WEB_DIR):
- Vite + Vue 3 project with router and Pinia.
- Routes per IA: /, /uyelikler, /program (filters ?tur & ?uzman), /etkinlikler (+ /etkinlikler/arsiv), /genel-bilgiler, /hakkimizda, /uzmanlar, /is-birlikleri, /iletisim, /giris, /kayit, /sifre-sifirla, /uye/* tabs, /gizlilik, /kvkk, /sartlar, 404/500.
- Components: Header, MobileDrawer, Footer (legal links + newsletter), ProgramTable (desktop) + ProgramCards (mobile), FilterChips, EventCards, Forms (Auth/Contact/Newsletter), Dashboard tabs.
- Accessibility: WCAG 2.2 AA focus rings, labels, keyboard traversal; ARIA landmarks.
- SEO: per-route title/meta; sitemap.xml & robots.txt generation; OG defaults.
- API integration: fetch from /api/v1 endpoints with typed client; env-configured base URL.
- Styling: map tokens to CSS variables; include provided CSS; keep it lightweight (Tailwind optional but not required).
- Dockerfile (nginx for static hosting) + compose fragment for 'web'.
- README with run/build instructions.

Write files only—no commentary.
PROMPT

sed -i \
  -e "s#{{UI_DOC}}#${UI_DOC}#g" \
  -e "s#{{STYLE_CSS}}#${STYLE_CSS:-<none>}#g" \
  -e "s#{{SAMPLES_DIR}}#${SAMPLES_DIR:-<none>}#g" \
  "$PROMPT_FILE"

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
