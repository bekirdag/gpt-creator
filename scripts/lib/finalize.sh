#!/usr/bin/env bash
# Finalization and reporting helpers for gpt-creator.

gc_json_escape() {
  local s="${1-}"
  s=${s//\\/\\\\}; s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}; s=${s//$'\r'/\\r}; s=${s//$'\t'/\\t}
  printf '%s' "$s"
}

gc_end_scripts_dirs() {
  local -a dirs=()
  dirs+=("$(gc_from_root "scripts/end-of-task.d")")
  local cli_root="${CLI_ROOT%/}"
  dirs+=("${cli_root}/scripts/end-of-task.d")
  printf '%s\n' "${dirs[@]}"
}

gc_run_end_scripts() {
  local json_path="${1:?json payload path required}"
  local status="${2:-}" reason="${3:-}"
  local failures=0
  local dir
  local project_root; project_root="$(gc_from_root "")"
  local cli_root="${CLI_ROOT%/}"
  while IFS= read -r dir; do
    [[ -d "$dir" ]] || continue
    local run_dir="$project_root"
    if [[ "$dir" == "${cli_root}/scripts/end-of-task.d" ]]; then
      run_dir="$cli_root"
    fi
    while IFS= read -r script_path; do
      [[ -f "$script_path" ]] || continue
      local interpreter
      interpreter="$(gc_guess_interpreter "$script_path")" || interpreter=""
      [[ -n "$interpreter" ]] || continue
      local rel_path="$script_path"
      if [[ "$script_path" == "$run_dir/"* ]]; then
        rel_path="${script_path#$run_dir/}"
      fi
      (
        cd "$run_dir" >/dev/null 2>&1 || exit 0
        if ! GC_TASK_FINAL_STATUS="$status" \
          GC_TASK_FINAL_REASON="$reason" \
          GC_TASK_FINAL_JSON="$json_path" \
          "$interpreter" "$rel_path"
        then
          gc_error_summary_add "end-script failed: $(basename "$rel_path")"
          exit 1
        fi
      ) || failures=1
    done < <(find "$dir" -maxdepth 1 -type f ! -name '.*' 2>/dev/null | sort)
  done < <(gc_end_scripts_dirs)

  local finalize_script
  finalize_script="$(gc_from_root "scripts/auto_finalize_task.sh")"
  if [[ -f "$finalize_script" ]]; then
    local interpreter
    interpreter="$(gc_guess_interpreter "$finalize_script")" || interpreter=""
    if [[ -n "$interpreter" ]]; then
      local rel_finalize
      rel_finalize="$(gc_rel_from_root "$finalize_script")"
      (
        cd "$(gc_from_root "")" >/dev/null 2>&1 || exit 0
        if ! GC_TASK_FINAL_STATUS="$status" \
          GC_TASK_FINAL_REASON="$reason" \
          GC_TASK_FINAL_JSON="$json_path" \
          "$interpreter" "$rel_finalize"
        then
          gc_error_summary_add "end-script failed: $(basename "$rel_finalize")"
          exit 1
        fi
      ) || failures=1
    fi
  fi
  return $failures
}

gc_finalize_and_report() {
  local finalize_key
  finalize_key="$(gc_finalize_lock_key)"
  if [[ "${GC_FINALIZE_AND_REPORT_DONE:-}" == "$finalize_key" ]]; then
    return 0
  fi
  if ! gc_try_acquire_finalize_lock; then
    GC_FINALIZE_AND_REPORT_DONE="$finalize_key"
    echo "[finalize] already completed for this task-run; skipping." >&2
    return 0
  fi
  GC_FINALIZE_AND_REPORT_DONE="$finalize_key"

  local status="${1:-}" reason="${2:-}"
  local now_utc
  now_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  local task_id="${GC_ACTIVE_TASK_ID:-${task_id:-}}"
  local task_number="${GC_ACTIVE_TASK_NUMBER:-${task_number:-${task_index:-}}}"
  local story_slug="${GC_ACTIVE_TASK_SLUG:-${slug:-}}"
  local prompt_path="${GC_ACTIVE_TASK_PROMPT:-${prompt_path:-}}"
  local output_path="${GC_ACTIVE_TASK_OUTPUT:-${output_path:-}}"
  local run_stamp="${GC_ACTIVE_RUN_STAMP:-manual}"
  local tokens_used="${GC_LAST_TOKENS_USED:-${task_tokens_total:-0}}"
  local prompt_estimate="${GC_LAST_PROMPT_ESTIMATE:-${task_prompt_estimate:-0}}"
  local failure_class="${GC_LAST_ERROR_CLASS:-NONE}"
  local retry_attempts="${GC_RETRY_ATTEMPTS:-0}"
  local timeout_record="${GC_LAST_TIMEOUT_SECONDS:-0}"

  if [[ -z "$status" ]]; then
    if [[ -n "${GC_LAST_ERROR_STATUS:-}" && "${GC_LAST_ERROR_STATUS}" != "0" ]]; then
      status="failure"
    else
      status="success"
    fi
  fi

  # git integration
  local finalize_task_id="${GC_ACTIVE_TASK_ID:-${CURRENT_TASK_ID:-${TASK_ID:-${task_id:-unknown}}}}"
  gc_git_finalize_task_branch "$finalize_task_id" "${status:-UNKNOWN}" "${FINAL_REASON_FILE:-}" || true

  local reason_redacted
  reason_redacted="$(gc_redact "$reason")"

  local project_root="${PROJECT_ROOT:-}"
  if [[ -z "$project_root" ]]; then
    project_root="$(gc_detect_project_root)"
  fi

  local git_state_helper=""
  local git_state_path="${project_root}/.gpt-creator/state/git-last.json"
  if declare -F gc_clone_python_tool >/dev/null 2>&1; then
    git_state_helper="$(gc_clone_python_tool "git_last_state.py" "$project_root")" || git_state_helper=""
  fi
  if [[ -z "$git_state_helper" && -n "${CLI_ROOT:-}" && -f "${CLI_ROOT}/scripts/python/git_last_state.py" ]]; then
    git_state_helper="${CLI_ROOT}/scripts/python/git_last_state.py"
  fi
  if [[ -n "$git_state_helper" && -f "$git_state_path" ]]; then
    local git_changed
    git_changed="$(python3 "$git_state_helper" "$git_state_path" 2>/dev/null | awk -F= '$1=="changed"{print $2}' | tail -1)"
    if [[ "$git_changed" =~ ^[0-9]+$ ]] && (( git_changed > 0 )); then
      local normalized_status="${status,,}"
      normalized_status="${normalized_status//_/-}"
      if [[ "$normalized_status" == "completed-no-changes" ]]; then
        info "[git] overriding task status to COMPLETED (${git_changed} files changed since branch start)"
        status="completed"
      fi
    fi
  fi

  if declare -F render_task_end >/dev/null 2>&1; then
    if [[ "${GC_LAST_RENDER_TASK_FOOTER:-}" != "$finalize_task_id" ]]; then
      render_task_end "$finalize_task_id" "${status:-UNKNOWN}" || true
    fi
  fi
  GC_LAST_RENDER_TASK_FOOTER=""

  local reports_dir="${project_root}/.gpt-creator/reports"
  mkdir -p "$reports_dir"
  local key="${story_slug:-story}-${task_number:-unknown}"
  key="${key//[\/ ]/_}"
  local json_path="${reports_dir}/${key}-${run_stamp}.final.json}"

  {
    printf '{'
    printf '"task_id":"%s",'         "$(gc_json_escape "$task_id")"
    printf '"task_number":"%s",'     "$(gc_json_escape "$task_number")"
    printf '"story_slug":"%s",'      "$(gc_json_escape "$story_slug")"
    printf '"status":"%s",'          "$(gc_json_escape "$status")"
    printf '"reason":"%s",'          "$(gc_json_escape "$reason_redacted")"
    printf '"timestamp":"%s",'       "$(gc_json_escape "$now_utc")"
    printf '"run_stamp":"%s",'       "$(gc_json_escape "$run_stamp")"
    printf '"prompt_path":"%s",'     "$(gc_json_escape "$prompt_path")"
    printf '"output_path":"%s",'     "$(gc_json_escape "$output_path")"
    printf '"tokens_used":%s,'       "${tokens_used:-0}"
    printf '"prompt_estimate":%s,'   "${prompt_estimate:-0}"
    printf '"failure_class":"%s",'   "$(gc_json_escape "$failure_class")"
    printf '"attempts":%s,'          "${retry_attempts:-0}"
    printf '"timeout_sec":%s'        "${timeout_record:-0}"
    printf '}\n'
  } >"$json_path"

  gc_flush_logs_hooks || true
  if declare -F gc_reports_flush >/dev/null 2>&1; then
    gc_reports_flush || true
  fi
  sync || true
  sleep 0.05 || true

  gc_run_end_scripts "$json_path" "$status" "$reason_redacted" || true
  gc_mark_finalize_done

  export GC_LAST_FINAL_JSON="$json_path"
  echo "[finalize] Wrote ${json_path}" >&2
  GC_LAST_ERROR_CLASS="NONE"
  GC_LAST_ERROR_REASON=""
  GC_RETRY_ATTEMPTS=0
  GC_LAST_TIMEOUT_SECONDS=0
  GC_ERROR_SUMMARY_ARR=()
}
