#!/usr/bin/env bash
# Codex helper functions shared across commands.

if [[ -n "${GC_LIB_CODEX_UTILS_SH:-}" ]]; then
  return 0
fi
GC_LIB_CODEX_UTILS_SH=1

gc_exec_with_timeout() {
  local timeout="${1:-0}"
  local stdin_file="${2:-}"
  local log_file="${3:-}"
  shift 3 || true
  local -a cmd=("$@")

  local python_bin="${PYTHON_BIN:-python3}"
  if (( ${#cmd[@]} == 0 )); then
    return 1
  fi

  if ! command -v "$python_bin" >/dev/null 2>&1; then
    warn "Python runtime '$python_bin' not available for gc_exec_with_timeout"
    return 1
  fi

  local helper_path
  helper_path="$(gc_clone_python_tool "gc_exec_with_timeout.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  "$python_bin" "$helper_path" "$timeout" "$stdin_file" "$log_file" "${cmd[@]}"
  return "$?"
}

gc_codex_profile_for_step() {
  local step="${1:-patch}"
  local model_ref="${2:?model ref required}"
  local reasoning_ref="${3:?reasoning ref required}"

  local model_value=""
  local reasoning_value=""
  case "$step" in
    patch|apply|code|implement)
      model_value="${CODEX_MODEL_CODE:-${CODEX_MODEL}}"
      reasoning_value="${CODEX_REASONING_EFFORT_CODE:-${CODEX_REASONING_EFFORT:-low}}"
      ;;
    *)
      model_value="${CODEX_MODEL_NON_CODE:-${CODEX_MODEL}}"
      reasoning_value="${CODEX_REASONING_EFFORT_NON_CODE:-${CODEX_REASONING_EFFORT:-low}}"
      ;;
  esac

  if [[ -z "$model_value" ]]; then
    model_value="${CODEX_MODEL:-gpt-5.1-codex}"
  fi
  if [[ -z "$reasoning_value" ]]; then
    if [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
      reasoning_value="${CODEX_REASONING_EFFORT}"
    else
      reasoning_value="low"
    fi
  fi

  printf -v "$model_ref" '%s' "$model_value"
  printf -v "$reasoning_ref" '%s' "$reasoning_value"
}

gc_codex_normalize_reasoning() {
  local value="${1:-}"
  local default_value="${2:-medium}"
  case "${value,,}" in
    low|medium|high) printf '%s' "${value,,}";;
    *) printf '%s' "${default_value,,}";;
  esac
}

gc_codex_normalize_model() {
  local value="${1:-}"
  local fallback="${2:-gpt-5.1-codex}"
  if [[ -z "$value" ]]; then
    printf '%s' "$fallback"
    return 0
  fi
  if [[ "$value" =~ ^(gpt-|o3|o1|o-)|^claude|^gemini ]]; then
    printf '%s' "$value"
    return 0
  fi
  warn "Codex model '${value}' not recognized; falling back to ${fallback}"
  printf '%s' "$fallback"
}

