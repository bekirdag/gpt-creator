#!/usr/bin/env bash
# gpt-creator :: generate orchestrator
# Usage: gpt-creator generate [all|api|web|admin] [options]
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck disable=SC1091
if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  source "${ROOT_DIR}/src/constants.sh"
fi

# Fallback lightweight log helpers if constants.sh didn't define them
type log_info >/dev/null 2>&1 || log_info(){ printf "[%s] \033[1mINFO\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_warn >/dev/null 2>&1 || log_warn(){ printf "[%s] \033[33mWARN\033[0m  %s\n" "$(date +%H:%M:%S)" "$*"; }
type log_err  >/dev/null 2>&1 || log_err(){  printf "[%s] \033[31mERROR\033[0m %s\n" "$(date +%H:%M:%S)" "$*" >&2; }
type die      >/dev/null 2>&1 || die(){ log_err "$*"; exit 1; }

show_usage() {
  cat <<'EOF'
gpt-creator generate — code generation orchestrator

USAGE
  gpt-creator generate [all|api|web|admin] [options]

OPTIONS
  -m, --model <name>        Codex model (default: ${CODEX_MODEL:-gpt-5-high})
  --codex-cmd <cmd>         Codex CLI (default: ${CODEX_CMD:-codex})
  -y, --yes                 Non-interactive; auto-accept prompts
  -n, --dry-run             Plan only; do not call Codex
  --skip-install            Skip package install/build steps
  --out-root <dir>          Root output (default: ${PROJECT_ROOT:-$ROOT_DIR}/apps)
  -h, --help                Show this help

EXAMPLES
  gpt-creator generate all -y
  gpt-creator generate api  --model gpt-5-high
  gpt-creator generate web  --out-root ./apps
  gpt-creator generate admin -n
EOF
}

# Defaults (may be overridden by constants.sh or env)
: "${PROJECT_ROOT:=${ROOT_DIR}}"
: "${CODEX_MODEL:=gpt-5-high}"
: "${CODEX_CMD:=codex}"

TARGET="all"
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    all|api|web|admin) TARGET="$1"; shift ;;
    -m|--model) CODEX_MODEL="$2"; shift 2 ;;
    --codex-cmd) CODEX_CMD="$2"; shift 2 ;;
    -y|--yes) GC_NONINTERACTIVE=1; shift ;;
    -n|--dry-run) GC_DRY_RUN=1; shift ;;
    --skip-install) GC_SKIP_INSTALL=1; shift ;;
    --out-root) PROJECT_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
    -h|--help) show_usage; exit 0 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

export CODEX_MODEL CODEX_CMD GC_NONINTERACTIVE GC_DRY_RUN GC_SKIP_INSTALL PROJECT_ROOT

run_part () {
  local part="$1"
  local script="${SCRIPT_DIR}/generate-${part}.sh"
  [[ -x "$script" ]] || die "Missing script: $script"
  log_info "▶ Generating ${part}…"
  "$script" "${ARGS[@]}"
  log_info "✔ ${part} generation complete."
}

case "$TARGET" in
  all)
    run_part api
    run_part web
    run_part admin
    ;;
  api|web|admin)
    run_part "$TARGET"
    ;;
  *)
    show_usage
    exit 1
    ;;
esac
