#!/usr/bin/env bash
# gpt-creator :: generate-admin — uses the active adapter to scaffold Vue 3 Admin (Backoffice) from workflows + docs
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

: "${PROJECT_ROOT:=${ROOT_DIR}}"
# Use the standard CLI default model.
: "${ADAPTER_MODEL:=${GC_ACTIVE_MODEL:-${DEFAULT_LLM:-${CODEX_MODEL:-gpt-5.1-codex}}}}"
: "${ADAPTER_CMD:=${CODEX_CMD:-codex}}"
: "${ADAPTER_NAME:=${GC_ACTIVE_AGENT_ADAPTER:-${CODEX_ADAPTER:-codex_cli}}}"
: "${STAGING_DIR:=${PROJECT_ROOT}/.gpt-creator/staging}"
: "${WORK_DIR:=${PROJECT_ROOT}/.gpt-creator/staging/generate-admin}"
: "${ADMIN_DIR:=${PROJECT_ROOT}/apps/admin}"

mkdir -p "${WORK_DIR}/prompts" "${ADMIN_DIR}"

BACKOFFICE_MMD="${BACKOFFICE_MMD:-}"
PDR="$(resolve_doc "${STAGING_DIR}/pdr.md" '*pdr*.md')"; PDR="${PDR:-<missing>}"
SDS="$(resolve_doc "${STAGING_DIR}/sds.md" '*sds*.md' '*system*design*spec*.md')"; SDS="${SDS:-<missing>}"
JIRA="$(resolve_doc "${STAGING_DIR}/jira.md" '*jira*task*.md' '*jira*.md')"; JIRA="${JIRA:-<missing>}"

INSTALL_DEPS=1

show_help() {
  (
    set -a
    # shellcheck disable=SC2034
    GEN_ADMIN_OUT_DEFAULT="${ADMIN_DIR}"
    set +a
    gc_cli_render_template "help/generate_admin_usage.txt"
  )
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mmd) BACKOFFICE_MMD="$2"; shift 2 ;;
    --out) ADMIN_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --no-install) INSTALL_DEPS=0; shift ;;
    -n|--dry-run) GC_DRY_RUN=1; shift ;;
    -h|--help) show_help; exit 0 ;;
    *) log_warn "Unknown argument: $1"; shift ;;
  esac
done

# Discover Mermaid workflow diagram
if [[ -z "$BACKOFFICE_MMD" ]]; then
  for cand in \
    "${STAGING_DIR}/backoffice.mmd" \
    "${PROJECT_ROOT}/Backoffice pages workflow _ Mermaid Diagram.mmd" \
    "${PROJECT_ROOT}/Website workflow _ Mermaid  Diagram.mmd"
  do
    [[ -f "$cand" ]] && BACKOFFICE_MMD="$cand" && break
  done
fi

[[ -f "$BACKOFFICE_MMD" ]] || log_warn "Backoffice Mermaid diagram not found; proceeding without."

PROMPT_FILE="${WORK_DIR}/prompts/generate-admin.prompt.md"

(
  set -a
  export GEN_ADMIN_SDS="${SDS}"
  export GEN_ADMIN_PDR="${PDR}"
  export GEN_ADMIN_MMD="${BACKOFFICE_MMD:-<none>}"
  export GEN_ADMIN_JIRA="${JIRA}"
  set +a
  gc_cli_render_template "prompts/generate_admin.prompt.md.tmpl"
) > "$PROMPT_FILE"

log_info "Prepared adapter prompt → $PROMPT_FILE"
log_info "Output directory         → $ADMIN_DIR"

mkdir -p "$ADMIN_DIR"

run_adapter() {
  local prompt="$1"
  local out="$2"
  local out_md="${out}/adapter.out.md"
  if [[ -n "${GC_DRY_RUN:-}" ]]; then
    log_info "[dry-run] Skipping model invocation; prompt at ${prompt}"
    printf '{"status":"dry-run","label":"generate-admin"}\n' > "${out}/adapter.out.json"
    return 0
  fi
  case "${ADAPTER_NAME}" in
    command)
      log_info "Running command adapter for admin generation (cmd='${ADAPTER_MODEL}')"
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
      PYTHONPATH="${GC_SCRIPTS_ROOT:-${ROOT_DIR}/scripts}/python:${PYTHONPATH:-}" \
        "${PYTHON_BIN:-python3}" - "$prompt" "$out_md" "$ADAPTER_NAME" "$ADAPTER_MODEL" <<'PY'
import sys
from pathlib import Path
adapter, model = sys.argv[3], sys.argv[4]
prompt_text = Path(sys.argv[1]).read_text(encoding="utf-8")
out_path = Path(sys.argv[2])
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "scripts" / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "python"))
from llm_client_factory import create_llm_client  # type: ignore
client = create_llm_client(adapter, {})
response = client.send_chat([prompt_text], model=model)
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(response.content, encoding="utf-8")
PY
      ;;
  esac
  log_info "Adapter output saved → ${out_md}"
}

run_adapter "$PROMPT_FILE" "$ADMIN_DIR"

if [[ "${INSTALL_DEPS}" -eq 1 && -z "${GC_DRY_RUN:-}" ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    (cd "$ADMIN_DIR" && pnpm install)
    (cd "$ADMIN_DIR" && pnpm build || true)
  else
    log_warn "pnpm not found; skipping install/build."
  fi
fi

if [[ -s "${ADMIN_DIR}/adapter.out.md" ]]; then
  log_info "Admin generation script finished."
else
  die "Admin generation did not produce adapter.out.md in ${ADMIN_DIR}; check logs above."
fi