codex_call() {
  local task="${1:?task}"; shift || true
  local prompt_dir="${GC_DIR}/prompts"
  mkdir -p "$prompt_dir"
  GC_CODEX_CALL_TOKEN_ACCUM=0

  local prompt_file=""
  local output_file=""
  local call_step="patch"
  local call_max_output=0

  if [[ $# -gt 0 && -f "$1" ]]; then
    prompt_file="$1"
    shift || true
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prompt) prompt_file="$2"; shift 2;;
      --output) output_file="$2"; shift 2;;
      --step)
        call_step="${2,,}"
        shift 2
        ;;
      *) break;;
    esac
  done

  if [[ -z "$prompt_file" ]]; then
    prompt_file="${prompt_dir}/${task}.md"
    if [[ ! -f "$prompt_file" ]]; then
      gc_render_template "prompts/default_codex_prompt.md" >"$prompt_file"
    fi
  fi

  if [[ -n "$prompt_file" && -f "$prompt_file" ]]; then
    gc_trim_prompt_file "$prompt_file"
  fi

  call_step="${call_step,,}"
  [[ -n "$call_step" ]] || call_step="patch"
  call_max_output="$(gc_output_limit_for_step "$call_step")"
  if ! [[ "$call_max_output" =~ ^[0-9]+$ ]]; then
    call_max_output=0
  fi
  # shellcheck disable=SC2034  # exposed for observability in external tooling
  GC_CURRENT_CODEX_STEP="$call_step"
  # shellcheck disable=SC2034  # exposed for observability in external tooling
  GC_CURRENT_CODEX_MAX_OUT="$call_max_output"

  local codex_model_for_step=""
  local codex_reasoning_for_step=""
  gc_codex_profile_for_step "$call_step" codex_model_for_step codex_reasoning_for_step
  codex_model_for_step="$(gc_codex_normalize_model "$codex_model_for_step" "${CODEX_MODEL:-gpt-5.1-codex}")"
  codex_reasoning_for_step="$(gc_codex_normalize_reasoning "$codex_reasoning_for_step" "${CODEX_REASONING_EFFORT:-medium}")"

  if [[ "${GC_CODEX_USAGE_LIMIT_REACHED:-0}" == "1" && "${GC_CODEX_USAGE_LIMIT_CONFIRMED:-0}" == "1" ]]; then
    warn "Codex usage limit previously reached; skipping ${task}."
    return 95
  fi

  if command -v "$CODEX_BIN" >/dev/null 2>&1; then
    local fallback_model="${CODEX_FALLBACK_MODEL:-$codex_model_for_step}"
    info "Codex ${task} (step=${call_step}) → model=${codex_model_for_step} (reasoning=${codex_reasoning_for_step:-default})"
    # shellcheck disable=SC2034  # local function assigned below for lexical scoping
    local run_codex_model
    run_codex_model() {
      local model="$1"
      shift || true
      local step_reasoning="${1:-}"
      shift || true
      local args=(exec --model "$model")
      if [[ -n "${CODEX_PROFILE:-}" ]]; then
        args+=(--profile "$CODEX_PROFILE")
      fi
      if [[ -n "${PROJECT_ROOT:-}" ]]; then
        args+=(--cd "$PROJECT_ROOT")
      fi
      if [[ -n "$step_reasoning" ]]; then
        args+=(-c "model_reasoning_effort=\"$(gc_codex_normalize_reasoning "$step_reasoning" "${CODEX_REASONING_EFFORT:-medium}")\"")
      elif [[ -n "${CODEX_REASONING_EFFORT:-}" ]]; then
        args+=(-c "model_reasoning_effort=\"$(gc_codex_normalize_reasoning "${CODEX_REASONING_EFFORT}" medium)\"")
      else
        args+=(-c "model_reasoning_effort=\"low\"")
      fi
      if [[ -n "${CODEX_REASONING_SUMMARIES:-}" ]]; then
        args+=(-c "reasoning_summaries=\"${CODEX_REASONING_SUMMARIES}\"")
      else
        args+=(-c "reasoning_summaries=\"disabled\"")
      fi
      if (( call_max_output > 0 )); then
        args+=(-c "model_max_output_tokens=${call_max_output}")
      fi
      args+=(--full-auto --sandbox workspace-write --skip-git-repo-check)
      if [[ -n "$output_file" ]]; then
        mkdir -p "$(dirname "$output_file")"
        args+=(--output-last-message "$output_file")
      fi
      local usage_dir="${LOG_DIR:-${PROJECT_ROOT:-$PWD}/.gpt-creator/logs}"
      mkdir -p "$usage_dir"
      local task_slug
      task_slug="$(printf '%s' "$task" | tr '[:upper:]' '[:lower:]')"
      task_slug="$(printf '%s' "$task_slug" | tr -c 'a-z0-9' '_')"
      [[ -n "$task_slug" ]] || task_slug="codex"
      local model_slug
      model_slug="$(printf '%s' "$model" | tr '[:upper:]' '[:lower:]')"
      model_slug="$(printf '%s' "$model_slug" | tr -c 'a-z0-9' '_')"
      [[ -n "$model_slug" ]] || model_slug="model"
      local codex_log=""
      if ! codex_log="$(mktemp "${usage_dir}/codex-${task_slug}-${model_slug}.XXXXXX.log" 2>/dev/null)"; then
        codex_log="$(mktemp 2>/dev/null)" || codex_log=""
      fi
      local exec_timeout=0
      if [[ "${GC_CODEX_EXEC_TIMEOUT:-}" =~ ^[0-9]+$ ]]; then
        exec_timeout=$((GC_CODEX_EXEC_TIMEOUT))
      fi
      if [[ -n "$codex_log" ]]; then
        local cmd_status=0
        local exec_start_time exec_end_time exec_duration_ms
        exec_start_time="$(date +%s)"
        if gc_exec_with_timeout "$exec_timeout" "$prompt_file" "$codex_log" "$CODEX_BIN" "${args[@]}"; then
          cmd_status=0
        else
          cmd_status=$?
        fi
        exec_end_time="$(date +%s)"
        exec_duration_ms=$(( (exec_end_time - exec_start_time) * 1000 ))
        (( exec_duration_ms < 0 )) && exec_duration_ms=0
        gc_record_codex_usage "$codex_log" "$task" "$model" "$prompt_file" "$cmd_status" "$call_step" "$call_max_output" "$exec_duration_ms"
        local attempt_tokens="${GC_LAST_CODEX_TOTAL_TOKENS:-0}"
        if [[ "$attempt_tokens" =~ ^[0-9]+$ ]]; then
          GC_CODEX_CALL_TOKEN_ACCUM=$((GC_CODEX_CALL_TOKEN_ACCUM + attempt_tokens))
        fi
        gc_log_tokens_used "${GC_LAST_CODEX_TOTAL_TOKENS:-0}" "${GC_LAST_CODEX_PROMPT_TOKENS:-0}" "${GC_LAST_CODEX_COMPLETION_TOKENS:-0}"
        if [[ "${GC_STAGE_LIMIT_LAST_STEP:-}" == "$call_step" ]]; then
          skip_codex=1
          skip_codex_reason="stage-limit"
        fi
      else
        warn "codex_call: could not create log file in ${usage_dir}; continuing without capturing usage."
        "$CODEX_BIN" "${args[@]}"
      fi
      return $cmd_status
    }

    local skip_codex=0
    local skip_codex_reason=""
    if ! run_codex_model "$codex_model_for_step" "$codex_reasoning_for_step"; then
      if [[ "$skip_codex" -eq 1 ]]; then
        warn "Skipping Codex ${task} (step=${call_step}) due to ${skip_codex_reason:-unknown}"
        return 1
      fi
      if [[ -n "$fallback_model" && "$fallback_model" != "$codex_model_for_step" ]]; then
        warn "Primary Codex model failed; retrying with fallback model: $fallback_model"
        run_codex_model "$fallback_model"
      else
        return 1
      fi
    fi
  else
    warn "Codex CLI (${CODEX_BIN:-codex}) not found; skipping Codex call for ${task}."
    return 1
  fi
}

ensure_go_runtime() {
  if command -v go >/dev/null 2>&1; then
    return 0
  fi
  warn "Go toolchain not found in PATH; skipping Go-based checks."
  return 1
}

ensure_node_runtime() {
  if command -v node >/dev/null 2>&1; then
    return 0
  fi
  warn "Node.js runtime not found in PATH; skipping Node-based checks."
  return 1
}

ensure_node_dependencies() {
  local project_root="${1:-${PROJECT_ROOT:-$PWD}}"
  local package_lock="${project_root}/package.json"
  if [[ ! -f "$package_lock" ]]; then
    warn "package.json not found under ${project_root}; skipping Node-based checks."
    return 1
  fi
  local pkg_manager="npm"
  if command -v pnpm >/dev/null 2>&1 && [[ -f "${project_root}/pnpm-lock.yaml" ]]; then
    pkg_manager="pnpm"
  elif command -v yarn >/dev/null 2>&1 && [[ -f "${project_root}/yarn.lock" ]]; then
    pkg_manager="yarn"
  fi
  info "Ensuring Node dependencies are installed (using ${pkg_manager})..."
  local install_output="" install_status=0
  local log_dir="${LOG_DIR:-${project_root}/.gpt-creator/logs}"
  mkdir -p "$log_dir" 2>/dev/null || true
  local log_file="${log_dir}/dep-install.log"
  local tmp_log
  tmp_log="$(mktemp "${TMPDIR:-/tmp}/gc-dep-install.XXXXXX")"

  set +e
  install_output="$(
    (cd "$project_root" && "$pkg_manager" install) >"$tmp_log" 2>&1
  )"
  install_status=$?
  set -e

  install_output="$(cat "$tmp_log" 2>/dev/null || true)"

  {
    printf '\n[%s] project=%s manager=%s status=%s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$project_root" "$pkg_manager" "$install_status"
    cat "$tmp_log"
  } >>"$log_file" 2>/dev/null || true
  rm -f "$tmp_log"

  if (( install_status == 0 )); then
    return 0
  fi

  local network_error=0
  if [[ "$install_output" == *"EAI_AGAIN"* || "$install_output" == *"ENOTFOUND"* || "$install_output" == *"getaddrinfo"* ]]; then
    network_error=1
  elif [[ "$install_output" == *"registry.npmjs.org"* || "$install_output" == *"network connection error"* ]]; then
    network_error=1
  fi

  if (( network_error )); then
    warn "Node dependency install skipped (network unavailable: ${pkg_manager} install); see ${log_file}."
  else
    warn "Node dependency install failed (exit ${install_status}); see ${log_file} for details. Continuing."
  fi

  # Never block work-on-tasks on install issues; continue.
  return 0
}

gc_wot_normalize_sleep_between() {
  local python_bin="${1:-python3}"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    printf '%s\n' "0"
    return 0
  fi
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    die "Python runtime '${python_bin}' not available; cannot normalize --sleep-between"
  fi
  "$python_bin" - "$value" <<'PY'
import sys
import math

def parse_duration(val: str) -> int:
    val = val.strip().lower()
    if val.endswith("ms"):
        return math.ceil(float(val[:-2]))
    if val.endswith("s"):
        return math.ceil(float(val[:-1]) * 1000)
    if val.endswith("m"):
        return math.ceil(float(val[:-1]) * 60_000)
    if val.endswith("h"):
        return math.ceil(float(val[:-1]) * 3_600_000)
    if val.isdigit():
        return int(val)
    raise ValueError(f"invalid duration: {val}")

try:
    parsed = parse_duration(sys.argv[1])
    print(parsed)
except Exception as e:
    sys.stderr.write(str(e) + "\\n")
    sys.exit(1)
PY
}

gc_apply_codex_changes() {
  local output_file="${1:-}"
  local project_root="${2:-${PROJECT_ROOT:-$PWD}}"
  local artifact_path="${3:-}"
  local shell_bin="${BASH:-bash}"

  [[ -f "$output_file" ]] || die "Codex output file not found: ${output_file}"
  local apply_script="$CLI_ROOT/scripts/auto_apply_patch.sh"
  [[ -f "$apply_script" ]] || die "Patch application script missing: ${apply_script}"

  local apply_args=("$apply_script" "$output_file")
  if [[ -n "$artifact_path" ]]; then
    apply_args+=("$artifact_path")
  fi
  GC_APPLY_PATCH_PROJECT_ROOT="$project_root" "$shell_bin" "${apply_args[@]}"
}

gc_refresh_work_prompt() {
  local prompt_base="$1"
  local prompt_path="$2"
  local template="$3"
  local python_bin="${PYTHON_BIN:-python3}"
  [[ -n "$prompt_base" && -n "$prompt_path" && -n "$template" ]] || return 1
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    die "Python runtime '${python_bin}' not available; cannot refresh prompt."
  fi
  local helper_path
  helper_path="$(gc_clone_python_tool "refresh_work_prompt.py" "${PROJECT_ROOT:-$PWD}")" || {
    warn "refresh_work_prompt helper missing; skipping prompt refresh."
    return 0
  }
  "$python_bin" "$helper_path" "$prompt_base" "$prompt_path" "$template"
}
