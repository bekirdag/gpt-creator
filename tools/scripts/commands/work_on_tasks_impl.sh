#!/usr/bin/env bash
# shellcheck shell=bash

_cmd_work_on_tasks_impl() {
  local root="" resume=1 story_filter="" task_filter="" start_task_ref="" keep_artifacts=0 memory_cycle=0 force_reset=0
  local batch_size=0 sleep_between=0 sleep_between_positive=0 context_lines=400 context_file_lines=200 prompt_compact=1 sample_lines=0 doc_snippets=1
  local -a context_skip_patterns=()
  local override_max_tokens=""
  local override_soft_limit=""
  local override_reserved_output=""
  local override_stop_on_overbudget=""
  local -a stage_limit_overrides=()
  local auto_abandon_override=""
  local idle_timeout="${GC_WORK_ON_TASKS_IDLE_TIMEOUT:-0}"
  local throughput_checkpoint_interval=300
  local throughput_next_checkpoint=0
  local diff_repeat_limit_override=""
  local override_plan_max_out=""
  local override_status_max_out=""
  local override_patch_max_out=""
  local override_hard_cap=""
  local complete_on_followup="${GC_WOT_COMPLETE_ON_FOLLOWUP:-1}"
  local backlog_guard_window_days="${GC_BACKLOG_GUARD_WINDOW_DAYS:-7}"
  local backlog_guard_wip_limit="${GC_BACKLOG_GUARD_WIP_LIMIT:-12}"
  local backlog_snapshot_before_path=""
  local backlog_snapshot_after_path=""
  local backlog_guard_enabled=0
  local backlog_guard_window_value=""
  local prompt_slim_helper=""
  local prompt_safeguard_helper=""
  local empty_apply_mode=""
  local prepare_prompts=1
  local agent_model_override=""
  local agent_selector=""
  local wot_avg_tokens_per_sp=""
  local wot_avg_tokens_samples=0
  local wot_avg_tokens_points="0"
  local wot_avg_tokens_total="0"
  local wot_avg_recent_count=0
  local wot_avg_recent_window=0

  unset GC_ACTIVE_AGENT_FILE GC_ACTIVE_AGENT_NAME GC_ACTIVE_AGENT_CLIENT GC_ACTIVE_AGENT_MODEL GC_ACTIVE_AGENT_ADAPTER GC_ACTIVE_AGENT_MAX_CONTEXT GC_ACTIVE_AGENT_MAX_OUTPUT GC_ACTIVE_AGENT_API_BASE GC_ACTIVE_AGENT_API_KEY_ENV GC_ACTIVE_AGENT_API_ORG_ENV

  local auto_review_enabled=1
  if [[ -n "${GC_AUTO_REVIEW:-}" ]]; then
    case "${GC_AUTO_REVIEW,,}" in
      0|false|no|off) auto_review_enabled=0 ;;
      1|true|yes|on) auto_review_enabled=1 ;;
    esac
  fi

  local binder_enabled=1
  local binder_ttl_seconds=604800
  local binder_max_size_bytes=209715200
  local binder_clear_on_migration=0
  local python_bin="${PYTHON_BIN:-python3}"
  prompt_safeguard_helper="$(gc_clone_python_tool "prompt_safeguard.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  GC_PY_HELPERS_DIR="$(dirname "$prompt_safeguard_helper")"
  export GC_PY_HELPERS_DIR
  if [[ -n "${GC_BINDER_ENABLED:-}" ]]; then
    case "${GC_BINDER_ENABLED,,}" in
      0|false|no|off) binder_enabled=0;;
      *) binder_enabled=1;;
    esac
  fi
  if [[ -n "${GC_BINDER_TTL_SECONDS:-}" ]]; then
    binder_ttl_seconds=$(gc_parse_duration_seconds "${GC_BINDER_TTL_SECONDS}" "$binder_ttl_seconds")
  fi
  if [[ -n "${GC_BINDER_MAX_BYTES:-}" ]]; then
    binder_max_size_bytes=$(gc_parse_size_bytes "${GC_BINDER_MAX_BYTES}" "$binder_max_size_bytes")
  fi
  if [[ -n "${GC_BINDER_CLEAR_ON_MIGRATION:-}" ]]; then
    case "${GC_BINDER_CLEAR_ON_MIGRATION,,}" in
      1|true|yes|on) binder_clear_on_migration=1;;
      *) binder_clear_on_migration=0;;
    esac
  fi

  local codex_timeout_default=600
  local codex_timeout_value="${GC_CODEX_EXEC_TIMEOUT:-}"
  if [[ -z "$codex_timeout_value" ]]; then
    GC_CODEX_EXEC_TIMEOUT="$codex_timeout_default"
  elif [[ "$codex_timeout_value" =~ ^[0-9]+$ ]]; then
    if (( codex_timeout_value <= 0 )); then
      if [[ -n "${GC_CODEX_EXEC_TIMEOUT_INITIAL:-}" ]]; then
        warn "GC_CODEX_EXEC_TIMEOUT (idle timeout) must be greater than zero; defaulting to ${codex_timeout_default}s."
      fi
      GC_CODEX_EXEC_TIMEOUT="$codex_timeout_default"
    fi
  else
    warn "GC_CODEX_EXEC_TIMEOUT ('${codex_timeout_value}') is not numeric; defaulting idle timeout to ${codex_timeout_default}s."
    GC_CODEX_EXEC_TIMEOUT="$codex_timeout_default"
  fi
  local codex_timeout_seconds="${GC_CODEX_EXEC_TIMEOUT}"

  local loop_guard_triggered=0
  local loop_guard_exit_code="${GC_LOOP_GUARD_EXIT_CODE:-72}"
  if ! [[ "$loop_guard_exit_code" =~ ^[0-9]+$ ]]; then
    loop_guard_exit_code=72
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --story|--from-story) story_filter="$2"; shift 2;;
      --from-task|--fresh-from)
        start_task_ref="${2:-}"
        [[ -n "$start_task_ref" ]] || die "--from-task requires a task id or story:position reference"
        shift 2
        ;;
      --task)
        task_filter="${2:-}"
        [[ -n "$task_filter" ]] || die "--task requires a task identifier"
        shift 2
        ;;
      --task=*)
        task_filter="${1#--task=}"
        [[ -n "$task_filter" ]] || die "--task requires a task identifier"
        shift
        ;;
      --fresh) resume=0; shift;;
      --force)
        resume=0
        force_reset=1
        shift
        ;;
      --no-verify)
        shift
        ;;
      --verify)
        shift
        ;;
      --soft-verify|--verify-soft|--verify-soft-fail)
        shift
        ;;
      --verify-mode)
        shift 2
        ;;
      --verify-mode=*)
        shift
        ;;
      --complete-on-followup|--keep-complete-on-followup)
        complete_on_followup=1
        shift
        ;;
      --auto-push)
        export GC_AUTO_PUSH=1
        shift
        ;;
      --auto-push=*)
        export GC_AUTO_PUSH=1
        local auto_push_arg="${1#--auto-push=}"
        if [[ "$auto_push_arg" == *":"* ]]; then
          export GC_AUTO_PUSH_REMOTE="${auto_push_arg%%:*}"
          export GC_AUTO_PUSH_BRANCH="${auto_push_arg#*:}"
        elif [[ "$auto_push_arg" == */* ]]; then
          export GC_AUTO_PUSH_REMOTE="${auto_push_arg%%/*}"
          export GC_AUTO_PUSH_BRANCH="${auto_push_arg#*/}"
        else
          export GC_AUTO_PUSH_REMOTE="$auto_push_arg"
        fi
        shift
        ;;
      --skip-prisma-guard|--no-prisma-guard)
        SKIP_PRISMA_GUARD=1
        shift
        ;;
      --skip-dep-install|--no-dep-install)
        SKIP_DEP_INSTALL=1
        shift
        ;;

      --agent|--codex-model)
        agent_selector="${2:-}"
        agent_model_override="${agent_selector}"
        [[ -n "$agent_model_override" ]] || die "--agent requires a Codex model name"
        shift 2
        ;;
      --agent=*|--codex-model=*)
        agent_selector="${1#*=}"
        agent_model_override="$agent_selector"
        [[ -n "$agent_model_override" ]] || die "--agent requires a Codex model name"
        shift
        ;;
      --keep-artifacts) keep_artifacts=1; shift;;
      --memory-cycle) memory_cycle=1; shift;;
      --batch-size) batch_size="${2:-0}"; shift 2;;
      --sleep-between) sleep_between="${2:-0}"; shift 2;;
      --context-lines)
        context_lines="${2:-}"
        shift 2
        ;;
      --context-none)
        context_lines=0
        shift
        ;;
      --context-file-lines)
        context_file_lines="${2:-}"
        shift 2
        ;;
      --context-skip)
        context_skip_patterns+=("$2")
        shift 2
        ;;
      --prompt-compact)
        prompt_compact=1
        shift
        ;;
      --prompt-expanded)
        prompt_compact=0
        shift
        ;;
      --prepare-prompts)
        prepare_prompts=1
        shift
        ;;
      --no-prepare-prompts)
        prepare_prompts=0
        shift
        ;;
      --context-doc-snippets|--doc-snippets)
        doc_snippets=1
        shift
        ;;
      --no-context-doc-snippets|--no-doc-snippets)
        doc_snippets=0
        shift
        ;;
      --on-empty-apply)
        empty_apply_mode="${2:-}"
        shift 2
        ;;
      --on-empty-apply=*)
        empty_apply_mode="${1#--on-empty-apply=}"
        shift
        ;;
      --plan-max-out)
        override_plan_max_out="${2:-}"
        shift 2
        ;;
      --status-max-out)
        override_status_max_out="${2:-}"
        shift 2
        ;;
      --verify-max-out)
        shift 2
        ;;
      --patch-max-out)
        override_patch_max_out="${2:-}"
        shift 2
        ;;
      --out-hard-cap)
        override_hard_cap="${2:-}"
        shift 2
        ;;
      --sample-lines)
        sample_lines="${2:-}"
        shift 2
        ;;
      --max-tokens)
        override_max_tokens="${2:-}"
        shift 2
        ;;
      --soft-limit)
        override_soft_limit="${2:-}"
        shift 2
        ;;
      --reserve-output)
        override_reserved_output="${2:-}"
        shift 2
        ;;
      --stop-on-overbudget)
        override_stop_on_overbudget="true"
        shift
        ;;
      --stop-on-overbudget=*)
        override_stop_on_overbudget="${1#*=}"
        shift
        ;;
      --no-stop-on-overbudget)
        override_stop_on_overbudget="false"
        shift
        ;;
      --max-tokens-per-stage)
        stage_limit_overrides+=("${2:-}")
        shift 2
        ;;
      --auto-abandon-top-offenders)
        auto_abandon_override="true"
        shift
        ;;
      --no-auto-abandon-top-offenders)
        auto_abandon_override="false"
        shift
        ;;
      --binder-ttl)
        binder_ttl_seconds=$(gc_parse_duration_seconds "${2:-}" "$binder_ttl_seconds")
        shift 2
        ;;
      --binder-max-size)
        binder_max_size_bytes=$(gc_parse_size_bytes "${2:-}" "$binder_max_size_bytes")
        shift 2
        ;;
      --binder-clear-on-migration)
        binder_clear_on_migration=1
        shift
        ;;
      --no-binder)
        binder_enabled=0
        shift
        ;;
      --binder-enabled)
        binder_enabled=1
        shift
        ;;
      --diff-repeat-limit)
        diff_repeat_limit_override="${2:-}"
        [[ -n "$diff_repeat_limit_override" ]] || die "--diff-repeat-limit requires a value"
        [[ "$diff_repeat_limit_override" =~ ^[0-9]+$ ]] || die "Invalid --diff-repeat-limit value: ${diff_repeat_limit_override}"
        export GC_CODEX_DIFF_REPEAT_LIMIT="$diff_repeat_limit_override"
        shift 2
        ;;
      --idle-timeout)
        idle_timeout="${2:-}"
        shift 2
        ;;
      --)
        shift
        break
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd work-on-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/work_on_tasks_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown work-on-tasks option: ${1}"
        ;;
    esac
  done

  GC_WOT_COMPLETE_ON_FOLLOWUP="$complete_on_followup"

  GC_ALLOW_EMPTY_COMMIT="${GC_ALLOW_EMPTY_COMMIT:-1}"
  GC_AUTO_PUSH_MAIN="${GC_AUTO_PUSH_MAIN:-1}"
  GC_RETRY_PUSH_MAX="${GC_RETRY_PUSH_MAX:-3}"
  # shellcheck disable=SC2034
  GC_LAST_VERIFY_STATUS="skipped"
  export GC_LAST_VERIFY_SUMMARY=""

  if [[ -n "$agent_model_override" ]]; then
    CODEX_MODEL="$agent_model_override"
    CODEX_MODEL_LOW="$agent_model_override"
    CODEX_MODEL_NON_CODE="$agent_model_override"
    CODEX_MODEL_CODE="$agent_model_override"
    export CODEX_MODEL CODEX_MODEL_LOW CODEX_MODEL_NON_CODE CODEX_MODEL_CODE
    info "Codex agent override active → ${agent_model_override}"
  fi
  export GC_LAST_VERIFY_REPORT=""
  export GC_LAST_VERIFY_DETAILS=""
  GC_LAST_AUTO_PUSH_ERROR=""
  if [[ -z "${GC_VERIFY_CONFIG:-}" ]]; then
    GC_VERIFY_CONFIG=""
  fi

  if [[ "${GC_AUTO_PUSH_MAIN:-1}" == "1" && -z "${GC_AUTO_PUSH_BRANCH:-}" ]]; then
    GC_AUTO_PUSH_BRANCH="main"
  fi

  if [[ -z "$empty_apply_mode" ]]; then
    empty_apply_mode="${GC_ON_EMPTY_APPLY_MODE:-${GC_ON_EMPTY_APPLY:-}}"
  fi
  local empty_apply_mode_lower="${empty_apply_mode,,}"
  case "$empty_apply_mode_lower" in
    ""|complete|complete-and-next|complete_and_next|next|advance|auto)
      empty_apply_mode="complete"
      ;;
    retry|repeat)
      empty_apply_mode="retry"
      ;;
    fail|error|abort)
      empty_apply_mode="fail"
      ;;
    *)
      warn "Unknown on-empty-apply mode '${empty_apply_mode}'; defaulting to 'complete'."
      empty_apply_mode="complete"
      ;;
  esac
  export GC_ON_EMPTY_APPLY_MODE="$empty_apply_mode"

  if (( binder_enabled )); then
    export GC_BINDER_ENABLED=1
  else
    export GC_BINDER_ENABLED=0
  fi
  export GC_BINDER_TTL_SECONDS="$binder_ttl_seconds"
  export GC_BINDER_MAX_BYTES="$binder_max_size_bytes"
  export GC_BINDER_CLEAR_ON_MIGRATION="$binder_clear_on_migration"

  if [[ -z "$task_filter" && -n "${TASK_FILTER:-}" ]]; then
    task_filter="${TASK_FILTER}"
  fi
  local task_filter_normalized="${task_filter,,}"
  local single_task_mode=0
  local single_task_consumed=0
  if [[ -n "$task_filter_normalized" ]]; then
    single_task_mode=1
    export TASK_FILTER="$task_filter_normalized"
  else
    unset TASK_FILTER 2>/dev/null || true
  fi

  if [[ $# -gt 0 ]]; then
    die "Unexpected argument for work-on-tasks: ${1}"
  fi

  [[ "$batch_size" =~ ^[0-9]+$ ]] || die "Invalid --batch-size value: ${batch_size}"
  if ! sleep_between="$(gc_wot_normalize_sleep_between "$python_bin" "$sleep_between")"; then
    die "Invalid --sleep-between value: ${sleep_between}"
  fi
  [[ "$context_lines" =~ ^[0-9]+$ ]] || die "Invalid --context-lines value: ${context_lines}"
  [[ "$context_file_lines" =~ ^[0-9]+$ ]] || die "Invalid --context-file-lines value: ${context_file_lines}"
  [[ "$sample_lines" =~ ^-?[0-9]+$ ]] || die "Invalid --sample-lines value: ${sample_lines}"
  if [[ -z "$idle_timeout" ]]; then
    idle_timeout=0
  elif [[ "$idle_timeout" =~ ^[0-9]+$ ]]; then
    :
  else
    die "Invalid --idle-timeout value: ${idle_timeout}"
  fi
  batch_size=$((batch_size))
  context_lines=$((context_lines))
  context_file_lines=$((context_file_lines))
  sample_lines=$((sample_lines))
  idle_timeout=$((idle_timeout))
  (( sample_lines >= 0 )) || die "--sample-lines must be zero or positive (got ${sample_lines})"
  if [[ "$sleep_between" != "0" ]]; then
    sleep_between_positive=1
  fi

  backlog_guard_window_value="$backlog_guard_window_days"
  if [[ -z "$backlog_guard_window_value" ]]; then
    backlog_guard_window_value="7"
  elif [[ "$backlog_guard_window_value" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    :
  else
    warn "GC_BACKLOG_GUARD_WINDOW_DAYS ('${backlog_guard_window_days}') is invalid; defaulting to 7."
    backlog_guard_window_value="7"
  fi
  if [[ -z "$backlog_guard_wip_limit" || ! "$backlog_guard_wip_limit" =~ ^[0-9]+$ ]]; then
    warn "GC_BACKLOG_GUARD_WIP_LIMIT ('${backlog_guard_wip_limit}') is invalid; defaulting to 12."
    backlog_guard_wip_limit="12"
  fi

  if [[ -n "$override_max_tokens" && ! "$override_max_tokens" =~ ^[0-9]+$ ]]; then
    die "Invalid --max-tokens value: ${override_max_tokens}"
  fi
  if [[ -n "$override_soft_limit" && ! "$override_soft_limit" =~ ^[0-9]*\.?[0-9]+$ ]]; then
    die "Invalid --soft-limit value: ${override_soft_limit}"
  fi
  if [[ -n "$override_reserved_output" && ! "$override_reserved_output" =~ ^[0-9]+$ ]]; then
    die "Invalid --reserve-output value: ${override_reserved_output}"
  fi
  if ((${#stage_limit_overrides[@]})); then
    local entry
    for entry in "${stage_limit_overrides[@]}"; do
      [[ -n "$entry" && "$entry" == *"="* ]] || die "--max-tokens-per-stage expects stage=value (received: ${entry})"
      local stage_name="${entry%%=*}"
      local stage_value="${entry#*=}"
      [[ -n "$stage_name" ]] || die "--max-tokens-per-stage requires a stage name"
      [[ "$stage_value" =~ ^[0-9]+$ ]] || die "Invalid stage limit '${entry}'; value must be numeric"
    done
  fi
  if [[ -n "$override_plan_max_out" && ! "$override_plan_max_out" =~ ^[0-9]+$ ]]; then
    die "Invalid --plan-max-out value: ${override_plan_max_out}"
  fi
  if [[ -n "$override_status_max_out" && ! "$override_status_max_out" =~ ^[0-9]+$ ]]; then
    die "Invalid --status-max-out value: ${override_status_max_out}"
  fi
  if [[ -n "$override_patch_max_out" && ! "$override_patch_max_out" =~ ^[0-9]+$ ]]; then
    die "Invalid --patch-max-out value: ${override_patch_max_out}"
  fi
  if [[ -n "$override_hard_cap" && ! "$override_hard_cap" =~ ^[0-9]+$ ]]; then
    die "Invalid --out-hard-cap value: ${override_hard_cap}"
  fi
  local stop_override_normalized=""
  if [[ -n "$override_stop_on_overbudget" ]]; then
    stop_override_normalized="${override_stop_on_overbudget,,}"
    case "$stop_override_normalized" in
      true|false|0|1|yes|no|on|off|t|f|y|n) ;;
      *) die "Invalid --stop-on-overbudget value: ${override_stop_on_overbudget}" ;;
    esac
  fi

  if [[ -n "$override_max_tokens" ]]; then
    export GC_PER_TASK_HARD_LIMIT_OVERRIDE="$override_max_tokens"
  else
    unset GC_PER_TASK_HARD_LIMIT_OVERRIDE
  fi
  if [[ -n "$override_soft_limit" ]]; then
    export GC_PER_TASK_SOFT_RATIO_OVERRIDE="$override_soft_limit"
  else
    unset GC_PER_TASK_SOFT_RATIO_OVERRIDE
  fi
  if [[ -n "$override_reserved_output" ]]; then
    export GC_PER_TASK_MIN_OUTPUT_OVERRIDE="$override_reserved_output"
  else
    unset GC_PER_TASK_MIN_OUTPUT_OVERRIDE
  fi
  if [[ -n "$stop_override_normalized" ]]; then
    export GC_STOP_ON_OVERBUDGET_OVERRIDE="$stop_override_normalized"
  else
    unset GC_STOP_ON_OVERBUDGET_OVERRIDE
  fi
  if (( idle_timeout > 0 )); then
    info "Idle watchdog active → ${idle_timeout}s without progress."
  fi
  if [[ -n "$diff_repeat_limit_override" ]]; then
    info "Codex diff repeat guard limit → ${diff_repeat_limit_override} diff(s)."
  fi

  local diff_guard_stall_limit="${GC_DIFF_GUARD_STALL_LIMIT:-1}"
  local diff_guard_token_threshold="${GC_DIFF_GUARD_TOKEN_THRESHOLD:-12}"
  local diff_guard_stdout_slice="${GC_DIFF_GUARD_STDOUT_SLICE:-2048}"
  local diff_guard_file_cooldown="${GC_DIFF_GUARD_FILE_COOLDOWN:-2}"
  local diff_guard_file_min_bytes="${GC_DIFF_GUARD_FILE_MIN_BYTES:-120}"
  local diff_guard_turn_repeat_limit="${GC_DIFF_GUARD_TURN_REPEAT_LIMIT:-3}"
  local diff_guard_history_limit="${GC_DIFF_GUARD_HISTORY_LIMIT:-200}"
  if ! [[ "$diff_guard_stall_limit" =~ ^-?[0-9]+$ ]]; then
    diff_guard_stall_limit=1
  fi
  if ! [[ "$diff_guard_token_threshold" =~ ^[0-9]+$ ]]; then
    diff_guard_token_threshold=12
  fi
  if ! [[ "$diff_guard_stdout_slice" =~ ^[0-9]+$ ]]; then
    diff_guard_stdout_slice=2048
  fi
  if ! [[ "$diff_guard_file_cooldown" =~ ^[0-9]+$ ]]; then
    diff_guard_file_cooldown=2
  fi
  if ! [[ "$diff_guard_file_min_bytes" =~ ^[0-9]+$ ]]; then
    diff_guard_file_min_bytes=120
  fi
  if ! [[ "$diff_guard_turn_repeat_limit" =~ ^[0-9]+$ ]]; then
    diff_guard_turn_repeat_limit=3
  fi
  if ! [[ "$diff_guard_history_limit" =~ ^[0-9]+$ ]]; then
    diff_guard_history_limit=200
  fi
  export GC_DIFF_GUARD_STDOUT_SLICE="$diff_guard_stdout_slice"
  local diff_guard_history=""
  local diff_guard_global_attempt=0

  if [[ -n "$start_task_ref" && $resume -eq 0 ]]; then
    info "--fresh ignored when --from-task is provided; resuming from the specified task instead."
    resume=1
  fi

  if (( memory_cycle )); then
    if (( batch_size == 0 || batch_size > 1 )); then
      info "Memory-cycle enabled; forcing --batch-size 1 for iterative runs."
    fi
    batch_size=1
  fi

  gc_auto_clean_dirty_tree() {
    local git_root="${PROJECT_ROOT:-$PWD}"
    if ! command -v git >/dev/null 2>&1; then
      warn "Auto-clean skipped: git command unavailable."
      return 1
    fi
    if [[ -z "$git_root" || ! -d "$git_root" ]]; then
      warn "Auto-clean skipped: project root unavailable."
      return 1
    fi
    if ! (cd "$git_root" && git rev-parse --is-inside-work-tree >/dev/null 2>&1); then
      warn "Auto-clean skipped: not inside a git repository."
      return 1
    fi

    local dirty_status
    dirty_status="$(cd "$git_root" && git status --porcelain=v1 --untracked-files=all 2>/dev/null || true)"
    if [[ -z "$dirty_status" ]]; then
      return 0
    fi

    local snapshot_timestamp snapshot_label stash_output post_status
    snapshot_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    snapshot_label="work-on-tasks auto snapshot ${snapshot_timestamp}"

    local commit_message="chore(gpt-creator): auto snapshot before work-on-tasks ${snapshot_timestamp}"
    info "Dirty working tree detected; attempting auto snapshot commit before run."
    local branch_state_file="${git_root}/.gpt-creator/state/current-branch"
    local preferred_branch=""
    if [[ -f "$branch_state_file" ]]; then
      preferred_branch="$(head -n1 "$branch_state_file" 2>/dev/null || printf '')"
      preferred_branch="${preferred_branch%%[$'\r\n']*}"
    fi
    local current_branch=""
    current_branch="$(cd "$git_root" && git rev-parse --abbrev-ref HEAD 2>/dev/null || printf '')"
    local branch_switched=0
    local branch_restore_target=""
    local branch_switch_source=""
    if [[ -n "$preferred_branch" && "$preferred_branch" != "$current_branch" ]]; then
      if (cd "$git_root" && git show-ref --verify --quiet "refs/heads/$preferred_branch"); then
        if (cd "$git_root" && git checkout -q "$preferred_branch" >/dev/null 2>&1); then
          branch_switched=1
          branch_restore_target="$current_branch"
          branch_switch_source="$preferred_branch"
          info "Dirty working tree likely belongs to ${preferred_branch}; snapshotting there before continuing."
        else
          warn "Auto snapshot: unable to checkout ${preferred_branch}; continuing on ${current_branch:-current branch}."
        fi
      fi
    fi
    if (cd "$git_root" && git add --all >/dev/null 2>&1); then
      if (cd "$git_root" && git diff --cached --quiet); then
        info "Working tree clean after staging; nothing to snapshot."
        if (( branch_switched )) && [[ -n "$branch_restore_target" && "$branch_restore_target" != "HEAD" ]]; then
          if ! (cd "$git_root" && git checkout -q "$branch_restore_target" >/dev/null 2>&1); then
            warn "Auto snapshot: failed to restore branch ${branch_restore_target}; currently on ${branch_switch_source:-unknown}."
          fi
          branch_switched=0
        fi
        return 0
      fi
      if (cd "$git_root" && GIT_AUTHOR_NAME="gpt-creator automation" GIT_AUTHOR_EMAIL="automation@gpt-creator" GIT_COMMITTER_NAME="gpt-creator automation" GIT_COMMITTER_EMAIL="automation@gpt-creator" git commit -m "$commit_message" >/dev/null 2>&1); then
        local commit_hash
        commit_hash="$(cd "$git_root" && git rev-parse HEAD 2>/dev/null | head -n1)"
        if [[ -n "$commit_hash" ]]; then
          info "Auto commit created (${commit_message}) [${commit_hash:0:7}]."
        else
          info "Auto commit created (${commit_message})."
        fi
        if (( branch_switched )) && [[ -n "$branch_restore_target" && "$branch_restore_target" != "HEAD" ]]; then
          if ! (cd "$git_root" && git checkout -q "$branch_restore_target" >/dev/null 2>&1); then
            warn "Auto snapshot: failed to restore branch ${branch_restore_target}; currently on ${branch_switch_source:-unknown}."
          fi
          branch_switched=0
        fi
        return 0
      fi
      warn "Auto commit snapshot failed; falling back to stash."
      if (cd "$git_root" && git rev-parse --verify HEAD >/dev/null 2>&1); then
        (cd "$git_root" && git reset --mixed HEAD >/dev/null 2>&1 || true)
      else
        (cd "$git_root" && git reset --mixed >/dev/null 2>&1 || true)
      fi
    else
      warn "Auto snapshot staging failed; falling back to stash."
    fi

    info "Attempting auto stash before run."
    if stash_output="$(cd "$git_root" && git stash push --include-untracked --message "$snapshot_label" 2>&1)"; then
      post_status="$(cd "$git_root" && git status --porcelain=v1 --untracked-files=all 2>/dev/null || true)"
      if [[ -z "$post_status" ]]; then
        info "Auto stash created (${snapshot_label})."
        if (( branch_switched )) && [[ -n "$branch_restore_target" && "$branch_restore_target" != "HEAD" ]]; then
          if ! (cd "$git_root" && git checkout -q "$branch_restore_target" >/dev/null 2>&1); then
            warn "Auto snapshot: failed to restore branch ${branch_restore_target}; currently on ${branch_switch_source:-unknown}."
          fi
          branch_switched=0
        fi
        return 0
      fi
      warn "Auto stash incomplete; working tree still dirty."
    else
      stash_output="${stash_output//$'\n'/ }"
      warn "Auto stash failed; ${stash_output}"
    fi
    if (( branch_switched )) && [[ -n "$branch_restore_target" && "$branch_restore_target" != "HEAD" ]]; then
      if ! (cd "$git_root" && git checkout -q "$branch_restore_target" >/dev/null 2>&1); then
        warn "Auto snapshot: failed to restore branch ${branch_restore_target}; currently on ${branch_switch_source:-unknown}."
      fi
      branch_switched=0
    fi
    return 1
  }

  gc_preserve_dirty_tree_for_attempt() {
    local task_label="${1:-task}"
    local attempt_label="${2:-}"
    local git_root="${PROJECT_ROOT:-$PWD}"

    if ! command -v git >/dev/null 2>&1; then
      return 0
    fi
    if [[ -z "$git_root" || ! -d "$git_root" ]]; then
      return 0
    fi
    if ! git -C "$git_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      return 0
    fi

    local dirty_status
    dirty_status="$(git -C "$git_root" status --porcelain=v1 --untracked-files=all 2>/dev/null || true)"
    if [[ -z "$dirty_status" ]]; then
      return 0
    fi

    local commit_message="chore(gpt-creator): preserve pending edits before ${task_label}"
    if [[ -n "$attempt_label" ]]; then
      commit_message+=" attempt ${attempt_label}"
    fi

    info "    Pending edits detected; committing carry-over snapshot (${commit_message})."

    if ! git -C "$git_root" add --all >/dev/null 2>&1; then
      warn "    Failed to stage pending edits for snapshot."
      return 1
    fi

    if git -C "$git_root" diff --cached --quiet >/dev/null 2>&1; then
      info "    Snapshot staging resulted in no changes; continuing."
      return 0
    fi

    if ! GIT_AUTHOR_NAME="gpt-creator automation" \
         GIT_AUTHOR_EMAIL="automation@gpt-creator" \
         GIT_COMMITTER_NAME="gpt-creator automation" \
         GIT_COMMITTER_EMAIL="automation@gpt-creator" \
         git -C "$git_root" commit -m "$commit_message" >/dev/null 2>&1; then
      warn "    Carry-over snapshot commit failed."
      return 1
    fi

    return 0
  }

  gc_auto_sync_i18n() {
    local project_root="${PROJECT_ROOT:-$PWD}"
    if [[ -z "$project_root" || ! -d "$project_root" ]]; then
      warn "Auto locale sync skipped: project root unavailable."
      return 1
    fi

    local sync_cmd_output=""

    if [[ -f "${project_root}/package.json" ]] && grep -q '"i18n:sync"' "${project_root}/package.json"; then
      if command -v pnpm >/dev/null 2>&1; then
        info "Attempting auto locale sync via 'pnpm run i18n:sync'."
        if sync_cmd_output="$(cd "$project_root" && pnpm run i18n:sync 2>&1)"; then
          info "Locale sync completed (pnpm)."
          return 0
        fi
        warn "Locale sync via pnpm failed: ${sync_cmd_output//$'\n'/ }"
      fi

      if command -v npm >/dev/null 2>&1; then
        info "Attempting auto locale sync via 'npm run i18n:sync'."
        if sync_cmd_output="$(cd "$project_root" && npm run i18n:sync --silent 2>&1)"; then
          info "Locale sync completed (npm)."
          return 0
        fi
        warn "Locale sync via npm failed: ${sync_cmd_output//$'\n'/ }"
      fi
    fi

    local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
    if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
      scripts_root="${CLI_ROOT}/scripts"
    fi
    local i18n_script="${scripts_root}/i18n-sync.js"
    if [[ -f "$i18n_script" ]] && command -v node >/dev/null 2>&1; then
      info "Attempting auto locale sync via local i18n-sync.js."
      if sync_cmd_output="$(cd "$project_root" && node "$i18n_script" 2>&1)"; then
        info "Locale sync completed (node)."
        return 0
      fi
      warn "Locale sync via node script failed: ${sync_cmd_output//$'\n'/ }"
    fi

    warn "Auto locale sync failed; tooling unavailable or commands returned errors."
    return 1
  }

  ensure_ctx "$root"
  local work_plan_tasks_db="${PLAN_DIR}/tasks/tasks.db"
  [[ -f "$work_plan_tasks_db" ]] || die "Tasks database not found at ${work_plan_tasks_db}. Run 'gpt-creator create-tasks' first."

  if [[ -n "$agent_selector" ]]; then
    local agent_tmp=""
    agent_tmp="$(mktemp "${GC_DIR}/tmp/agent-select.XXXXXX.json")"
    local select_output=""
    if select_output="$(gc_run_agents_cli "${PROJECT_ROOT:-$PWD}" "$work_plan_tasks_db" select --name "$agent_selector")"; then
      local parse_output=""
      parse_output="$("$python_bin" - "$agent_tmp" <<'PY' <<<"$select_output"
import json, sys
data = json.load(sys.stdin)
tmp_path = sys.argv[1]
kind = data.get("kind")
if kind == "agent":
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    agent = data.get("agent") or {}
    print("agent")
    print(agent.get("client", ""))
    print(agent.get("model", ""))
    print(agent.get("name", ""))
    print(agent.get("client_api_key", ""))
    print(agent.get("client_api_base", ""))
    print(agent.get("client_api_org", ""))
elif kind == "model":
    print("model")
    print("")
    print(data.get("model", ""))
    print("")
    print("")
    print("")
    print("")
else:
    print("unknown")
    print("")
    print("")
    print("")
    print("")
    print("")
PY
)"
      IFS=$'\n' read -r resolved_kind resolved_client resolved_model resolved_name resolved_api_key resolved_api_base resolved_api_org <<<"$parse_output"
      if [[ "$resolved_kind" == "agent" && -n "$resolved_model" ]]; then
        export GC_ACTIVE_AGENT_FILE="$agent_tmp"
        export GC_ACTIVE_AGENT_NAME="$resolved_name"
        export GC_ACTIVE_AGENT_CLIENT="$resolved_client"
        export GC_ACTIVE_AGENT_MODEL="$resolved_model"
        agent_model_override="$resolved_model"
        local registry_info adapter_parse_output agent_adapter="" agent_ctx="" agent_out="" agent_api_base="" agent_api_key_env="" agent_org_env="" agent_api_base_env=""
        if registry_info="$(gc_agents_registry_cmd validate --client "$resolved_client" --model "$resolved_model" 2>/dev/null)"; then
          adapter_parse_output="$("$python_bin" - <<'PY' "$registry_info"
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print(data.get("adapter", ""))
print(data.get("maxContextTokens") or "")
print(data.get("maxOutputTokens") or "")
print(data.get("apiBase") or "")
print(data.get("apiKeyEnv") or "")
print(data.get("orgEnv") or "")
print(data.get("apiBaseEnv") or "")
PY
)"
          IFS=$'\n' read -r agent_adapter agent_ctx agent_out agent_api_base agent_api_key_env agent_org_env agent_api_base_env <<<"$adapter_parse_output"
          if [[ -n "$agent_adapter" ]]; then
            export GC_ACTIVE_AGENT_ADAPTER="$agent_adapter"
          fi
          if [[ -n "$agent_ctx" ]]; then
            export GC_ACTIVE_AGENT_MAX_CONTEXT="$agent_ctx"
          fi
          if [[ -n "$agent_out" ]]; then
            export GC_ACTIVE_AGENT_MAX_OUTPUT="$agent_out"
          fi
          if [[ -n "$agent_api_base" ]]; then
            export GC_ACTIVE_AGENT_API_BASE="$agent_api_base"
          fi
          if [[ -n "$agent_api_key_env" ]]; then
            export GC_ACTIVE_AGENT_API_KEY_ENV="$agent_api_key_env"
          fi
          if [[ -n "$agent_org_env" ]]; then
            export GC_ACTIVE_AGENT_API_ORG_ENV="$agent_org_env"
          fi
          if [[ -n "$agent_api_base_env" ]]; then
            export GC_ACTIVE_AGENT_API_BASE_ENV="$agent_api_base_env"
          fi
        fi
        if [[ -n "$resolved_api_base" ]]; then
          export GC_ACTIVE_AGENT_API_BASE="$resolved_api_base"
          if [[ -n "$agent_api_base_env" ]]; then
            export "$agent_api_base_env"="$resolved_api_base"
          fi
        fi
        if [[ -n "$agent_api_key_env" && -n "$resolved_api_key" ]]; then
          export "$agent_api_key_env"="$resolved_api_key"
        fi
        if [[ -n "$agent_org_env" && -n "$resolved_api_org" ]]; then
          export "$agent_org_env"="$resolved_api_org"
        fi
        info "Agent '${resolved_name}' active (client=${resolved_client}, model=${resolved_model}${agent_adapter:+, adapter=${agent_adapter}})."
        AGENT_TELEMETRY_PAYLOAD="$(jq -n \
          --arg name "$resolved_name" \
          --arg client "$resolved_client" \
          --arg model "$resolved_model" \
          '{agent: {name: $name, client: $client, model: $model}}')"
      else
        rm -f "$agent_tmp"
        if [[ -n "$resolved_model" ]]; then
          agent_model_override="$resolved_model"
        fi
      fi
    else
      rm -f "$agent_tmp"
      warn "Agent '${agent_selector}' not found; treating value as raw model override."
    fi
  fi

  if [[ -z "$override_max_tokens" && -n "${GC_ACTIVE_AGENT_MAX_CONTEXT:-}" && "${GC_ACTIVE_AGENT_MAX_CONTEXT}" =~ ^[0-9]+$ ]]; then
    override_max_tokens="${GC_ACTIVE_AGENT_MAX_CONTEXT}"
    info "Applying agent max-context override (${override_max_tokens} tokens)."
  fi
  if [[ -z "$override_reserved_output" && -n "${GC_ACTIVE_AGENT_MAX_OUTPUT:-}" && "${GC_ACTIVE_AGENT_MAX_OUTPUT}" =~ ^[0-9]+$ ]]; then
    override_reserved_output="${GC_ACTIVE_AGENT_MAX_OUTPUT}"
    info "Applying agent max-output override (${override_reserved_output} tokens)."
  fi

  if [[ -z "${GC_ACTIVE_AGENT_ADAPTER:-}" ]]; then
    GC_ACTIVE_AGENT_ADAPTER="codex_cli"
  fi

  local order_helper=""
  if ! order_helper="$(gc_clone_python_tool "update_global_task_order.py" "${PROJECT_ROOT:-$PWD}")"; then
    return 1
  fi
  if ! python3 "$order_helper" "$work_plan_tasks_db" --project-root "${PROJECT_ROOT:-$PWD}" --ensure >/dev/null 2>&1; then
    warn "work-on-tasks: unable to verify global task order; continuing with existing queue."
  fi

  local prepare_prompts_flag="$prepare_prompts"
  if [[ -n "${GC_WORK_PREPARE_PROMPTS:-}" ]]; then
    case "${GC_WORK_PREPARE_PROMPTS,,}" in
      0|false|no) prepare_prompts_flag=0 ;;
      1|true|yes) prepare_prompts_flag=1 ;;
    esac
  fi
  export GC_WORK_PREPARE_PROMPTS="$prepare_prompts_flag"
  if [[ "${GC_WORK_PREPARE_PROMPTS}" == "1" ]]; then
    export GC_SKIP_STORY_PROMPT_SYNC=0
  else
    export GC_SKIP_STORY_PROMPT_SYNC=1
  fi

  local work_state_dir="${PLAN_DIR}/work"
  mkdir -p "$work_state_dir"
  local prompt_guard="${work_state_dir}/.prompt_sync.once"
  export GC_WORK_PROMPT_SYNC_RUN_GUARD="$prompt_guard"
  if [[ "${GC_WORK_PREPARE_PROMPTS}" == "1" ]]; then
    rm -f "$prompt_guard" 2>/dev/null || true
  else
    : > "$prompt_guard"
  fi

  if [[ -z "${GC_PROMPT_PUBLISH_DISABLE:-}" ]]; then
    if [[ "${GC_WORK_PREPARE_PROMPTS}" == "1" ]]; then
      export GC_PROMPT_PUBLISH_DISABLE=0
    else
      export GC_PROMPT_PUBLISH_DISABLE=1
    fi
  fi

  local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
  if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
    scripts_root="${CLI_ROOT}/scripts"
  fi
  local preflight_script="${scripts_root}/preflight_git_blockers.sh"
  local auto_conflict_script="${scripts_root}/auto_resolve_conflicts.sh"
  local preflight_conflict_autofix_attempted=0
  local preflight_dirty_tree_autofix_attempts=0
  local preflight_dirty_tree_autofix_limit="${GC_PREFLIGHT_DIRTY_TREE_AUTO_FIX_LIMIT:-3}"
  if ! [[ "$preflight_dirty_tree_autofix_limit" =~ ^[0-9]+$ ]]; then
    preflight_dirty_tree_autofix_limit=3
  fi
  if [[ -x "$preflight_script" ]]; then
    while true; do
      local preflight_output="" preflight_code=0 preflight_outcome=""
      if [[ -n "${PROJECT_ROOT:-}" ]]; then
        set +e
        preflight_output="$(cd "$PROJECT_ROOT" && "$preflight_script")"
        preflight_code=$?
        set -e
      else
        set +e
        preflight_output="$("$preflight_script")"
        preflight_code=$?
        set -e
      fi
      preflight_outcome="${preflight_output//[$'\r\n']}"
      if [[ -z "$preflight_outcome" ]]; then
        if (( preflight_code == 3 )); then
          preflight_outcome="blocked-merge-conflict"
        elif (( preflight_code == 2 )); then
          preflight_outcome="blocked-dirty-tree"
        else
          preflight_outcome="ok"
        fi
      fi
      case "$preflight_outcome" in
        blocked-merge-conflict)
          if (( preflight_conflict_autofix_attempted == 0 )) && [[ -x "$auto_conflict_script" ]]; then
            info "Merge artifacts detected; attempting automatic cleanup."
            if [[ -n "${PROJECT_ROOT:-}" ]]; then
              (cd "$PROJECT_ROOT" && "$auto_conflict_script" "$PROJECT_ROOT") || true
            else
              "$auto_conflict_script" "$PWD" || true
            fi
            preflight_conflict_autofix_attempted=1
            continue
          fi
          warn "Git merge conflicts detected; resolve before running work-on-tasks."
          printf '%s\n' "$preflight_outcome"
          return 3
          ;;
        blocked-dirty-tree)
          if (( preflight_dirty_tree_autofix_attempts < preflight_dirty_tree_autofix_limit )); then
            ((preflight_dirty_tree_autofix_attempts+=1))
            if gc_auto_clean_dirty_tree; then
              continue
            fi
          fi
          warn "Dirty working tree detected; commit or stash changes before running work-on-tasks."
          printf '%s\n' "$preflight_outcome"
          return 2
          ;;
        ok)
          break
          ;;
        *)
          if (( preflight_code != 0 )); then
            warn "Preflight git blockers returned '${preflight_outcome:-?}' (exit ${preflight_code}); treating as dirty tree."
            printf '%s\n' "${preflight_outcome:-blocked-dirty-tree}"
            return 2
          fi
          break
          ;;
      esac
    done
  fi

  local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
  if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
    scripts_root="${CLI_ROOT}/scripts"
  fi
  local i18n_guard_script="${scripts_root}/preflight_i18n_guard.sh"
  if [[ "${WORK_ON_TASKS_SKIP_I18N_GUARD:-0}" =~ ^(1|true|yes)$ ]]; then
    info "Skipping i18n preflight guard because WORK_ON_TASKS_SKIP_I18N_GUARD=${WORK_ON_TASKS_SKIP_I18N_GUARD}"
  elif [[ -x "$i18n_guard_script" ]]; then
    local i18n_guard_output="" i18n_guard_code=0 i18n_guard_outcome=""
    local i18n_guard_autofix_attempts=0
    local i18n_guard_autofix_limit="${GC_PREFLIGHT_I18N_AUTO_SYNC_LIMIT:-1}"
    if ! [[ "$i18n_guard_autofix_limit" =~ ^[0-9]+$ ]]; then
      i18n_guard_autofix_limit=1
    fi
    while true; do
      if [[ -n "${PROJECT_ROOT:-}" ]]; then
        set +e
        i18n_guard_output="$(cd "$PROJECT_ROOT" && "$i18n_guard_script" 2>&1)"
        i18n_guard_code=$?
        set -e
      else
        set +e
        i18n_guard_output="$("$i18n_guard_script" 2>&1)"
        i18n_guard_code=$?
        set -e
      fi
      i18n_guard_outcome="${i18n_guard_output//[$'\r\n']}"
      if [[ -z "$i18n_guard_outcome" ]]; then
        if (( i18n_guard_code == 6 )); then
          i18n_guard_outcome="blocked-dependency(i18n_sync_required)"
        elif (( i18n_guard_code == 3 )); then
          i18n_guard_outcome="blocked-merge-conflict"
        else
          i18n_guard_outcome="ok"
        fi
      fi
      case "$i18n_guard_outcome" in
        blocked-merge-conflict)
          warn "Locale merge conflicts detected; resolve locale .rej files before running work-on-tasks."
          printf '%s\n' "$i18n_guard_outcome"
          return 3
          ;;
        'blocked-dependency(i18n_sync_required)')
          if (( i18n_guard_autofix_attempts < i18n_guard_autofix_limit )); then
            ((i18n_guard_autofix_attempts+=1))
            if gc_auto_sync_i18n; then
              continue
            fi
          fi
          warn "Locale files out of sync; run 'pnpm i18n:sync' to regenerate translations."
          printf '%s\n' "$i18n_guard_outcome"
          return 6
          ;;
        blocked-i18n-guard-error)
          warn "i18n preflight guard failed; inspect scripts/preflight_i18n_guard.sh output."
          if [[ -n "$i18n_guard_output" ]]; then
            printf '%s\n' "$i18n_guard_output" >&2
          fi
          printf '%s\n' "$i18n_guard_outcome"
          return 6
          ;;
        ok)
          break
          ;;
        *)
          if (( i18n_guard_code != 0 )); then
            warn "i18n preflight guard returned '${i18n_guard_outcome:-?}' (exit ${i18n_guard_code}); treating as guard failure."
            printf '%s\n' "blocked-i18n-guard-error"
            return 6
          fi
          break
          ;;
      esac
    done
  fi

  local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
  if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
    scripts_root="${CLI_ROOT}/scripts"
  fi
  local schema_guard_script="${scripts_root}/preflight_prisma_guard.sh"
  if [[ -x "$schema_guard_script" ]]; then
    local schema_guard_output="" schema_guard_code=0 schema_guard_outcome=""
    if [[ -n "${PROJECT_ROOT:-}" ]]; then
      set +e
      schema_guard_output="$(cd "$PROJECT_ROOT" && "$schema_guard_script")"
      schema_guard_code=$?
      set -e
    else
      set +e
      schema_guard_output="$("$schema_guard_script")"
      schema_guard_code=$?
      set -e
    fi
    schema_guard_outcome="${schema_guard_output//[$'\r\n']}"
    if [[ -z "$schema_guard_outcome" ]]; then
      if (( schema_guard_code == 4 )); then
        schema_guard_outcome="blocked-schema-drift"
      elif (( schema_guard_code == 5 )); then
        schema_guard_outcome="blocked-schema-guard-error"
      else
        schema_guard_outcome="ok"
      fi
    fi
    case "$schema_guard_outcome" in
      blocked-schema-drift)
        warn "Prisma schema drift detected; align prisma/schema.prisma with migrations before running work-on-tasks."
        printf '%s\n' "$schema_guard_outcome"
        return 4
        ;;
      blocked-schema-guard-error)
        warn "Prisma schema guard failed; inspect prisma migrate diff output and rerun."
        printf '%s\n' "$schema_guard_outcome"
        return 4
        ;;
      ok)
        ;;
      *)
        if (( schema_guard_code != 0 )); then
          warn "Prisma schema guard returned '${schema_guard_outcome:-?}' (exit ${schema_guard_code}); treating as guard failure."
          printf '%s\n' "blocked-schema-guard-error"
          return 4
        fi
        ;;
    esac
  fi

  local budget_cfg_json="{}"
  local budget_loader
  if budget_loader="$(gc_clone_python_tool "load_budget_config.py" "$PROJECT_ROOT" 2>/dev/null)"; then
    budget_cfg_json="$("$python_bin" "$budget_loader" "$PROJECT_ROOT" 2>/dev/null || echo '{}')"
  fi

  local budget_stage_json
  local budget_stage_helper
  if budget_stage_helper="$(gc_clone_python_tool "budget_stage_from_config.py" "${PROJECT_ROOT:-$PWD}")"; then
    budget_stage_json="$("$python_bin" "$budget_stage_helper" "$budget_cfg_json" 2>/dev/null || echo '{}')"
  else
    budget_stage_json="{}"
  fi

  if ((${#stage_limit_overrides[@]} > 0)); then
    local budget_stage_override_helper
    if budget_stage_override_helper="$(gc_clone_python_tool "budget_stage_apply_overrides.py" "${PROJECT_ROOT:-$PWD}")"; then
      budget_stage_json="$("$python_bin" "$budget_stage_override_helper" "$budget_stage_json" "${stage_limit_overrides[@]}" 2>/dev/null || echo '{}')"
    fi
  fi

  local budget_stage_iter_helper
  budget_stage_iter_helper="$(gc_clone_python_tool "budget_stage_iter.py" "${PROJECT_ROOT:-$PWD}")" || budget_stage_iter_helper=""

  if [[ -n "$budget_stage_iter_helper" ]]; then
    while IFS=$'\t' read -r stage_name stage_limit_value; do
      gc_budget_set_stage_limit "$stage_name" "$stage_limit_value"
    done < <("$python_bin" "$budget_stage_iter_helper" "$budget_stage_json")
  fi

  gc_budget_reset_stage_tracking

  local budget_off_json="{}"
  local budget_off_helper
  if budget_off_helper="$(gc_clone_python_tool "budget_offenders_from_config.py" "${PROJECT_ROOT:-$PWD}")"; then
    budget_off_json="$("$python_bin" "$budget_off_helper" "$budget_cfg_json" 2>/dev/null || echo '{}')"
  fi
  [[ -n "$budget_off_json" ]] || budget_off_json="{}"

  local budget_offender_window=10
  local budget_offender_top_k=3
  local budget_offender_dom=0.5
  local budget_auto_abandon_default=1
  local budget_offender_actions_json="{}"
  local budget_offender_meta_helper
  if budget_offender_meta_helper="$(gc_clone_python_tool "budget_offenders_meta.py" "${PROJECT_ROOT:-$PWD}")"; then
    local offender_meta
    offender_meta="$("$python_bin" "$budget_offender_meta_helper" "$budget_off_json" 2>/dev/null)"
    if [[ -n "$offender_meta" ]]; then
      IFS=$'\t' read -r budget_offender_window budget_offender_top_k budget_offender_dom budget_auto_abandon_default budget_offender_actions_json <<<"$offender_meta"
    fi
  fi
  budget_offender_window=${budget_offender_window:-10}
  budget_offender_top_k=${budget_offender_top_k:-3}
  budget_offender_dom=${budget_offender_dom:-0.5}
  budget_auto_abandon_default=${budget_auto_abandon_default:-1}
  [[ -n "$budget_offender_actions_json" ]] || budget_offender_actions_json="{}"

  local auto_abandon_flag=$budget_auto_abandon_default
  if [[ "$auto_abandon_override" == "true" ]]; then
    auto_abandon_flag=1
  elif [[ "$auto_abandon_override" == "false" ]]; then
    auto_abandon_flag=0
  fi
  if gc_env_truthy "${GC_DISABLE_AUTO_ABANDON:-}"; then
    auto_abandon_flag=0
  fi

  local budget_usage_file="${LOG_DIR:-${PROJECT_ROOT:-$PWD}/.gpt-creator/logs}/codex-usage.ndjson"
  local budget_offenders_json="{}"
  local offenders_helper
  if offenders_helper="$(gc_clone_python_tool "budget_offenders.py" "$PROJECT_ROOT" 2>/dev/null)"; then
    local -a offender_args=("$offenders_helper" --usage-file "$budget_usage_file" --per-stage-json "$budget_stage_json" --actions-json "$budget_offender_actions_json" --window-runs "$budget_offender_window" --top-k "$budget_offender_top_k" --dominance-threshold "$budget_offender_dom")
    if (( auto_abandon_flag )); then
      offender_args+=(--auto-abandon)
    else
      offender_args+=(--no-auto-abandon)
    fi
    budget_offenders_json="$("$python_bin" "${offender_args[@]}" 2>/dev/null || echo '{}')"
  fi

  local last_offender_run=""
  local offenders_auto_flag=$auto_abandon_flag
  if gc_env_truthy "${GC_DISABLE_AUTO_ABANDON:-}"; then
    offenders_auto_flag=0
  fi
  if [[ -n "$budget_offenders_json" && "$budget_offenders_json" != "{}" ]]; then
    local budget_off_iter_helper
    budget_off_iter_helper="$(gc_clone_python_tool "budget_offenders_iter.py" "${PROJECT_ROOT:-$PWD}")" || budget_off_iter_helper=""
    if [[ -n "$budget_off_iter_helper" ]]; then
      while IFS=$'\t' read -r kind value1 value2 value3 value4; do
        case "$kind" in
          AUTO)
            offenders_auto_flag="${value1:-0}"
            ;;
          RUN)
            last_offender_run="$value1"
            ;;
          STAGE)
            if [[ "$offenders_auto_flag" == "1" ]]; then
              gc_budget_set_stage_skip "$value1" 1 "auto-abandon:${last_offender_run:-previous}"
            fi
            ;;
          TOOL)
            local tool_key
            tool_key="$(gc_budget_stage_id "$value1")"
            local tool_action_var="GC_BUDGET_TOOL_ACTION_${tool_key^^}"
            printf -v "$tool_action_var" '%s' "$value4"
            local tool_bytes_var="GC_BUDGET_TOOL_BYTES_${tool_key^^}"
            printf -v "$tool_bytes_var" '%s' "$value2"
            local tool_share_var="GC_BUDGET_TOOL_SHARE_${tool_key^^}"
            printf -v "$tool_share_var" '%s' "$value3"
            ;;
        esac
      done < <("$python_bin" "$budget_off_iter_helper" "$budget_offenders_json")
    fi
  fi

  if [[ "${GC_BUDGET_TOOL_ACTION_SHOW_FILE:-}" == "range-only" ]]; then
    export GC_SHOW_FILE_FORCE_RANGE=1
  fi
  if [[ "${GC_BUDGET_TOOL_ACTION_RG:-}" == "narrow" ]]; then
    export GC_RG_NARROW=1
  fi
  if [[ "${GC_BUDGET_TOOL_ACTION_TESTS:-}" == "summary" ]]; then
    export GC_TESTS_SUMMARY=1
  fi

  export GC_BUDGET_STAGE_LIMITS_JSON="$budget_stage_json"
  export GC_BUDGET_TOOL_ACTIONS_JSON="$budget_offender_actions_json"

  gc_load_llm_output_limits "${PROJECT_ROOT:-$PWD}" || true
  if [[ -n "$override_hard_cap" ]]; then
    gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_HARD_CAP "$override_hard_cap"
  fi
  if [[ -n "$override_plan_max_out" ]]; then
    gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_PLAN "$override_plan_max_out"
  fi
  if [[ -n "$override_status_max_out" ]]; then
    gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_STATUS "$override_status_max_out"
  fi
  if [[ -n "$override_patch_max_out" ]]; then
    gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_PATCH "$override_patch_max_out"
  fi

  info "LLM output limits → plan=${GC_LLM_OUTPUT_LIMIT_PLAN}, status=${GC_LLM_OUTPUT_LIMIT_STATUS}, patch=${GC_LLM_OUTPUT_LIMIT_PATCH}, hard_cap=${GC_LLM_OUTPUT_LIMIT_HARD_CAP}"

  local tasks_dir="${PLAN_DIR}/tasks"
  mkdir -p "$tasks_dir"
  local canonical_tasks_dir="${PROJECT_ROOT:-$PWD}/.gpt-creator/staging/plan/tasks"
  mkdir -p "$canonical_tasks_dir"
  local tasks_db="${canonical_tasks_dir}/tasks.db"
  local intake_lock_path="${canonical_tasks_dir}/.intake-frozen"
  local doc_vector_path="${canonical_tasks_dir}/documentation-vector-index.sqlite"
  export GC_DOC_VECTOR_INDEX_PATH="$doc_vector_path"
  export GC_DOCUMENTATION_INDEX_PATH="$doc_vector_path"
  local doc_mode="${GC_DOCS_MODE:-lazy}"
  local workspace_stub="${PROJECT_ROOT:-$PWD}/.gpt-creator/docs/catalog.db"
  local using_stub=0
  if [[ -n "${GC_DOCUMENTATION_DB_PATH:-}" && "$GC_DOCUMENTATION_DB_PATH" == "$workspace_stub" ]]; then
    using_stub=1
  fi

  if [[ "${GC_DOCS_ENABLED:-1}" -eq 1 ]]; then
    if (( using_stub )); then
      if gc_refresh_documentation_if_needed "${PROJECT_ROOT:-$PWD}"; then
        local refreshed_db="${canonical_tasks_dir}/tasks.db"
        if [[ -f "$refreshed_db" ]]; then
          export GC_DOCUMENTATION_DB_PATH="$refreshed_db"
          using_stub=0
          info "Documentation catalog refreshed; using ${GC_DOCUMENTATION_DB_PATH}."
        fi
      fi
    fi

    if (( using_stub )); then
      warn "Documentation catalog running in workspace stub mode (${GC_DOCUMENTATION_DB_PATH}); limited doc queries only."
    fi

    if (( using_stub == 0 )); then
      if [[ "${doc_mode,,}" == "strict" ]]; then
        if ! gc_require_documentation_catalog "$PROJECT_ROOT"; then
          local catalog_root="${PROJECT_ROOT:-$PWD}"
          die "Failed to prepare documentation catalog. Run 'gpt-creator scan --project \"${catalog_root}\"' and retry."
        fi
        gc_bootstrap_docs_registry
      else
        if ! gc_require_documentation_catalog "$PROJECT_ROOT"; then
          warn "Documentation catalog not ready; continuing in lazy mode without strict enforcement."
        else
          gc_bootstrap_docs_registry
        fi
      fi
    fi
  else
    warn "Documentation catalog disabled (GC_DOCS_MODE=${GC_DOCS_MODE:-off}); skipping documentation checks."
  fi

  if ! gc_tasks_db_has_rows "$tasks_db"; then
    die "Task database missing or empty. Run 'gpt-creator create-tasks' (or create-jira-tasks + migrate-tasks) before work-on-tasks."
  fi

  local total_tasks_all
  total_tasks_all="$(sqlite3 "$tasks_db" "SELECT COUNT(*) FROM tasks;" 2>/dev/null || echo 0)"
  if ! [[ "$total_tasks_all" =~ ^[0-9]+$ ]]; then
    total_tasks_all=0
  fi
  if (( total_tasks_all == 0 )); then
    die "there are no tasks in the database"
  fi
  local tasks_missing_ids
  tasks_missing_ids="$(sqlite3 "$tasks_db" "SELECT COUNT(*) FROM tasks WHERE TRIM(COALESCE(task_id,''))='';" 2>/dev/null || echo 0)"
  if ! [[ "$tasks_missing_ids" =~ ^[0-9]+$ ]]; then
    tasks_missing_ids=0
  fi
  if (( tasks_missing_ids > 0 )); then
    die "Task database has ${tasks_missing_ids} task(s) missing task_id; populate valid task ids and rerun work-on-tasks."
  fi

  local now_ts
  now_ts="$(date +%s)"
  throughput_next_checkpoint=$((now_ts + throughput_checkpoint_interval))

  local throughput_msg=""
  if throughput_msg="$(gc_update_throughput_metrics "$tasks_db" "flush")"; then
    if [[ -n "$throughput_msg" ]]; then
      info "$throughput_msg"
    fi
  else
    warn "Failed to prime throughput metrics (flush)."
  fi
  if ! gc_update_throughput_metrics "$tasks_db" "init" >/dev/null; then
    warn "Failed to start throughput metrics window."
  fi

  local token_expect_helper=""
  if token_expect_helper="$(gc_clone_python_tool "token_expectation.py" "${PROJECT_ROOT:-$PWD}")"; then
    gc_clone_python_tool "estimate_remaining_work.py" "${PROJECT_ROOT:-$PWD}" >/dev/null || true
    local token_expect_output=""
    if token_expect_output="$("$python_bin" "$token_expect_helper" "$tasks_db" 2>/dev/null)"; then
      if [[ "$token_expect_output" == *"|"* ]]; then
        IFS='|' read -r wot_avg_tokens_per_sp wot_avg_tokens_samples wot_avg_tokens_points wot_avg_tokens_total wot_avg_recent_count wot_avg_recent_window <<<"$token_expect_output"
        IFS=$' \t\n'
        wot_avg_tokens_per_sp="${wot_avg_tokens_per_sp//[[:space:]]/}"
        wot_avg_tokens_samples="${wot_avg_tokens_samples//[[:space:]]/}"
        wot_avg_tokens_points="${wot_avg_tokens_points//[[:space:]]/}"
        wot_avg_tokens_total="${wot_avg_tokens_total//[[:space:]]/}"
        wot_avg_recent_count="${wot_avg_recent_count//[[:space:]]/}"
        wot_avg_recent_window="${wot_avg_recent_window//[[:space:]]/}"
      fi
    fi
  fi

  local use_story_metadata="${GC_USE_STORY_METADATA:-0}"
  case "${use_story_metadata,,}" in
    1|true|yes|on) use_story_metadata=1 ;;
    *) use_story_metadata=0 ;;
  esac

  if (( use_story_metadata )); then
    gc_align_task_story_slugs "$tasks_db"
    gc_sync_story_totals "$tasks_db"
  else
    info "Skipping story metadata alignment for work-on-tasks (GC_USE_STORY_METADATA=${GC_USE_STORY_METADATA:-0})."
  fi

  if (( force_reset )); then
    info "Resetting backlog progress to pending (--force)."
    gc_reset_task_progress "$tasks_db"
    if (( use_story_metadata )); then
      gc_sync_story_totals "$tasks_db"
    fi
  fi

  local migration_epoch_initial=0
  if migration_epoch_initial="$(gc_fetch_migration_epoch "$tasks_db" 2>/dev/null)"; then
    :
  else
    migration_epoch_initial=0
  fi
  local migration_epoch_baseline="$migration_epoch_initial"
  local migration_transition_triggered=0
  local migration_epoch_refreshes=0
  local migration_epoch_refresh_limit=5
  local migration_transition_hard_stop=0

  local start_task_story_slug="" start_task_story_title="" start_task_position="" start_task_id="" start_task_title=""
  if [[ -n "$start_task_ref" ]]; then
    info "Rewinding backlog starting from task reference '${start_task_ref}'."
    local rewind_info=""
    local original_story_filter="$story_filter"
    if ! rewind_info="$(gc_rewind_backlog_from_task "$tasks_db" "$start_task_ref" "$original_story_filter")"; then
      die "Unable to rewind backlog from task reference '${start_task_ref}'."
    fi
    IFS=$'\t' read -r start_task_story_slug start_task_story_title start_task_position start_task_id start_task_title <<<"$rewind_info"
    if [[ -z "$start_task_story_slug" || -z "$start_task_position" ]]; then
      die "Invalid response while rewinding backlog; aborting."
    fi
    if [[ -n "$original_story_filter" && "${original_story_filter,,}" != "${start_task_story_slug,,}" ]]; then
      info "Normalizing story filter '${original_story_filter}' to story slug '${start_task_story_slug}'."
    fi
    story_filter="$start_task_story_slug"
    gc_sync_story_totals "$tasks_db"
    local story_display="$start_task_story_slug"
    if [[ -n "$start_task_story_title" && "${start_task_story_title,,}" != "${start_task_story_slug,,}" ]]; then
      story_display+=" — ${start_task_story_title}"
    fi
    info "Starting from task ${start_task_position} (${start_task_id:-no-id}) in story ${story_display}."
    if [[ -n "$start_task_title" ]]; then
      info "  ${start_task_title}"
    fi
  fi

  ensure_node_dependencies "$PROJECT_ROOT"
  gc_refresh_discovery_if_needed
  gc_clear_active_task

  if (( prompt_compact )); then
    export GC_PROMPT_COMPACT=1
  else
    unset GC_PROMPT_COMPACT
  fi
  if (( doc_snippets )); then
    export GC_PROMPT_DOC_SNIPPETS=1
  else
    unset GC_PROMPT_DOC_SNIPPETS
  fi

  local state_dir="${PLAN_DIR}/work"
  local runs_dir="${state_dir}/runs"
  local work_logs_root="${LOG_DIR}/work-on-tasks"
  mkdir -p "$runs_dir" "$work_logs_root"

  GC_CONTEXT_FILE_LINES="$context_file_lines"
  if ((${#context_skip_patterns[@]} > 0)); then
    GC_CONTEXT_SKIP_PATTERNS=("${context_skip_patterns[@]}")
  else
    unset GC_CONTEXT_SKIP_PATTERNS
  fi

  export GC_PROMPT_SAMPLE_LINES="$sample_lines"

  local run_stamp
  run_stamp="$(date +%Y%m%d_%H%M%S)"
  export GC_BUDGET_RUN_ID="$run_stamp"
  local run_dir="${runs_dir}/${run_stamp}"
  local run_log_dir="${work_logs_root}/${run_stamp}"
  mkdir -p "$run_dir" "$run_log_dir"

  RUN_DIR="${RUN_DIR:-$run_dir}"
  export RUN_DIR
  mkdir -p "$RUN_DIR"

  if [[ -z "${TMUX:-}${STY:-}" ]]; then
    echo "W: consider running inside tmux/screen" >&2
  fi

  export GC_HARD_TOKENS_PER_TASK="${GC_HARD_TOKENS_PER_TASK:-1000000}"
  WOT_EXCLUDE_STATUSES="${WOT_EXCLUDE_STATUSES:-skip-already-complete,blocked-*,test-env-failed}"

  local backlog_guard_snapshot_output=""
  backlog_snapshot_before_path="${run_dir}/backlog-before.json"
  if backlog_guard_snapshot_output="$(gc_backlog_guard_snapshot "$tasks_db" "" "$backlog_guard_window_value" "$backlog_guard_wip_limit" 2>/dev/null)"; then
    if [[ -n "$backlog_guard_snapshot_output" ]]; then
      printf '%s\n' "$backlog_guard_snapshot_output" >"$backlog_snapshot_before_path"
      backlog_guard_enabled=1
    fi
  else
    backlog_guard_enabled=0
  fi
  local doc_catalog_path="${state_dir}/doc-catalog.json"
  if [[ ! -f "$doc_catalog_path" ]]; then
    mkdir -p "$(dirname "$doc_catalog_path")"
    printf '{"version":1,"documents":{}}\n' >"$doc_catalog_path"
  fi
  export GC_DOC_CATALOG_PATH="$doc_catalog_path"

  if gc_setup_doc_catalog_helpers; then
    export GC_DOC_CATALOG_HELPER="${GC_DOC_CATALOG_PY}"
    export GC_DOC_REGISTRY_HELPER="${GC_DOC_REGISTRY_PY}"
    export GC_DOC_INDEXER_HELPER="${GC_DOC_INDEXER_PY}"
    export doc_catalog="${GC_DOC_CATALOG_PY}"
    export doc_registry="${GC_DOC_REGISTRY_PY}"
    export doc_indexer="${GC_DOC_INDEXER_PY}"
  else
    warn "Doc helpers unavailable; header will fall back to raw sqlite3."
    unset GC_DOC_CATALOG_PY GC_DOC_REGISTRY_PY GC_DOC_INDEXER_PY
    unset GC_DOC_CATALOG_HELPER GC_DOC_REGISTRY_HELPER GC_DOC_INDEXER_HELPER
    unset doc_catalog doc_registry doc_indexer
    unset GC_REPO_OUTLINE_PY GC_TARGETED_SEARCH_PY
    unset GC_REST_CHECK_RUNNER_PY GC_SAFE_SHOW_FILE_PY GC_RUN_SNIPPET_PY
  fi

  local last_progress_ts
  local idle_timeout_triggered=0
  local ctx_file="${run_dir}/context.md"
  gc_build_context_file "$ctx_file" "$STAGING_DIR"
  local context_tail=""
  local context_tail_mode="none"
  export GC_CONTEXT_TAIL_LIMIT="$context_lines"
  if (( context_lines > 0 )); then
    context_tail_mode="digest"
    context_tail="${run_dir}/context_digest.md"
    if ! gc_build_context_digest "$ctx_file" "$context_tail" "$context_lines"; then
      warn "Failed to build context digest; falling back to raw tail."
      context_tail_mode="raw"
      context_tail="${run_dir}/context_tail.md"
      if ! tail -n "$context_lines" "$ctx_file" >"$context_tail" 2>/dev/null; then
        cp "$ctx_file" "$context_tail"
      fi
    fi
  fi
  GC_CONTEXT_TAIL_MODE="$context_tail_mode"
  export GC_CONTEXT_TAIL_MODE

  local context_lines_current="$context_lines"
  local context_file_lines_current="$context_file_lines"
  local context_lines_min=0
  local context_file_lines_min=0
  local context_lines_min_default="${GC_CONTEXT_MIN_LINES:-80}"
  local context_file_lines_min_default="${GC_CONTEXT_MIN_FILE_LINES:-60}"
  if ! [[ "$context_lines_min_default" =~ ^[0-9]+$ ]]; then
    context_lines_min_default=80
  fi
  if ! [[ "$context_file_lines_min_default" =~ ^[0-9]+$ ]]; then
    context_file_lines_min_default=60
  fi
  if (( context_lines_current > 0 )); then
    context_lines_min="$context_lines_min_default"
    if (( context_lines_current < context_lines_min )); then
      context_lines_min="$context_lines_current"
    fi
  fi
  if (( context_file_lines_current > 0 )); then
    context_file_lines_min="$context_file_lines_min_default"
    if (( context_file_lines_current < context_file_lines_min )); then
      context_file_lines_min="$context_file_lines_current"
    fi
  fi
  local context_shrink_iterations=0
  local context_last_shrink_tokens=0
  local context_auto_shrink_threshold="${GC_CONTEXT_AUTO_SHRINK_THRESHOLD:-1000000}"
  if ! [[ "$context_auto_shrink_threshold" =~ ^[0-9]+$ ]]; then
    context_auto_shrink_threshold=1000000
  fi
  info "Work run directory → ${run_dir}"
  gc_git_branching_init
  ln -sfn "${run_dir}" "$(dirname "${run_dir}")/latest" 2>/dev/null || true

  local resume_flag=1
  [[ $resume -eq 1 ]] || resume_flag=0

  local work_failed=0
  # shellcheck disable=SC2034
  local any_changes=0
  local manual_followups=0
  local usage_limit_triggered=0
  local batch_limit_reached=0
  local run_blocked_quota=0

  gc_touch_progress() {
    last_progress_ts="$(date +%s)"
  }

  gc_check_idle_timeout() {
    if (( idle_timeout > 0 )); then
      local now_ts
      now_ts="$(date +%s)"
      if (( now_ts - last_progress_ts >= idle_timeout )); then
        if (( idle_timeout_triggered == 0 )); then
          idle_timeout_triggered=1
          manual_followups=1
          work_failed=1
          warn "Idle timeout reached (${idle_timeout}s without progress); halting run."
        fi
        return 1
      fi
    fi
    return 0
  }

  gc_auto_commit_task() {
    local commit_message="${1:-}"
    shift || true
    local -a raw_paths=("$@")
    GC_LAST_AUTO_COMMIT_HASH=""
    GC_LAST_AUTO_COMMIT_STATUS="skipped"

    local helper_path
    helper_path="$(gc_clone_python_tool "gc_auto_commit_task.py" "${PROJECT_ROOT:-$PWD}")" || return 0

    local helper_output=""
    if ! helper_output="$("${python_bin:-python3}" "$helper_path" "$commit_message" "${raw_paths[@]}")"; then
      warn "    Auto-commit helper failed."
      return 0
    fi

    local status_received=0
    while IFS=$'	' read -r kind field1 rest; do
      [[ -z "$kind" ]] && continue
      case "$kind" in
        MESSAGE)
          local message="$rest"
          case "$field1" in
            info) info "    ${message}" ;;
            warn) warn "    ${message}" ;;
            *) info "    ${message}" ;;
          esac
          ;;
        RESULT)
          GC_LAST_AUTO_COMMIT_STATUS="${field1:-skipped}"
          GC_LAST_AUTO_COMMIT_HASH="${rest:-}"
          status_received=1
          ;;
      esac
    done <<<"$helper_output"

    if (( status_received == 0 )); then
      GC_LAST_AUTO_COMMIT_STATUS="skipped"
      GC_LAST_AUTO_COMMIT_HASH=""
    fi
    return 0
  }

  gc_mark_terminal_state() {
    task_terminal_state="${1:-RUNNING}"
  }

  gc_mark_failure_class() {
    task_failure_class="${1:-NONE}"
  }

  gc_mark_outcome() {
    local outcome_state="${1:-RUNNING}"
    local outcome_class="${2:-}"
    gc_mark_terminal_state "$outcome_state"
    if [[ -n "$outcome_class" ]]; then
      gc_mark_failure_class "$outcome_class"
    fi
  }

  gc_auto_push_helper() {
    local label="${1:-}"
    shift || true
    local -a change_records=("$@")

    GC_LAST_AUTO_COMMIT_STATUS="failed"
    GC_LAST_AUTO_COMMIT_HASH=""
    GC_LAST_AUTO_PUSH_STATUS="skipped"
    GC_LAST_AUTO_PUSH_REMOTE=""
    GC_LAST_AUTO_PUSH_BRANCH=""
    GC_LAST_AUTO_PUSH_ERROR=""

    if [[ "${GC_AUTO_PUSH:-}" != "1" ]]; then
      return 1
    fi

    local project_root="${PROJECT_ROOT:-$PWD}"
    local node_bin="${NODE_BIN:-node}"
    local helper_path="${CLI_ROOT}/src/lib/autoPush.js"

    if [[ -z "$project_root" ]]; then
      warn "    Auto-push skipped: project root unavailable."
      return 1
    fi
    if [[ ! -f "$helper_path" ]]; then
      warn "    Auto-push skipped: helper missing at ${helper_path}."
      return 1
    fi
    if ! command -v "$node_bin" >/dev/null 2>&1; then
      warn "    Auto-push skipped: node runtime not found."
      return 1
    fi
    if ! command -v git >/dev/null 2>&1; then
      warn "    Auto-push skipped: git command not available."
      return 1
    fi
    if ! git -C "$project_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      warn "    Auto-push skipped: not a git repository."
      return 1
    fi

    local summary_path
    summary_path="$(mktemp)" || return 1
    local summary_py=$'import json, sys
repo = sys.argv[1]
label = sys.argv[2]
records = []
for raw in sys.argv[3:]:
    if "\t" in raw:
        op, path = raw.split("\t", 1)
    else:
        op, path = "?", raw
    op = op or "?"
    records.append({"op": op, "path": path})
summary = {"cwd": repo, "files": records}
if label:
    summary["label"] = label
print(json.dumps(summary))'
    if ! "$python_bin" -c "$summary_py" "$project_root" "$label" "${change_records[@]}" >"$summary_path"; then
      rm -f "$summary_path"
      warn "    Auto-push skipped: failed to prepare summary payload."
      return 1
    fi

    local autopush_stdout=""
    if ! autopush_stdout="$(GC_AUTOPUSH_EXPECT_JSON=1 "$node_bin" "$helper_path" "$summary_path" 2>&1)"; then
      rm -f "$summary_path"
      GC_LAST_AUTO_PUSH_STATUS="failed"
      GC_LAST_AUTO_PUSH_ERROR="$autopush_stdout"
      return 1
    fi
    rm -f "$summary_path"

    if [[ -z "$autopush_stdout" ]]; then
      autopush_stdout='{}'
    fi

    local parse_output=""
    local autopush_parse_py=$'import json, sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    payload = {}
commit_status = payload.get("commitStatus", "skipped")
commit_sha = payload.get("commitSha") or ""
push_status = payload.get("pushStatus", "skipped")
remote = payload.get("remote") or ""
branch = payload.get("branch") or ""
error = payload.get("error") or ""
print(commit_status)
print(commit_sha)
print(push_status)
print(remote)
print(branch)
print(error)'
    if ! parse_output="$("$python_bin" -c "$autopush_parse_py" "$autopush_stdout" 2>/dev/null)"; then
      parse_output=$'failed\n\nfailed\n\n\n'
    fi

    IFS=$'\n' read -r GC_LAST_AUTO_COMMIT_STATUS GC_LAST_AUTO_COMMIT_HASH GC_LAST_AUTO_PUSH_STATUS GC_LAST_AUTO_PUSH_REMOTE GC_LAST_AUTO_PUSH_BRANCH GC_LAST_AUTO_PUSH_ERROR <<<"$parse_output"

    if [[ "$GC_LAST_AUTO_COMMIT_STATUS" == "failed" || "$GC_LAST_AUTO_PUSH_STATUS" == "failed" ]]; then
      return 1
    fi

    return 0
  }

  gc_finalize_task_snapshot() {
    local label="${1:-task}"
    local task_ref="${2:-task}"
    local attempt_label="${3:-1}"
    local status_label="${4:-unknown}"
    local commit_mode="${5:-snapshot}"
    shift 5
    local -a change_records=("$@")

    local project_root="${PROJECT_ROOT:-$PWD}"
    if [[ -z "$project_root" || ! -d "$project_root" ]]; then
      return 0
    fi
    if ! command -v git >/dev/null 2>&1; then
      return 0
    fi
    local pending_status
    pending_status="$(git -C "$project_root" status --porcelain=v1 --untracked-files=all 2>/dev/null || true)"
    if [[ -z "$pending_status" ]]; then
      return 0
    fi

    local original_auto_push="${GC_AUTO_PUSH:-}"
    local original_remote="${GC_AUTO_PUSH_REMOTE:-}"
    local original_branch="${GC_AUTO_PUSH_BRANCH:-}"
    local original_task_ref="${GC_AUTOPUSH_TASK_REF:-}"
    local original_attempt_ref="${GC_AUTOPUSH_ATTEMPT_REF:-}"
    local original_commit_message="${GC_AUTOPUSH_COMMIT_MESSAGE:-}"
    local original_allow_empty="${GC_ALLOW_EMPTY_COMMIT:-}"

    GC_AUTO_PUSH=1
    unset GC_AUTO_PUSH_REMOTE
    unset GC_AUTO_PUSH_BRANCH

    export GC_AUTOPUSH_TASK_REF="$task_ref"
    export GC_AUTOPUSH_ATTEMPT_REF="attempt-${attempt_label}"
    if [[ "$commit_mode" == "snapshot" ]]; then
      export GC_AUTOPUSH_COMMIT_MESSAGE="chore(gpt-creator): snapshot ${label} attempt ${attempt_label} (${status_label})"
    else
      unset GC_AUTOPUSH_COMMIT_MESSAGE
    fi
    export GC_ALLOW_EMPTY_COMMIT=0

    local finalize_attempt=1
    local finalize_success=0
    local finalize_error=""
    local retry_cap="${GC_RETRY_PUSH_MAX:-3}"
    if ! [[ "$retry_cap" =~ ^[0-9]+$ ]]; then
      retry_cap=3
    fi

    while (( finalize_attempt <= retry_cap )); do
      if gc_auto_push_helper "$label" "${change_records[@]}"; then
        finalize_success=1
        break
      fi
      finalize_error="${GC_LAST_AUTO_PUSH_ERROR:-auto-push failure}"
      sleep $((finalize_attempt * 2))
      ((finalize_attempt++))
    done

    if [[ -n "$original_auto_push" ]]; then
      GC_AUTO_PUSH="$original_auto_push"
    else
      unset GC_AUTO_PUSH
    fi
    if [[ -n "$original_remote" ]]; then
      GC_AUTO_PUSH_REMOTE="$original_remote"
    else
      unset GC_AUTO_PUSH_REMOTE
    fi
    if [[ -n "$original_branch" ]]; then
      GC_AUTO_PUSH_BRANCH="$original_branch"
    else
      unset GC_AUTO_PUSH_BRANCH
    fi
    if [[ -n "$original_task_ref" ]]; then
      export GC_AUTOPUSH_TASK_REF="$original_task_ref"
    else
      unset GC_AUTOPUSH_TASK_REF
    fi
    if [[ -n "$original_attempt_ref" ]]; then
      export GC_AUTOPUSH_ATTEMPT_REF="$original_attempt_ref"
    else
      unset GC_AUTOPUSH_ATTEMPT_REF
    fi
    if [[ -n "$original_commit_message" ]]; then
      export GC_AUTOPUSH_COMMIT_MESSAGE="$original_commit_message"
    else
      unset GC_AUTOPUSH_COMMIT_MESSAGE
    fi
    if [[ -n "$original_allow_empty" ]]; then
      export GC_ALLOW_EMPTY_COMMIT="$original_allow_empty"
    else
      unset GC_ALLOW_EMPTY_COMMIT
    fi

    if (( finalize_success )); then
      return 0
    fi

    warn "    Auto-finalize snapshot failed: ${finalize_error}"
    return 1
  }

  gc_auto_push_only() {
    GC_LAST_AUTO_PUSH_STATUS="skipped"
    GC_LAST_AUTO_PUSH_REMOTE=""
    GC_LAST_AUTO_PUSH_BRANCH=""
    GC_LAST_AUTO_PUSH_ERROR=""

    if [[ "${GC_AUTO_PUSH:-}" != "1" ]]; then
      return 0
    fi

    local project_root="${PROJECT_ROOT:-$PWD}"
    if [[ -z "$project_root" ]]; then
      warn "    Auto-push skipped: project root unavailable."
      return 1
    fi
    if ! command -v git >/dev/null 2>&1; then
      warn "    Auto-push skipped: git command not available."
      return 1
    fi
    if ! git -C "$project_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      warn "    Auto-push skipped: not a git repository."
      return 1
    fi

    local current_branch
    current_branch="$(git -C "$project_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    local resolved_branch="${GC_AUTO_PUSH_BRANCH:-$current_branch}"
    local resolved_remote="${GC_AUTO_PUSH_REMOTE:-}"

    if [[ -z "$resolved_remote" && -n "$resolved_branch" ]]; then
      resolved_remote="$(git -C "$project_root" config --get "branch.${resolved_branch}.remote" 2>/dev/null || true)"
    fi
    if [[ -z "$resolved_remote" && -n "$current_branch" ]]; then
      resolved_remote="$(git -C "$project_root" config --get "branch.${current_branch}.remote" 2>/dev/null || true)"
    fi
    if [[ -z "$resolved_remote" ]]; then
      resolved_remote="origin"
    fi

    local push_branch="$resolved_branch"
    if [[ -z "$push_branch" || "$push_branch" == "HEAD" ]]; then
      push_branch="$current_branch"
    fi

    GC_LAST_AUTO_PUSH_REMOTE="$resolved_remote"
    GC_LAST_AUTO_PUSH_BRANCH="$push_branch"

    if [[ "$resolved_remote" == "__skip__" ]]; then
      GC_LAST_AUTO_PUSH_STATUS="skipped"
      return 0
    fi
    if ! git -C "$project_root" remote get-url "$resolved_remote" >/dev/null 2>&1; then
      warn "    Auto-push skipped: remote ${resolved_remote} not configured."
      GC_LAST_AUTO_PUSH_STATUS="skipped"
      return 1
    fi

    local -a push_args=("$resolved_remote")
    if [[ -n "$push_branch" && "$push_branch" != "HEAD" ]]; then
      push_args+=("$push_branch")
    fi

    if ! git -C "$project_root" push "${push_args[@]}"; then
      warn "    Auto-push failed: git push ${push_args[*]} returned non-zero."
      GC_LAST_AUTO_PUSH_STATUS="failed"
      return 1
    fi

    GC_LAST_AUTO_PUSH_STATUS="pushed"
    return 0
  }


  gc_diff_fingerprint() {
    if [[ -z "${PROJECT_ROOT:-}" ]]; then
      printf 'no-project-%s
' "$RANDOM$RANDOM$$"
      return 0
    fi
    if ! command -v git >/dev/null 2>&1; then
      printf 'nogit-%s
' "$RANDOM$RANDOM$$"
      return 0
    fi
    local diff_payload
    if ! diff_payload="$( (git -C "$PROJECT_ROOT" diff --shortstat --no-ext-diff || true; printf '
'; git -C "$PROJECT_ROOT" diff --numstat --no-ext-diff || true; printf '
'; git -C "$PROJECT_ROOT" diff --name-only --no-ext-diff || true) 2>/dev/null )"; then
      printf 'diff-error-%s
' "$RANDOM$RANDOM$$"
      return 0
    fi
    if command -v "$python_bin" >/dev/null 2>&1; then
      local diff_hash_helper
      if diff_hash_helper="$(gc_clone_python_tool "diff_payload_hash.py" "${PROJECT_ROOT:-$PWD}")"; then
        "$python_bin" "$diff_hash_helper" "$diff_payload"
        return 0
      fi
    fi
    if command -v shasum >/dev/null 2>&1; then
      printf '%s' "$diff_payload" | shasum -a 1 2>/dev/null | awk '{print $1}'
    elif command -v sha1sum >/dev/null 2>&1; then
      printf '%s' "$diff_payload" | sha1sum 2>/dev/null | awk '{print $1}'
    else
      printf 'hash-%s
' "$(printf '%s' "$diff_payload" | wc -c | awk '{print $1}')"
    fi
  }


  gc_create_empty_apply_checkpoint() {
    local story_slug="$1"
    local task_id="$2"
    local root="${PROJECT_ROOT:-$PWD}"
    [[ -n "$story_slug" ]] || story_slug="story"
    [[ -n "$task_id" ]] || task_id="task"
    local checkpoint_dir="${root}/.gpt-creator/logs/empty-apply/${story_slug}/${task_id}"
    local checkpoint_file="${checkpoint_dir}/checkpoint.md"
    mkdir -p "$checkpoint_dir" || return 1
  if [[ ! -f "$checkpoint_file" ]]; then
    local checkpoint_timestamp
    checkpoint_timestamp="$(date -u +%FT%TZ)"
    (
      set -a
      export GC_CHECKPOINT_TITLE="${story_slug}/${task_id}"
      export GC_CHECKPOINT_TIMESTAMP="$checkpoint_timestamp"
      set +a
      gc_render_template "checkpoints/empty_apply_checkpoint.md.tmpl"
    ) >"$checkpoint_file"
  fi
    local checkpoint_rel
    local checkpoint_helper
    checkpoint_helper="$(gc_clone_python_tool "checkpoint_relative_path.py" "${PROJECT_ROOT:-$PWD}")" || checkpoint_helper=""
    if [[ -n "$checkpoint_helper" ]]; then
      checkpoint_rel="$("$python_bin" "$checkpoint_helper" "$checkpoint_file" "$root")"
    else
      checkpoint_rel="$checkpoint_file"
    fi
    printf '%s\n' "$checkpoint_rel"
  }

  gc_touch_progress

  local processed_total=0
  local processed_any_total=0
  local remaining_tasks=0
  local no_progress_iterations=0
  local memory_cycle_single=0
  local no_progress_story_limit="${GC_NO_PROGRESS_STORY_LIMIT:-40}"
  if ! [[ "$no_progress_story_limit" =~ ^[0-9]+$ ]]; then
    no_progress_story_limit=40
  fi
  local story_plan_helper=""
  story_plan_helper="$(gc_clone_python_tool "story_scheduler.py" "${PROJECT_ROOT:-$PWD}")" || return 1

  while :; do
    if gc_check_idle_timeout; then :; else break; fi
    local iteration_processed_any=0
    local iteration_processed=0
    local continue_current_run=0
    local progress_safety_break=0
    local no_progress_story_count=0
    local pending_tasks=0

    local effective_batch_size="$batch_size"
    if (( memory_cycle )); then
      if (( memory_cycle_single )); then
        effective_batch_size=1
      else
        effective_batch_size="$batch_size"
      fi
    fi

    while IFS=$'\t' read -r sequence slug story_id story_title epic_id epic_title total_tasks next_task completed status; do
      if [[ -z "${sequence}${slug}${story_id}${story_title}${epic_id}${epic_title}" ]]; then
        continue
      fi

      if ! gc_check_idle_timeout; then
        break
      fi

      iteration_processed_any=1
      local story_progress_before="$iteration_processed"

      if (( throughput_checkpoint_interval > 0 )); then
        now_ts="$(date +%s)"
        if (( throughput_next_checkpoint == 0 || now_ts >= throughput_next_checkpoint )); then
          local throughput_checkpoint_msg=""
          if throughput_checkpoint_msg="$(gc_update_throughput_metrics "$tasks_db" "checkpoint")"; then
            if [[ -n "$throughput_checkpoint_msg" ]]; then
              info "$throughput_checkpoint_msg"
            fi
          else
            warn "Failed to checkpoint throughput metrics."
          fi
          throughput_next_checkpoint=$((now_ts + throughput_checkpoint_interval))
        fi
      fi

    : "${total_tasks:=0}"; : "${next_task:=0}"
    local total_tasks_int=0
    if [[ "$total_tasks" =~ ^[0-9]+$ ]]; then
      total_tasks_int=$((total_tasks))
    fi
    local next_task_int=0
    if [[ "$next_task" =~ ^[0-9]+$ ]]; then
      next_task_int=$((next_task))
    fi

    if (( migration_transition_hard_stop )); then
      break
    fi

    if (( migration_transition_triggered )); then
      break
    fi

    local migration_epoch_current=""
    if migration_epoch_current="$(gc_fetch_migration_epoch "$tasks_db" 2>/dev/null)"; then
      if [[ "$migration_epoch_current" != "$migration_epoch_baseline" ]]; then
        migration_transition_triggered=1
        (( migration_epoch_refreshes++ ))
        local prior_epoch="$migration_epoch_baseline"
        if (( migration_epoch_refreshes > migration_epoch_refresh_limit )); then
          warn "  Migration epoch changed ${migration_epoch_refreshes} times within a single work-on-tasks run; pausing to avoid an infinite loop."
          work_failed=1
          manual_followups=1
          migration_transition_hard_stop=1
          break
        fi
        if (( binder_clear_on_migration )); then
          gc_binder_clear_story "$PROJECT_ROOT" "${epic_id:-}" "$slug"
          info "  Cleared binder cache for story ${slug} due to migration epoch change."
        fi
        info "  Migration epoch changed (${prior_epoch} → ${migration_epoch_current}); refreshing backlog before continuing."
        migration_epoch_baseline="$migration_epoch_current"
        break
      fi
    fi

    printf -v story_prefix "%03d" "${sequence:-0}"
    [[ -n "$slug" ]] || slug="story-${story_prefix}"
    local story_run_dir="${run_dir}/story_${story_prefix}_${slug}"
    local story_log_dir="${run_log_dir}/story_${story_prefix}_${slug}"
    mkdir -p "${story_run_dir}/prompts" "${story_run_dir}/out" "${story_run_dir}/reports" "$story_log_dir"
    local report_dir="${story_run_dir}/reports"

    info "Story ${story_prefix} (${story_id:-$slug}) — ${story_title:-Unnamed}"
    export GC_BUDGET_STORY_ID="${story_id:-$slug}"

    # Always trust tasks.db for counts; ignore stale story metadata.
    local stats=""
    local actual_total=0 actual_completed=0
    if stats="$(gc_fetch_story_task_counts "$tasks_db" "$slug" 2>/dev/null)"; then
      IFS=$'\t' read -r actual_total actual_completed <<<"$stats"
      [[ "$actual_total" =~ ^[0-9]+$ ]] || actual_total=0
      [[ "$actual_completed" =~ ^[0-9]+$ ]] || actual_completed=0
    fi
    total_tasks_int=$actual_total
    if (( actual_completed > total_tasks_int )); then
      actual_completed="$total_tasks_int"
    fi
    if (( next_task_int < actual_completed )); then
      next_task_int="$actual_completed"
    fi
    if (( total_tasks_int == 0 )); then
      info "  No tasks found in tasks.db for ${slug}; skipping."
      if (( keep_artifacts == 0 )); then
        rmdir "${story_run_dir}/prompts" 2>/dev/null || true
        rmdir "${story_run_dir}/out" 2>/dev/null || true
      fi
      continue
    fi
    gc_update_work_state "$tasks_db" "$slug" "pending" "$actual_completed" "$total_tasks_int" "$run_stamp"

    if (( total_tasks_int > 0 && next_task_int >= total_tasks_int )); then
      info "  All ${total_tasks_int} task(s) already complete; skipping prompt preparation."
      gc_update_work_state "$tasks_db" "$slug" "complete" "$total_tasks_int" "$total_tasks_int" "$run_stamp"
      if (( keep_artifacts == 0 )); then
        rmdir "${story_run_dir}/prompts" 2>/dev/null || true
        rmdir "${story_run_dir}/out" 2>/dev/null || true
      fi
      continue
    fi

    if (( total_tasks_int == 0 )); then
      info "  No tasks for this story; marking complete."
      gc_update_work_state "$tasks_db" "$slug" "complete" 0 0 "$run_stamp"
      if (( keep_artifacts == 0 )); then
        rmdir "${story_run_dir}/prompts" 2>/dev/null || true
        rmdir "${story_run_dir}/out" 2>/dev/null || true
      fi
      continue
    fi

    gc_update_work_state "$tasks_db" "$slug" "in-progress" "$next_task_int" "$total_tasks_int" "$run_stamp"

    local task_index
    if [[ "${GC_SKIP_STORY_PROMPT_SYNC:-0}" == "1" ]]; then
      info "  Skipping prompt preparation (GC_WORK_PREPARE_PROMPTS=0)."
    else
      info "  Preparing prompts and context…"
    fi
    local story_failed=0
    local story_task_consumed=0
    local single_task_fallback="${TASK_FALLBACK:-}"
    single_task_fallback="${single_task_fallback,,}"
    for (( task_index = next_task_int; task_index < total_tasks_int; task_index++ )); do
      if (( single_task_mode )) && [[ -n "$single_task_fallback" ]]; then
        local current_task_fallback
        printf -v current_task_fallback "%s:%d" "${slug,,}" $((task_index + 1))
        if [[ "${current_task_fallback,,}" != "$single_task_fallback" ]]; then
          continue
        fi
      fi
      gc_clear_active_task
      if ! gc_check_idle_timeout; then
        break
      fi
      if (( throughput_checkpoint_interval > 0 )); then
        now_ts="$(date +%s)"
        if (( throughput_next_checkpoint == 0 || now_ts >= throughput_next_checkpoint )); then
          local throughput_checkpoint_msg=""
          if throughput_checkpoint_msg="$(gc_update_throughput_metrics "$tasks_db" "checkpoint")"; then
            if [[ -n "$throughput_checkpoint_msg" ]]; then
              info "$throughput_checkpoint_msg"
            fi
          else
            warn "Failed to checkpoint throughput metrics."
          fi
          throughput_next_checkpoint=$((now_ts + throughput_checkpoint_interval))
        fi
      fi
      if (( effective_batch_size > 0 && iteration_processed >= effective_batch_size )); then
        batch_limit_reached=1
        break
      fi
      local task_number
      printf -v task_number "%03d" $((task_index + 1))
      local prompt_path="${story_run_dir}/prompts/task_${task_number}.prompt.md"
      local output_path="${story_run_dir}/out/task_${task_number}.out.md"
      local prompt_base_path="${prompt_path}.base"
      local stage_baseline_retrieve="${GC_BUDGET_STAGE_TOTAL_RETRIEVE:-0}"
      local stage_baseline_plan="${GC_BUDGET_STAGE_TOTAL_PLAN:-0}"
      local stage_baseline_patch="${GC_BUDGET_STAGE_TOTAL_PATCH:-0}"
      local stage_baseline_verify="${GC_BUDGET_STAGE_TOTAL_VERIFY:-0}"

      local prompt_meta
      if ! prompt_meta="$(gc_write_task_prompt "$tasks_db" "$slug" "$task_index" "$prompt_path" "$context_tail" "$CODEX_MODEL_CODE" "$PROJECT_ROOT" "$STAGING_DIR")"; then
        warn "  Failed to build prompt for task index ${task_index}; skipping task."
        manual_followups=1
        work_failed=1
        continue
      fi
      local prompt_meta_path="${prompt_path}.meta.json"
      if [[ -z "$prompt_slim_helper" ]]; then
        prompt_slim_helper="$(gc_clone_python_tool "wot_slim_prompt.py" "${PROJECT_ROOT:-$PWD}")" || return 1
      fi
      "$python_bin" "$prompt_slim_helper" "$prompt_path"
      if ! cp -f "$prompt_path" "$prompt_base_path"; then
        warn "  Unable to cache base prompt for task ${task_number}; retries may miss helper instructions."
      fi

      local prompt_est_tokens_raw
      prompt_est_tokens_raw="$(gc_estimate_tokens_from_bytes "$prompt_path")"
      if ! [[ "$prompt_est_tokens_raw" =~ ^[0-9]+$ ]]; then
        prompt_est_tokens_raw=0
      fi

      local task_id="" task_title="" task_story_points="" task_status_current="" task_locked_flag="0" task_status_reason=""
      IFS=$'\t' read -r task_id task_title task_story_points task_status_current task_locked_flag task_status_reason <<<"$prompt_meta"
      local task_id_lower="${task_id,,}"
      if (( single_task_mode )); then
        local fallback_key
        fallback_key="$(printf '%s:%d' "${slug,,}" $((task_index + 1)))"
        local matches_filter=0
        if [[ -n "$task_filter_normalized" ]]; then
          if [[ -n "$task_id_lower" && "$task_id_lower" == "$task_filter_normalized" ]]; then
            matches_filter=1
          elif [[ "$fallback_key" == "$task_filter_normalized" ]]; then
            matches_filter=1
          fi
        fi
        if (( matches_filter == 0 )) && [[ -n "$single_task_fallback" ]]; then
          if [[ "${fallback_key,,}" == "$single_task_fallback" ]]; then
            matches_filter=1
          fi
        fi
        if (( matches_filter == 0 )); then
          if (( keep_artifacts == 0 )); then
            rm -f "$prompt_path" "$output_path" "$prompt_meta_path" "$prompt_base_path"
          fi
          continue
        fi
        story_task_consumed=1
      fi
      local banner_task_id="${task_id:-no-id}"
      local task_start_epoch
      task_start_epoch="$(date +%s)"
      local task_tokens_total=0
      local task_llm_prompt_tokens=0
      local task_llm_completion_tokens=0
      local task_prompt_estimate=0
      local task_duration_seconds=0
      local task_duration_display=""
      local task_tokens_display=""
      local task_story_points_display="—"
      if [[ -n "$task_story_points" ]]; then
        task_story_points_display="$task_story_points"
      fi

      local task_status_original="$task_status_current"
      local task_status_lower="${task_status_original,,}"
      local task_locked_migration=0
      if [[ "$task_locked_flag" =~ ^[0-9]+$ ]] && (( task_locked_flag > 0 )); then
        task_locked_migration=1
      fi
      local task_status_reason_current="$task_status_reason"
      local terminal_locked_regex='^(complete|completed|completed-no-changes|ready-to-review|ready_to_review|ready-for-qa|ready_for_qa|dead-letter|permanent-fail|blocked-budget|blocked-quota|blocked-merge-conflict|blocked-schema-drift|blocked-schema-guard-error|blocked-dependency\([^)]+\)|skipped-already-complete)$'
      if [[ "$task_status_lower" == blocked-dependency\(* ]]; then
        local blocked_reason="${task_status_reason_current:-${task_status_original}}"
        warn "  Task ${task_number} (${banner_task_id}) blocked by dependency: ${blocked_reason}; skipping for now."
        manual_followups=1
        continue
      fi

      printf '\n'
      local task_codex_step="patch"
      local task_codex_model=""
      local task_codex_reasoning=""
      gc_codex_profile_for_step "$task_codex_step" task_codex_model task_codex_reasoning

      local task_alias_line="Working on task ${task_number} (${banner_task_id})"
      local task_summary_line="${task_title:-(untitled)}"
      local task_provider_display="${CODEX_BIN:-codex}"
      local task_workdir_display="${PROJECT_ROOT:-$PWD}"
      gc_render_task_start_panel \
        "$banner_task_id" \
        "$task_alias_line" \
        "$task_summary_line" \
        "$task_codex_model" \
        "$task_provider_display" \
        "$task_workdir_display" \
        "$task_codex_reasoning" \
        "$run_stamp" \
        "$task_codex_step"
      local current_task_id="${task_id:-${banner_task_id:-${slug:-story}-${task_number}}}"
      CURRENT_TASK_ID="$current_task_id"
      export CURRENT_TASK_ID
      gc_git_begin_task_branch "${CURRENT_TASK_ID}"
      info "  → ${task_alias_line}"
      info "    ${task_summary_line}"

      local call_name="story-${slug}-task-${task_number}"
      local codex_ok=0
      local attempt=0
      local max_attempts=2
      gc_touch_progress
      local prompt_augmented=0
      local contract_guard_injected=0
      local keep_output=$keep_artifacts
      local break_after_update=0
      local task_result_status="in-progress"
      local task_needs_review=0
      local task_verify_status="skipped"
      local task_verify_summary=""
      local task_verify_details=""
      local task_verify_report=""
      local task_terminal_state="RUNNING"
      local task_failure_class="NONE"
      local delta_prompt_injected=0
      local task_meta_plan_flag=0
      local task_meta_focus_flag=0
      local task_meta_no_changes_flag=0
      local task_meta_already_flag=0
      local -a task_notes=()
      local -a task_written_paths=()
      local -a task_patched_paths=()
      local task_ref_for_verify="${task_id:-${banner_task_id:-${slug:-story}-${task_number}}}"
      if [[ -z "$task_ref_for_verify" ]]; then
        task_ref_for_verify="${slug:-story}-${task_number}"
      fi
      local -a task_commands=()
      local -a task_auto_push_records=()
      local task_changes_applied=0
      local task_change_operations=0
      local task_last_change_operations=0
      local task_attempt_signature=""
      local task_outcome_reason=""
      local task_last_signature=""
      local task_last_changes_count="0"
      # shellcheck disable=SC2034
      local task_last_outcome_reason=""
      local previous_attempt_signature=""
      local apply_status="pending"
      local skip_codex_reason="prompt-blocked"
      local task_report_path="${report_dir}/task_${task_number}.log"
      local task_log_archive_path="${story_log_dir}/task_${task_number}.log"
      local task_change_sizes=""
      local diff_last_transition=""
      local diff_prev_after_sig=""
      local diff_prev_prev_after_sig=""
      local diff_stall_count=0
      local turn_diff_prev_hash=""
      local turn_diff_repeat_count=0
      local diff_guard_enabled=1
      if (( diff_guard_stall_limit <= 0 && diff_guard_file_cooldown <= 0 && diff_guard_turn_repeat_limit <= 0 )); then
        diff_guard_enabled=0
      fi
      local empty_checkpoint_created=0
      local attempt_tokens=0
      local codex_attempted=0
      local skip_codex=0
      local blocked_stop_run=0
      local prompt_status="ok"
      local prompt_soft_limit_value=0
      local prompt_hard_limit_value=0
      # shellcheck disable=SC2034
      local prompt_stop_on_overbudget="true"
      local prompt_token_estimate=0
      local prompt_pruned_bytes=0
      local prompt_pruned_items="[]"
      local prompt_binder_status=""
      local prompt_binder_reason=""
      gc_update_task_state "$tasks_db" "$slug" "$task_index" "in-progress" "$run_stamp"
      export GC_ACTIVE_TASK_DB="$tasks_db"
      export GC_ACTIVE_TASK_SLUG="$slug"
      export GC_ACTIVE_TASK_INDEX="$task_index"
      export GC_ACTIVE_TASK_FINALIZED=0
      export GC_ACTIVE_RUN_STAMP="$run_stamp"
      export GC_ACTIVE_TASK_NUMBER="$task_number"
      export GC_ACTIVE_TASK_ID="$task_id"
      export GC_ACTIVE_TASK_REPORT="$task_report_path"
      export GC_ACTIVE_TASK_ARCHIVE="$task_log_archive_path"
      export GC_ACTIVE_TASK_PROMPT="$prompt_path"
      export GC_ACTIVE_TASK_OUTPUT="$output_path"
      export GC_BUDGET_TASK_ID="${task_id:-$banner_task_id}"

      local prompt_meta_path="${prompt_path}.meta.json"
      if [[ -f "$prompt_meta_path" ]]; then
        local prompt_meta_helper
        prompt_meta_helper="$(gc_clone_python_tool "prompt_meta_summary.py" "${PROJECT_ROOT:-$PWD}")" || prompt_meta_helper=""
        if [[ -n "$prompt_meta_helper" ]]; then
          local _
          read -r prompt_status prompt_soft_limit_value prompt_hard_limit_value prompt_stop_on_overbudget prompt_token_estimate prompt_pruned_bytes prompt_pruned_items _ prompt_binder_status prompt_binder_reason < <(
            "$python_bin" "$prompt_meta_helper" "$prompt_meta_path"
          )
        fi
      fi
      GC_CURRENT_PRUNED_ITEMS="$prompt_pruned_items"
      if [[ "$prompt_token_estimate" =~ ^[0-9]+$ ]]; then
        task_prompt_estimate=$((prompt_token_estimate))
      else
        task_prompt_estimate=0
      fi
      local retrieve_tokens=0
      if [[ "$prompt_pruned_bytes" =~ ^[0-9]+$ && prompt_pruned_bytes -gt 0 ]]; then
        retrieve_tokens=$((prompt_pruned_bytes / 4))
      fi
      local retrieve_tool_bytes="{}"
      if [[ "$prompt_pruned_bytes" =~ ^[0-9]+$ && prompt_pruned_bytes -gt 0 ]]; then
        retrieve_tool_bytes="{\"show-file\": ${prompt_pruned_bytes}}"
      fi
      gc_budget_log_stage "retrieve" "$retrieve_tokens" 0 "$retrieve_tokens" 0 "$prompt_pruned_items" "$retrieve_tool_bytes" "false"
      if gc_budget_stage_tripped "retrieve"; then
        local retrieve_limit_value
        retrieve_limit_value="$(gc_budget_get_stage_limit "retrieve")"
        local max_retrieve_cap="${GC_AUTOBUDGET_RETRIEVE_MAX:-1000000}"
        local new_retrieve_cap="$retrieve_limit_value"
        if (( retrieve_tokens > retrieve_limit_value )); then
          new_retrieve_cap=$((retrieve_tokens + retrieve_tokens / 10 + 2048))
        else
          new_retrieve_cap=$((retrieve_limit_value + retrieve_limit_value / 2 + 2048))
        fi
        if (( new_retrieve_cap > max_retrieve_cap )); then
          new_retrieve_cap="$max_retrieve_cap"
        fi
        if (( new_retrieve_cap > retrieve_limit_value )); then
          gc_budget_set_stage_limit "retrieve" "$new_retrieve_cap"
          task_notes+=("Retrieve stage exceeded budget limit (${retrieve_tokens}/${retrieve_limit_value}); raised cap to ${new_retrieve_cap} tokens and retrying prompt build.")
          gc_budget_reset_stage_tracking
          rm -f "$prompt_path" "$output_path" "$prompt_base_path"
          if (( attempt > 0 )); then
            (( attempt-- ))
          fi
          continue
        fi
        task_notes+=("Retrieve stage exceeded maximum automatic budget (${retrieve_tokens}/${retrieve_limit_value}); deferring task for follow-up.")
        skip_codex=1
        codex_ok=1
        manual_followups=1
        keep_output=0
        task_result_status="retryable"
        apply_status="prompt-blocked"
        skip_codex_reason="stage-limit"
        break_after_update=1
        continue
      else
        gc_budget_log_stage "plan" "$prompt_token_estimate" 0 "$prompt_token_estimate" 0 "$prompt_pruned_items" "{}" "false"
        local guard_safe_limit="${GC_SAFE_PROMPT_TOKENS:-8000}"
        if ! [[ "$guard_safe_limit" =~ ^[0-9]+$ ]]; then
          guard_safe_limit=8000
        fi
        guard_safe_limit=$((guard_safe_limit))
        local guard_prompt_estimate=0
        if [[ "$prompt_token_estimate" =~ ^[0-9]+$ ]]; then
          guard_prompt_estimate=$((prompt_token_estimate))
        elif [[ "$prompt_est_tokens_raw" =~ ^[0-9]+$ ]]; then
          guard_prompt_estimate=$((prompt_est_tokens_raw))
        fi
        if gc_budget_stage_should_skip "patch"; then
          local guard_skip_reason
          guard_skip_reason="$(gc_budget_stage_skip_reason "patch")"
          [[ -z "$guard_skip_reason" ]] && guard_skip_reason="auto-abandon"
          if [[ "$guard_skip_reason" == auto-abandon* ]] && (( guard_prompt_estimate >= 0 && guard_prompt_estimate <= guard_safe_limit )); then
            if ! gc_env_truthy "${GC_DISABLE_AUTO_ABANDON:-}"; then
              export GC_DISABLE_AUTO_ABANDON=1
            fi
            gc_budget_set_stage_skip "patch" 0 ""
            offenders_auto_flag=0
          fi
        fi
        if gc_budget_stage_should_skip "patch"; then
          skip_codex=1
          codex_ok=1
          task_needs_review=0
          manual_followups=0
          keep_output=0
          task_result_status="abandoned-for-budget"
          apply_status="auto-abandon"
          skip_codex_reason="$(gc_budget_stage_skip_reason "patch")"
          [[ -z "$skip_codex_reason" ]] && skip_codex_reason="auto-abandon"
        fi
      fi

      : "${GC_TASK_TOKEN_HARD_LIMIT:=1000000}"
      local prompt_token_hard_cap
      prompt_token_hard_cap="$(gc_parse_int "${GC_TASK_TOKEN_HARD_LIMIT}" 1000000)"
      if ! [[ "$prompt_token_hard_cap" =~ ^[0-9]+$ ]]; then
        prompt_token_hard_cap=1000000
      else
        prompt_token_hard_cap=$((prompt_token_hard_cap))
      fi
      local prompt_estimate_tokens=$((prompt_est_tokens_raw))
      local current_prompt_cap_int=0
      if [[ "$prompt_hard_limit_value" =~ ^[0-9]+$ ]]; then
        current_prompt_cap_int=$((prompt_hard_limit_value))
      elif [[ "$prompt_soft_limit_value" =~ ^[0-9]+$ ]]; then
        current_prompt_cap_int=$((prompt_soft_limit_value))
      else
        current_prompt_cap_int=$prompt_token_hard_cap
      fi

      if (( prompt_token_hard_cap > 0 )) && (( prompt_estimate_tokens > prompt_token_hard_cap )) && (( skip_codex == 0 )); then
        local max_prompt_cap="${GC_AUTOBUDGET_PROMPT_MAX:-1000000}"
        local new_prompt_cap=$((prompt_estimate_tokens + prompt_estimate_tokens / 10 + 2048))
        if (( new_prompt_cap > max_prompt_cap )); then
          new_prompt_cap="$max_prompt_cap"
        fi
        if (( new_prompt_cap > current_prompt_cap_int )); then
          warn "    Prompt ~${prompt_estimate_tokens} tokens exceeds hard cap ${current_prompt_cap_int}; raising cap to ${new_prompt_cap} and retrying."
          GC_TASK_TOKEN_HARD_LIMIT="$new_prompt_cap"
          gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_HARD_CAP "$new_prompt_cap"
          gc_budget_reset_stage_tracking
          rm -f "$prompt_path" "$output_path" "$prompt_base_path"
          if (( attempt > 0 )); then
            (( attempt-- ))
          fi
          continue
        fi
        warn "    Prompt ~${prompt_estimate_tokens} tokens exceeds maximum automatic cap ${current_prompt_cap_int}; deferring task."
        skip_codex=1
        codex_ok=1
        manual_followups=1
        keep_output=0
        task_result_status="retryable"
        apply_status="prompt-blocked"
        skip_codex_reason="hard-cap"
        prompt_status="blocked-quota"
        prompt_hard_limit_value="$current_prompt_cap_int"
        prompt_token_estimate="$prompt_estimate_tokens"
        if [[ "$prompt_stop_on_overbudget" != "true" ]]; then
          prompt_stop_on_overbudget="true"
        fi
        task_prompt_estimate=$((prompt_estimate_tokens))
        task_notes+=("Prompt estimated at ~${prompt_estimate_tokens} tokens exceeds maximum automatic cap ${current_prompt_cap_int}; retry will run with trimmed context once budgets refresh.")
        break_after_update=1
        continue
      fi

      if [[ "${prompt_status,,}" != "blocked-quota" ]]; then
        if (( current_prompt_cap_int > 0 )) && [[ "$prompt_token_estimate" =~ ^[0-9]+$ ]] && (( prompt_token_estimate > current_prompt_cap_int )); then
          local max_prompt_cap="${GC_AUTOBUDGET_PROMPT_MAX:-1000000}"
          local new_prompt_cap=$((prompt_token_estimate + prompt_token_estimate / 10 + 2048))
          if (( new_prompt_cap > max_prompt_cap )); then
            new_prompt_cap="$max_prompt_cap"
          fi
          if (( new_prompt_cap > current_prompt_cap_int )); then
            warn "    Prompt estimate ${prompt_token_estimate}/${current_prompt_cap_int} exceeds hard cap; raising cap to ${new_prompt_cap} and retrying."
            GC_TASK_TOKEN_HARD_LIMIT="$new_prompt_cap"
            gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_HARD_CAP "$new_prompt_cap"
            gc_budget_reset_stage_tracking
            rm -f "$prompt_path" "$output_path" "$prompt_base_path"
            if (( attempt > 0 )); then
              (( attempt-- ))
            fi
            continue
          fi
          skip_codex=1
          codex_ok=1
          task_needs_review=1
          manual_followups=1
          keep_output=0
          task_result_status="retryable"
          apply_status="prompt-blocked"
          skip_codex_reason="hard-cap"
          local budget_note="${prompt_token_estimate}/${current_prompt_cap_int}"
          task_notes+=("Prompt estimate ${budget_note} exceeds maximum automatic hard token budget; defer and retry after context trim.")
          gc_log_blocked_quota "$prompt_meta_path" "${task_id:-}" "$slug" "$run_stamp" "$codex_model_for_step"
          break_after_update=1
          continue
        fi
      fi

      if [[ -n "$prompt_binder_status" ]]; then
        case "${prompt_binder_status,,}" in
          hit)
            info "    Binder hit — cached context reused."
            ;;
          stale)
            info "    Binder stale (${prompt_binder_reason:-reason unknown}); rebuilding context."
            ;;
          miss)
            info "    Binder cache miss (${prompt_binder_reason:-})"
            ;;
        esac
      fi

      if [[ "${prompt_status,,}" == "blocked-quota" ]]; then
        local max_prompt_cap="${GC_AUTOBUDGET_PROMPT_MAX:-1000000}"
        local new_prompt_cap=$((prompt_token_estimate + prompt_token_estimate / 10 + 2048))
        if (( new_prompt_cap > max_prompt_cap )); then
          new_prompt_cap="$max_prompt_cap"
        fi
        if (( skip_codex == 0 )) && (( new_prompt_cap > current_prompt_cap_int )); then
          warn "    Prompt exceeded token budgets (${prompt_token_estimate}/${current_prompt_cap_int}); raising cap to ${new_prompt_cap} and retrying."
          GC_TASK_TOKEN_HARD_LIMIT="$new_prompt_cap"
          gc_set_llm_output_limit_if_valid GC_LLM_OUTPUT_LIMIT_HARD_CAP "$new_prompt_cap"
          gc_budget_reset_stage_tracking
          rm -f "$prompt_path" "$output_path" "$prompt_base_path"
          if (( attempt > 0 )); then
            (( attempt-- ))
          fi
          continue
        fi
        skip_codex=1
        codex_ok=1
        task_needs_review=1
        manual_followups=1
        keep_output=0
        task_result_status="retryable"
        apply_status="prompt-blocked"
        local budget_note="${prompt_token_estimate}"
        if (( current_prompt_cap_int > 0 )); then
          budget_note="${prompt_token_estimate}/${current_prompt_cap_int}"
        elif [[ "$prompt_soft_limit_value" =~ ^[0-9]+$ ]] && (( prompt_soft_limit_value > 0 )); then
          budget_note="${prompt_token_estimate}/${prompt_soft_limit_value}"
        fi
        task_notes+=("Prompt exceeded token budgets after deterministic pruning; estimated ${budget_note} tokens. Will retry with trimmed context.")
        gc_log_blocked_quota "$prompt_meta_path" "${task_id:-}" "$slug" "$run_stamp" "$codex_model_for_step"
        break_after_update=1
        continue
      fi

      if command -v "$python_bin" >/dev/null 2>&1; then
        local _task_snapshot=""
        local helper_path
        if helper_path="$(gc_clone_python_tool "fetch_task_snapshot.py" "${PROJECT_ROOT:-$PWD}")"; then
          if _task_snapshot="$("$python_bin" "$helper_path" "$tasks_db" "$slug" "$task_index" 2>/dev/null)"; then
            if [[ -n "$_task_snapshot" ]]; then
              IFS=$'\t' read -r task_last_signature task_last_changes_count _ <<<"$_task_snapshot"
              previous_attempt_signature="$task_last_signature"
            fi
          fi
        fi
      fi
      [[ -n "$task_last_changes_count" ]] || task_last_changes_count="0"

      if (( skip_codex == 1 )); then
        attempt=$max_attempts
        gc_budget_log_stage "patch" 0 0 0 0 "$prompt_pruned_items" "{}" "true" "$skip_codex_reason"
      fi

      while (( attempt < max_attempts )); do
        (( ++attempt ))
        (( ++diff_guard_global_attempt ))
        if [[ -f "$prompt_base_path" ]]; then
          gc_refresh_work_prompt "$prompt_base_path" "$prompt_path" \
            "$contract_guard_injected" "$delta_prompt_injected" "$prompt_augmented" || true
        fi
        if ((${#task_notes[@]} > 0)); then
          local -a _task_notes_without_status=()
          local _task_note_line=""
          for _task_note_line in "${task_notes[@]}"; do
            if [[ "$_task_note_line" =~ ^STATUS[[:space:]:=] ]]; then
              continue
            fi
            _task_notes_without_status+=("$_task_note_line")
          done
          task_notes=("${_task_notes_without_status[@]}")
        fi
        local diff_guard_current_step="$diff_guard_global_attempt"
        gc_touch_progress
        GC_LAST_APPLY_META=""
        GC_LAST_APPLY_PAYLOAD=""
        codex_attempted=1
        task_change_operations=0
        local diff_before=""
        task_change_sizes=""

        local carry_over_label="${banner_task_id:-${task_id:-${slug:-story}-${task_number}}}"
        if ! gc_preserve_dirty_tree_for_attempt "$carry_over_label" "$attempt"; then
          warn "  Unable to snapshot pending edits before attempt ${attempt}; aborting task."
          task_needs_review=1
          manual_followups=1
          keep_output=1
          task_result_status="blocked-dirty-tree"
          gc_mark_outcome "PERMANENT_FAIL" "GIT"
          apply_status="dirty-tree-snapshot-failed"
          blocked_stop_run=1
          break
        fi

        if (( diff_guard_enabled )); then
          diff_before="$(gc_diff_fingerprint)"
        fi
        local patch_artifact_dir="${PROJECT_ROOT}/.gpt-creator/artifacts/patches"
        local patch_label="${banner_task_id:-${slug:-story}-${task_number}}"
        patch_label="${patch_label//[^A-Za-z0-9_.-]/_}"
        local patch_artifact_path="${patch_artifact_dir}/${patch_label}.patch"

        local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
        if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
          scripts_root="${CLI_ROOT}/scripts"
        fi
        local apply_helper="${scripts_root}/python/work_on_tasks_apply.py"
        if [[ ! -f "$apply_helper" ]]; then
          warn "Python apply helper missing; skipping Codex apply."
          task_needs_review=1
          manual_followups=1
          keep_output=1
          task_result_status="permanent-fail"
          gc_mark_outcome "PERMANENT_FAIL" "TOOLING"
          apply_status="codex-failed"
          task_notes+=("Codex apply helper missing; manual review required.")
          break
        fi

        local apply_json
        if ! apply_json="$("${PYTHON_BIN:-python3}" "$apply_helper" --prompt "$prompt_path" --output "$output_path" --call-name "$call_name" --step "$task_codex_step" --project-root "$PROJECT_ROOT" --patch-artifact "$patch_artifact_path" ${diff_guard_enabled:+--diff-guard})"; then
          warn "Codex apply helper failed; manual review required."
          task_needs_review=1
          manual_followups=1
          keep_output=1
          task_result_status="permanent-fail"
          gc_mark_outcome "PERMANENT_FAIL" "TOOLING"
          apply_status="codex-failed"
          task_notes+=("Codex apply helper failed; manual review required.")
          break
        fi

        local apply_status_val status_val prompt_tokens_val completion_tokens_val total_tokens_val
        local apply_notes_parsed=()
        while IFS= read -r line; do
          case "$line" in
            APPLY_STATUS:*) apply_status_val="${line#APPLY_STATUS:}";;
            STATUS:*) status_val="${line#STATUS:}";;
            TOKENS_PROMPT:*) prompt_tokens_val="${line#TOKENS_PROMPT:}";;
            TOKENS_COMPLETION:*) completion_tokens_val="${line#TOKENS_COMPLETION:}";;
            TOKENS_TOTAL:*) total_tokens_val="${line#TOKENS_TOTAL:}";;
            NOTE:*) apply_notes_parsed+=("${line#NOTE:}");;
          esac
        done <<<"$apply_json"
        apply_status="$apply_status_val"
        if [[ "$total_tokens_val" =~ ^[0-9]+$ ]]; then
          task_tokens_total=$((task_tokens_total + total_tokens_val))
        fi
        if [[ "$prompt_tokens_val" =~ ^[0-9]+$ ]]; then
          task_llm_prompt_tokens=$((task_llm_prompt_tokens + prompt_tokens_val))
        fi
        if [[ "$completion_tokens_val" =~ ^[0-9]+$ ]]; then
          task_llm_completion_tokens=$((task_llm_completion_tokens + completion_tokens_val))
        fi
        if (( ${#apply_notes_parsed[@]} )); then
          task_notes+=("${apply_notes_parsed[@]}")
        fi
        case "$status_val" in
          ok)
            codex_ok=1
            apply_status="applied"
            ;;
          empty-output)
            codex_ok=1
            apply_status="no-output"
            task_needs_review=1
            manual_followups=1
            keep_output=1
            task_result_status="apply-failed-migration-context"
            gc_mark_outcome "DEAD_LETTER" "TOOLING"
            ;;
          empty-apply|no-diff)
            codex_ok=1
            task_needs_review=1
            manual_followups=1
            keep_output=1
            task_result_status="apply-failed-migration-context"
            gc_mark_outcome "DEAD_LETTER" "CONTRACT"
            ;;
          apply-failed|codex-failed|contract-violation)
            task_needs_review=1
            manual_followups=1
            keep_output=1
            task_result_status="permanent-fail"
            gc_mark_outcome "PERMANENT_FAIL" "TOOLING"
            codex_ok=0
            break
            ;;
          *)
            task_needs_review=1
            manual_followups=1
            keep_output=1
            task_result_status="permanent-fail"
            gc_mark_outcome "PERMANENT_FAIL" "TOOLING"
            codex_ok=0
            break
            ;;
        esac
        break
      done

      if (( task_needs_review )) && (( auto_review_enabled )) && (( task_changes_applied > 0 )); then
        local auto_review_path=""
        if auto_review_path="$(gc_generate_auto_review "$story_run_dir" "$story_log_dir" "$banner_task_id" "$task_id" "$task_result_status" "$task_number" "$task_tokens_total" "$PROJECT_ROOT")"; then
          task_needs_review=0
          manual_followups=0
          if [[ "$task_result_status" == "retryable" || "$task_result_status" == "apply-failed-migration-context" ]]; then
            task_result_status="complete"
          fi
          local auto_review_rel="$auto_review_path"
          if [[ -n "$PROJECT_ROOT" && "$auto_review_rel" == "$PROJECT_ROOT/"* ]]; then
            auto_review_rel="${auto_review_rel#$PROJECT_ROOT/}"
          fi
          task_notes+=("Auto-generated review artifact: ${auto_review_rel}")
          info "    Auto review generated at ${auto_review_rel}"
        else
          warn "    GC_AUTO_REVIEW enabled but review artifact generation failed."
        fi
      fi

      if (( task_needs_review )) && (( task_changes_applied == 0 )) && [[ "${GC_COMPLETE_ON_EMPTY:-0}" == "1" ]]; then
        local _gc_note_text=""
        local _gc_note_lower=""
        local _gc_complete_on_empty=0
        for _gc_note_text in "${task_notes[@]}"; do
          _gc_note_lower="${_gc_note_text,,}"
          if [[ "$_gc_note_lower" == *"already satisfies"* ]] || [[ "$_gc_note_lower" == *"no repository edits required"* ]] || [[ "$_gc_note_lower" == *"no changes needed"* ]] || [[ "$_gc_note_lower" == *"acceptance criteria met"* ]]; then
            _gc_complete_on_empty=1
            break
          fi
        done
        if (( _gc_complete_on_empty )); then
          task_needs_review=0
          manual_followups=0
          keep_output=0
          task_result_status="completed-no-changes"
          if [[ -z "$apply_status" || "$apply_status" == "pending" || "$apply_status" == "no-changes" ]]; then
            apply_status="completed-no-changes"
          fi
          task_notes+=("Marked completed-no-changes via GC_COMPLETE_ON_EMPTY; existing artifacts satisfy the task.")
        fi
      fi

      if (( task_needs_review )); then
        manual_followups=1
        if [[ "$task_result_status" != "blocked" && "$task_result_status" != "permanent-fail" && "$task_result_status" != "dead-letter" ]]; then
          if (( ${GC_WOT_COMPLETE_ON_FOLLOWUP:-0} )); then
            case "$task_result_status" in
              complete|completed-no-changes)
                task_notes+=("Follow-up required; status remains complete due to --complete-on-followup.")
                ;;
              apply-failed-migration-context|retryable|in-progress)
                task_result_status="retryable"
                ;;
              *)
                task_result_status="retryable"
                ;;
            esac
          else
            task_result_status="retryable"
          fi
        fi
      fi

      if (( task_needs_review )) && [[ "$task_terminal_state" == "RUNNING" ]]; then
        gc_mark_outcome "RETRYABLE" "TRANSIENT"
      fi

      if (( codex_ok == 0 )); then
        task_result_status="permanent-fail"
        if [[ "$task_terminal_state" == "RUNNING" ]]; then
          gc_mark_outcome "PERMANENT_FAIL" "TOOLING"
        fi
        task_notes+=("Codex execution did not complete; no changes were applied.")
      fi

      if (( codex_attempted )) && (( codex_ok )) && (( context_lines_current > context_lines_min || context_file_lines_current > context_file_lines_min )); then
        local last_tokens="${GC_LAST_CODEX_TOTAL_TOKENS:-0}"
        local shrink_threshold="$context_auto_shrink_threshold"
        if [[ "$prompt_soft_limit_value" =~ ^[0-9]+$ ]] && (( prompt_soft_limit_value > 0 )); then
          shrink_threshold="$prompt_soft_limit_value"
        fi
        local trigger_shrink=0
        if [[ "$last_tokens" =~ ^[0-9]+$ ]] && (( last_tokens > shrink_threshold )); then
          trigger_shrink=1
        fi
        if (( trigger_shrink )); then
          if (( context_shrink_iterations > 0 )) && (( last_tokens <= context_last_shrink_tokens )); then
            trigger_shrink=0
          fi
        fi
        if (( trigger_shrink )); then
          local new_context_lines="$context_lines_current"
          local new_context_file_lines="$context_file_lines_current"
          local reduced=0
          if (( context_lines_current > context_lines_min )); then
            local decrement_lines=$(( context_lines_current / 3 ))
            (( decrement_lines < 40 )) && decrement_lines=40
            new_context_lines=$(( context_lines_current - decrement_lines ))
            if (( new_context_lines < context_lines_min )); then
              new_context_lines="$context_lines_min"
            fi
            if (( new_context_lines < context_lines_current )); then
              reduced=1
            fi
          fi
          if (( context_file_lines_current > context_file_lines_min )); then
            local decrement_files=$(( context_file_lines_current / 2 ))
            (( decrement_files < 20 )) && decrement_files=20
            new_context_file_lines=$(( context_file_lines_current - decrement_files ))
            if (( new_context_file_lines < context_file_lines_min )); then
              new_context_file_lines="$context_file_lines_min"
            fi
            if (( new_context_file_lines < context_file_lines_current )); then
              reduced=1
            fi
          fi
          if (( reduced )); then
            info "    Token usage ${last_tokens} exceeded budget (~${shrink_threshold}); pruning shared context to ${new_context_lines} lines (per-file ${new_context_file_lines})."
            context_lines_current="$new_context_lines"
            context_file_lines_current="$new_context_file_lines"
            context_last_shrink_tokens="$last_tokens"
            context_shrink_iterations=$((context_shrink_iterations + 1))
            GC_CONTEXT_FILE_LINES="$context_file_lines_current"
            export GC_CONTEXT_FILE_LINES
            GC_CONTEXT_TAIL_LIMIT="$context_lines_current"
            export GC_CONTEXT_TAIL_LIMIT
            if ! gc_build_context_file "$ctx_file" "$STAGING_DIR"; then
              warn "Failed to rebuild shared context after pruning."
            else
              if [[ -n "$context_tail" && -f "$ctx_file" ]]; then
                local new_mode
                new_mode="$(gc_refresh_context_tail "$ctx_file" "$context_tail" "$context_tail_mode" "$context_lines_current")"
                if [[ "$new_mode" == "raw" && "$context_tail_mode" != "raw" ]]; then
                  context_tail="${run_dir}/context_tail.md"
                  new_mode="$(gc_refresh_context_tail "$ctx_file" "$context_tail" "raw" "$context_lines_current")"
                fi
                context_tail_mode="$new_mode"
                GC_CONTEXT_TAIL_MODE="$context_tail_mode"
                export GC_CONTEXT_TAIL_MODE
              fi
            fi
          else
            context_last_shrink_tokens="$last_tokens"
          fi
        fi
      fi

      # Register documentation changes in the registry and guard against rejects.
      if (( ${#task_written_paths[@]} > 0 || ${#task_patched_paths[@]} > 0 )); then
        local -A gc_doc_changed=()
        local gc_doc_path=""
        for gc_doc_path in "${task_written_paths[@]}" "${task_patched_paths[@]}"; do
          [[ -z "$gc_doc_path" ]] && continue
          gc_doc_path="${gc_doc_path%% (*}"
          if [[ "$gc_doc_path" == docs/* ]]; then
            gc_doc_changed["$gc_doc_path"]=1
          fi
        done
        if (( ${#gc_doc_changed[@]} > 0 )); then
          local doc_registry_python="${PYTHON_BIN:-python3}"
          local doc_registry_tool="${CLI_ROOT}/src/lib/doc_registry.py"
          if command -v "$doc_registry_python" >/dev/null 2>&1 && [[ -f "$doc_registry_tool" ]]; then
            local gc_doc_register_ok=1
            local -a gc_doc_sorted=()
            while IFS= read -r gc_doc_line; do
              gc_doc_sorted+=("$gc_doc_line")
            done < <(printf '%s\n' "${!gc_doc_changed[@]}" | LC_ALL=C sort)
            local gc_doc_helper=""
            gc_doc_helper="$(gc_clone_python_tool "doc_registry_compute_id.py" "${PROJECT_ROOT:-$PWD}")" || gc_doc_helper=""
            if [[ -z "$gc_doc_helper" ]]; then
              gc_doc_register_ok=0
              task_notes+=("Doc registry helper unavailable; register manually for: ${gc_doc_sorted[*]}")
            else
              local gc_doc_reg_path=""
              for gc_doc_reg_path in "${gc_doc_sorted[@]}"; do
                local gc_doc_abs="${PROJECT_ROOT}/${gc_doc_reg_path}"
                if [[ ! -f "$gc_doc_abs" ]]; then
                  task_notes+=("Doc registry skipped ${gc_doc_reg_path} (file missing after apply).")
                  continue
                fi
                local gc_doc_id=""
                if ! gc_doc_id="$("$doc_registry_python" "$gc_doc_helper" "$gc_doc_abs")"; then
                  gc_doc_register_ok=0
                  task_notes+=("Failed to compute documentation id for ${gc_doc_reg_path}; register manually.")
                  continue
                fi
                if ! "$doc_registry_python" "$doc_registry_tool" register "$gc_doc_id" "$gc_doc_abs" "updated trace link(s)"; then
                  gc_doc_register_ok=0
                  task_notes+=("Doc registry update failed for ${gc_doc_reg_path}; rerun `python3 src/lib/doc_registry.py register ${gc_doc_id} ${gc_doc_reg_path}`.")
                fi
              done
            fi
            if (( gc_doc_register_ok == 0 )); then
              task_needs_review=1
              manual_followups=1
            fi
          else
            local -a gc_doc_missing=()
            while IFS= read -r gc_doc_line; do
              gc_doc_missing+=("$gc_doc_line")
            done < <(printf '%s\n' "${!gc_doc_changed[@]}" | LC_ALL=C sort)
            task_notes+=("Doc registry tooling unavailable; queue manual register for: ${gc_doc_missing[*]}")
          fi
        fi
      fi

      local -a gc_doc_rejects=()
      if [[ -d "${PROJECT_ROOT}/docs" ]]; then
        while IFS= read -r -d '' gc_reject; do
          gc_reject="${gc_reject#"${PROJECT_ROOT}/"}"
          gc_doc_rejects+=("$gc_reject")
        done < <(find "${PROJECT_ROOT}/docs" -type f -name '*.rej' -print0 2>/dev/null)
      fi
      if (( ${#gc_doc_rejects[@]} > 0 )); then
        task_result_status="blocked-merge-conflict"
        apply_status="blocked-merge-conflict"
        task_needs_review=1
        manual_followups=1
        keep_output=1
        task_notes+=("Documentation patch rejects present: ${gc_doc_rejects[*]}. Resolve before rerunning work-on-tasks.")
      fi

      if [[ "$task_result_status" == "in-progress" ]]; then
        task_result_status="ready-to-review"
      fi

      local note_status_override=""
      if ((${#task_notes[@]} > 0)); then
        local _note_text=""
        for _note_text in "${task_notes[@]}"; do
          if [[ "$_note_text" =~ STATUS:[[:space:]]*([A-Za-z-]+) ]]; then
            note_status_override="${BASH_REMATCH[1],,}"
          fi
        done
      fi
      if [[ -n "$note_status_override" ]]; then
        case "$note_status_override" in
          completed-no-changes|completed_no_changes)
            if [[ "$task_result_status" == "complete" || "$task_result_status" == "ready-to-review" || "$task_result_status" == "in-progress" || "$task_result_status" == "retryable" ]]; then
              task_result_status="ready-to-review-no-changes"
            fi
            ;;
          completed|complete|ready-to-review|ready_to_review)
            if [[ "$task_result_status" == "completed-no-changes" || "$task_result_status" == "ready-to-review-no-changes" || "$task_result_status" == "in-progress" || "$task_result_status" == "retryable" ]]; then
              task_result_status="ready-to-review"
            fi
            ;;
          needs-retry|needs_retry|retry|retryable)
            task_result_status="retryable"
            ;;
          failed|fail)
            if [[ "$task_result_status" != "dead-letter" && "$task_result_status" != "permanent-fail" ]]; then
              task_result_status="permanent-fail"
              task_outcome_reason="${task_outcome_reason:-note-status-failed}"
            fi
            ;;
          skipped-already-complete|skipped_already_complete)
            task_result_status="skipped-already-complete"
            ;;
        esac
      fi

      case "$task_result_status" in
        complete|completed)
          task_result_status="ready-to-review"
          ;;
        completed-no-changes)
          task_result_status="ready-to-review-no-changes"
          ;;
      esac

      if [[ "$task_terminal_state" == "RUNNING" ]]; then
        case "$task_result_status" in
          complete|ready-to-review)
            if (( task_changes_applied > 0 )); then
              gc_mark_terminal_state "COMPLETED_WITH_CHANGES"
            else
              gc_mark_terminal_state "NOOP_ACCEPTED"
            fi
            ;;
          completed-no-changes|ready-to-review-no-changes)
            gc_mark_terminal_state "NOOP_ACCEPTED"
            ;;
          permanent-fail)
            gc_mark_terminal_state "PERMANENT_FAIL"
            ;;
          dead-letter)
            gc_mark_terminal_state "DEAD_LETTER"
            ;;
          retryable)
            gc_mark_terminal_state "RETRYABLE"
            ;;
          blocked-quota|abandoned-for-budget|blocked-push)
            gc_mark_outcome "DEAD_LETTER" "QUOTA"
            ;;
          blocked)
            gc_mark_terminal_state "PERMANENT_FAIL"
            ;;
        esac
      fi

      local task_end_epoch
      task_end_epoch="$(date +%s)"
      task_duration_seconds=$((task_end_epoch - task_start_epoch))
      if (( task_duration_seconds < 0 )); then
        task_duration_seconds=0
      fi
      task_duration_display="$(gc_format_duration_compact "$task_duration_seconds")"
      task_tokens_display="$(gc_format_tokens_compact "$task_tokens_total")"
      local task_prompt_estimate_display
      task_prompt_estimate_display="$(gc_format_tokens_compact "$task_prompt_estimate")"
      local task_estimated_tokens_value="$task_prompt_estimate"
      local task_estimated_tokens_display="$task_prompt_estimate_display"
      if [[ -n "$wot_avg_tokens_per_sp" && "$wot_avg_tokens_per_sp" != "0" && -n "$task_story_points" ]]; then
        local sp_clean="${task_story_points//[[:space:]]/}"
        if [[ "$sp_clean" =~ ^[0-9]+([.][0-9]+)?$ ]] && [[ "$wot_avg_tokens_per_sp" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
          local expected_tokens_calc
          expected_tokens_calc="$(awk -v avg="$wot_avg_tokens_per_sp" -v sp="$sp_clean" 'BEGIN{if (avg+0<=0 || sp+0<=0){print ""} else {printf "%.0f", avg*sp}}' 2>/dev/null)"
          if [[ "$expected_tokens_calc" =~ ^[0-9]+$ ]]; then
            task_estimated_tokens_value="$expected_tokens_calc"
            task_estimated_tokens_display="$(gc_format_tokens_compact "$task_estimated_tokens_value")"
          fi
        fi
      fi

      task_notes+=("Terminal state: ${task_terminal_state}")
      if [[ "$task_failure_class" != "NONE" ]]; then
        task_notes+=("Failure class: ${task_failure_class}")
      fi

      local status_token=""
      case "$task_result_status" in
        complete|completed|ready-to-review)
          status_token="COMPLETED"
          ;;
        completed-no-changes|ready-to-review-no-changes)
          status_token="COMPLETED NO CHANGES"
          ;;
        retryable)
          status_token="RETRYABLE"
          ;;
        skipped-already-complete)
          status_token="SKIPPED ALREADY COMPLETE"
          ;;
        blocked|blocked-*|abandoned-for-budget)
          status_token="BLOCKED"
          ;;
        dead-letter|permanent-fail|apply-failed-*|dirty-tree-snapshot-failed)
          status_token="FAILED"
          ;;
        *)
          status_token="${task_result_status//[_-]/ }"
          status_token="${status_token^^}"
          ;;
      esac
      if [[ -n "$status_token" ]]; then
        local -a task_notes_without_status=()
        local task_note_entry=""
        for task_note_entry in "${task_notes[@]}"; do
          if [[ "$task_note_entry" =~ ^STATUS[[:space:]:=] ]]; then
            continue
          fi
          task_notes_without_status+=("$task_note_entry")
        done
        task_notes_without_status+=("STATUS: ${status_token}")
        task_notes=("${task_notes_without_status[@]}")
      fi

      local attempt_label=$(( attempt > 0 ? attempt : 1 ))

      if [[ "$task_result_status" == "complete" || "$task_result_status" == "completed-no-changes" || "$task_result_status" == "ready-to-review" || "$task_result_status" == "ready-to-review-no-changes" ]]; then
        local commit_label="${banner_task_id}: ${task_title:-Task ${task_number}}"
        if gc_finalize_task_snapshot "$commit_label" "$task_ref_for_verify" "$attempt_label" "$task_result_status" "complete" "${task_auto_push_records[@]}"; then
          if [[ "${GC_LAST_AUTO_COMMIT_STATUS:-}" == "committed" ]]; then
            local commit_hash="${GC_LAST_AUTO_COMMIT_HASH:0:7}"
            local push_desc=""
            if [[ "${GC_LAST_AUTO_PUSH_STATUS:-}" == "pushed" ]]; then
              push_desc="pushed to ${GC_LAST_AUTO_PUSH_REMOTE:-origin}/${GC_LAST_AUTO_PUSH_BRANCH:-HEAD}"
            elif [[ "${GC_LAST_AUTO_PUSH_STATUS:-}" == "failed" ]]; then
              push_desc="push failed"
            elif [[ "${GC_LAST_AUTO_PUSH_STATUS:-}" == "skipped" ]]; then
              push_desc="push skipped"
            else
              push_desc="commit recorded"
            fi
            task_notes+=("Auto-finalized commit ${commit_hash} (${push_desc}).")
          fi
          local finalize_script="${PROJECT_ROOT}/scripts/auto_finalize_task.sh"
          if [[ -x "$finalize_script" ]]; then
            if ! bash "$finalize_script"; then
              warn "  Auto finalize failed; inspect git status."
            fi
          fi
        else
          task_result_status="blocked-push"
          manual_followups=1
          keep_output=1
          blocked_stop_run=1
          task_notes+=("Auto-push failed after ${GC_RETRY_PUSH_MAX:-3} attempt(s); review git state.")
        fi
      else
        local snapshot_label="${banner_task_id:-${task_id:-${slug:-story}-${task_number}}}"
        if gc_finalize_task_snapshot "$snapshot_label" "$task_ref_for_verify" "$attempt_label" "$task_result_status" "snapshot" "${task_auto_push_records[@]}"; then
          if [[ "${GC_LAST_AUTO_COMMIT_STATUS:-}" == "committed" ]]; then
            local commit_hash="${GC_LAST_AUTO_COMMIT_HASH:0:7}"
            local push_desc=""
            if [[ "${GC_LAST_AUTO_PUSH_STATUS:-}" == "pushed" ]]; then
              push_desc="pushed to ${GC_LAST_AUTO_PUSH_REMOTE:-origin}/${GC_LAST_AUTO_PUSH_BRANCH:-HEAD}"
            elif [[ "${GC_LAST_AUTO_PUSH_STATUS:-}" == "failed" ]]; then
              push_desc="push failed"
            elif [[ "${GC_LAST_AUTO_PUSH_STATUS:-}" == "skipped" ]]; then
              push_desc="push skipped"
            else
              push_desc="commit recorded"
            fi
            task_notes+=("Snapshot commit ${commit_hash} captured for attempt ${attempt_label} (${push_desc}).")
          fi
        else
          task_result_status="blocked-push"
          manual_followups=1
          keep_output=1
          blocked_stop_run=1
          task_notes+=("Snapshot auto-push failed after ${GC_RETRY_PUSH_MAX:-3} attempt(s); resolve manually.")
        fi
      fi

      if [[ "$task_result_status" == "completed-no-changes" && "${GC_LAST_AUTO_COMMIT_STATUS:-}" == "committed" ]]; then
        info "    Auto-finalize produced a commit; promoting status to complete."
        task_result_status="complete"
        task_changes_applied=1
        if (( task_last_change_operations == 0 )); then
          task_last_change_operations=1
        fi
        local -a _task_notes_refreshed=()
        local note_entry=""
        for note_entry in "${task_notes[@]}"; do
          if [[ "$note_entry" =~ ^STATUS[[:space:]:=] ]]; then
            continue
          fi
          if [[ "$note_entry" == *"no actionable changes"* ]]; then
            continue
          fi
          if [[ "$note_entry" == *"empty-apply checkpoint"* ]]; then
            continue
          fi
          _task_notes_refreshed+=("$note_entry")
        done
        _task_notes_refreshed+=("STATUS: COMPLETED")
        task_notes=("${_task_notes_refreshed[@]}")
      fi

      local story_status_hint="in-progress"
      case "$task_result_status" in
        blocked|blocked-budget|blocked-schema-drift|blocked-schema-guard-error|blocked-dependency\(*\)|retryable|blocked-push|dead-letter|permanent-fail) story_status_hint="blocked" ;;
        on-hold) story_status_hint="on-hold" ;;
      esac

      local completed_hint="$task_index"
      if [[ "$task_result_status" == "complete" || "$task_result_status" == "completed-no-changes" || "$task_result_status" == "ready-to-review" || "$task_result_status" == "ready-to-review-no-changes" ]]; then
        completed_hint=$((task_index + 1))
      fi

      gc_update_task_state "$tasks_db" "$slug" "$task_index" "$task_result_status" "$run_stamp"
      gc_update_work_state "$tasks_db" "$slug" "$story_status_hint" "$completed_hint" "$total_tasks_int" "$run_stamp"

      if (( blocked_stop_run )); then
        task_notes+=("Auto-push issues recorded; continuing to the next task.")
        blocked_stop_run=0
      fi

      local timestamp_utc
      timestamp_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

      local prompt_entry="$prompt_path"
      local output_entry="$output_path"
      local report_entry_path="$task_log_archive_path"
      local report_entry_display="$report_entry_path"
      local report_entry_db=""
      local project_prefix="${PROJECT_ROOT}/"
      if [[ -n "$PROJECT_ROOT" ]]; then
        if [[ "$prompt_entry" == "$project_prefix"* ]]; then
          prompt_entry="${prompt_entry#$project_prefix}"
        fi
        if [[ "$output_entry" == "$project_prefix"* ]]; then
          output_entry="${output_entry#$project_prefix}"
        fi
        if [[ "$report_entry_display" == "$project_prefix"* ]]; then
          report_entry_display="${report_entry_display#$project_prefix}"
        fi
      fi
      report_entry_db="$report_entry_display"
      if [[ ! -f "$prompt_path" ]]; then
        if (( keep_artifacts == 0 )); then
          prompt_entry="(discarded)"
        else
          prompt_entry="(missing)"
        fi
      fi
      if [[ ! -f "$output_path" ]]; then
        if (( keep_output == 0 )); then
          output_entry="(discarded)"
        else
          output_entry="(missing)"
        fi
      fi
      local history_summary_path=""
      local history_meta_path=""
      local history_summary_entry=""
      local history_meta_entry=""
      if [[ -n "$story_run_dir" ]]; then
        local history_root="${story_run_dir}/history"
        local history_dir_name
        history_dir_name="$(gc_history_dir_name_for_task "$task_number" "$slug" "$task_id")"
        local history_dir="${history_root}/${history_dir_name}"
        if [[ -f "${history_dir}/latest.summary.md" ]]; then
          history_summary_path="${history_dir}/latest.summary.md"
          history_summary_entry="$history_summary_path"
        fi
        if [[ -f "${history_dir}/latest.summary.txt" ]]; then
          history_meta_path="${history_dir}/latest.summary.txt"
          history_meta_entry="$history_meta_path"
        fi
      fi
      if [[ -n "$history_summary_entry" && -n "$PROJECT_ROOT" && "$history_summary_entry" == "$project_prefix"* ]]; then
        history_summary_entry="${history_summary_entry#$project_prefix}"
      fi
      if [[ -n "$history_meta_entry" && -n "$PROJECT_ROOT" && "$history_meta_entry" == "$project_prefix"* ]]; then
        history_meta_entry="${history_meta_entry#$project_prefix}"
      fi
      if [[ -n "$history_summary_entry" && ! -f "$history_summary_path" ]]; then
        history_summary_entry=""
      fi
      if [[ -n "$history_meta_entry" && ! -f "$history_meta_path" ]]; then
        history_meta_entry=""
      fi

      local task_changes_count="$task_last_change_operations"
      if [[ -z "$task_outcome_reason" ]]; then
        case "$task_result_status" in
          completed-no-changes)
            task_outcome_reason="noop"
            ;;
          complete)
            task_outcome_reason="changes-applied"
            ;;
        esac
      fi
      local changes_flag="false"
      if (( task_changes_applied > 0 )); then
        changes_flag="true"
      fi

      local notes_payload=""
      if ((${#task_notes[@]} > 0)); then
        notes_payload="$(printf '%s\n' "${task_notes[@]}")"
      fi
      local task_notes_display="${task_outcome_reason:-}"
      if [[ -z "$task_notes_display" ]] && ((${#task_notes[@]} > 0)); then
        local -a task_notes_sanitized=()
        for note in "${task_notes[@]}"; do
          local sanitized="${note//$'\r'/ }"
          sanitized="${sanitized//$'\n'/ }"
          sanitized="${sanitized//$'\t'/ }"
          while [[ "$sanitized" == *"  "* ]]; do
            sanitized="${sanitized//  / }"
          done
          sanitized="${sanitized#"${sanitized%%[![:space:]]*}"}"
          sanitized="${sanitized%"${sanitized##*[![:space:]]}"}"
          [[ -n "$sanitized" ]] || continue
          task_notes_sanitized+=("$sanitized")
        done
        if ((${#task_notes_sanitized[@]} > 0)); then
          local IFS='; '
          task_notes_display="${task_notes_sanitized[*]}"
        fi
      fi
      local written_payload=""
      if ((${#task_written_paths[@]} > 0)); then
        written_payload="$(printf '%s\n' "${task_written_paths[@]}")"
      fi
      local patched_payload=""
      if ((${#task_patched_paths[@]} > 0)); then
        patched_payload="$(printf '%s\n' "${task_patched_paths[@]}")"
      fi
      local commands_payload=""
      if ((${#task_commands[@]} > 0)); then
        commands_payload="$(printf '%s\n' "${task_commands[@]}")"
      fi

      {
        printf 'task_number: %s\n' "$task_number"
        printf 'task_id: %s\n' "${task_id:-}"
        printf 'task_title: %s\n' "${task_title//$'\n'/ }"
        printf 'story_slug: %s\n' "$slug"
        printf 'status: %s\n' "$task_result_status"
        printf 'timestamp: %s\n' "$timestamp_utc"
        printf 'attempts: %s\n' "$attempt"
        printf 'apply_status: %s\n' "$apply_status"
        printf 'changes_applied: %s\n' "$changes_flag"
        printf 'tokens_used: %s\n' "$task_tokens_total"
        printf 'llm_prompt_tokens: %s\n' "$task_llm_prompt_tokens"
        printf 'llm_completion_tokens: %s\n' "$task_llm_completion_tokens"
        printf 'prompt_tokens_estimate: %s\n' "$task_prompt_estimate"
        printf 'prompt_path: %s\n' "$prompt_entry"
        printf 'output_path: %s\n' "$output_entry"
        printf 'changes_count: %s\n' "$task_changes_count"
        printf 'attempt_signature: %s\n' "${task_attempt_signature:-}"
        if [[ -n "$task_outcome_reason" ]]; then
          printf 'outcome_reason: %s\n' "$task_outcome_reason"
        fi
        if ((${#task_written_paths[@]} > 0)); then
          printf 'written:\n'
          for path in "${task_written_paths[@]}"; do
            printf '  - %s\n' "$path"
          done
        fi
        if ((${#task_patched_paths[@]} > 0)); then
          printf 'patched:\n'
          for path in "${task_patched_paths[@]}"; do
            printf '  - %s\n' "$path"
          done
        fi
        if ((${#task_commands[@]} > 0)); then
          printf 'commands:\n'
          for cmd in "${task_commands[@]}"; do
            printf '  - %s\n' "$cmd"
          done
        fi
        printf 'notes:\n'
        if ((${#task_notes[@]} > 0)); then
          for note in "${task_notes[@]}"; do
            printf '  - %s\n' "${note//$'\n'/ }"
          done
        else
          printf '  - (none)\n'
        fi
      } >"$task_report_path"
      if ! cp -f "$task_report_path" "$task_log_archive_path"; then
        warn "  Failed to archive task log to ${task_log_archive_path}."
      fi
      if [[ ! -f "$task_log_archive_path" ]]; then
        report_entry_db=""
        report_entry_display="(missing)"
      fi

      local observation_hash=""
      if (( task_tokens_total > 0 )); then
        local observation_seed="${task_id:-}:${stdout_hash:-}:${apply_status:-}:${task_result_status:-}:${task_tokens_total:-0}"
        if observation_hash="$(gc_make_observation_hash "$observation_seed" 2>/dev/null)"; then
          :
        else
          observation_hash=""
        fi
      fi
      local stage_retrieve_after_int stage_plan_after_int stage_patch_after_int stage_verify_after_int
      stage_retrieve_after_int="$(gc_parse_int "${GC_BUDGET_STAGE_TOTAL_RETRIEVE:-0}" 0)"
      stage_plan_after_int="$(gc_parse_int "${GC_BUDGET_STAGE_TOTAL_PLAN:-0}" 0)"
      stage_patch_after_int="$(gc_parse_int "${GC_BUDGET_STAGE_TOTAL_PATCH:-0}" 0)"
      stage_verify_after_int="$(gc_parse_int "${GC_BUDGET_STAGE_TOTAL_VERIFY:-0}" 0)"
      local stage_retrieve_start_int stage_plan_start_int stage_patch_start_int stage_verify_start_int
      stage_retrieve_start_int="$(gc_parse_int "$stage_baseline_retrieve" 0)"
      stage_plan_start_int="$(gc_parse_int "$stage_baseline_plan" 0)"
      stage_patch_start_int="$(gc_parse_int "$stage_baseline_patch" 0)"
      stage_verify_start_int="$(gc_parse_int "$stage_baseline_verify" 0)"
      local task_stage_tokens_retrieve=$((stage_retrieve_after_int - stage_retrieve_start_int))
      local task_stage_tokens_plan=$((stage_plan_after_int - stage_plan_start_int))
      local task_stage_tokens_patch=$((stage_patch_after_int - stage_patch_start_int))
      local task_stage_tokens_verify=$((stage_verify_after_int - stage_verify_start_int))
      (( task_stage_tokens_retrieve < 0 )) && task_stage_tokens_retrieve=0
      (( task_stage_tokens_plan < 0 )) && task_stage_tokens_plan=0
      (( task_stage_tokens_patch < 0 )) && task_stage_tokens_patch=0
      (( task_stage_tokens_verify < 0 )) && task_stage_tokens_verify=0

      gc_record_task_progress "$tasks_db" "$slug" "$task_index" "$run_stamp" "$task_result_status" "$report_entry_db" "$prompt_entry" "$output_entry" "$attempt" "$task_tokens_total" "$task_prompt_estimate" "$task_llm_prompt_tokens" "$task_llm_completion_tokens" "$task_duration_seconds" "$apply_status" "$changes_flag" "$notes_payload" "$written_payload" "$patched_payload" "$commands_payload" "$observation_hash" "$timestamp_utc" "$task_stage_tokens_retrieve" "$task_stage_tokens_plan" "$task_stage_tokens_patch" "$task_stage_tokens_verify" "$task_story_points" "$task_verify_status" "$task_verify_summary" "$task_verify_report" "$task_verify_details" "$task_meta_plan_flag" "$task_meta_focus_flag" "$task_meta_no_changes_flag" "$task_meta_already_flag" "${GC_LAST_AUTO_COMMIT_HASH:-}" "${GC_LAST_AUTO_COMMIT_STATUS:-}" "${GC_LAST_AUTO_PUSH_STATUS:-}" "${GC_LAST_AUTO_PUSH_REMOTE:-}" "${GC_LAST_AUTO_PUSH_BRANCH:-}" "${GC_LAST_AUTO_PUSH_ERROR:-}" "$task_attempt_signature" "$task_changes_count" "$task_outcome_reason" "$history_summary_entry" "$history_meta_entry"

      gc_log_task_metrics "$run_stamp" "$slug" "$task_number" "$banner_task_id" "$task_result_status" "$task_story_points" "$task_stage_tokens_retrieve" "$task_stage_tokens_plan" "$task_stage_tokens_patch" "$task_stage_tokens_verify" "$task_prompt_estimate" "$task_llm_prompt_tokens" "$task_llm_completion_tokens"
      if [[ -n "${AGENT_TELEMETRY_PAYLOAD:-}" ]]; then
        gc_telemetry_record "agent_usage" "${AGENT_TELEMETRY_PAYLOAD}" || true
      fi

      if [[ "$task_result_status" == "complete" || "$task_result_status" == "completed-no-changes" || "$task_result_status" == "ready-to-review" || "$task_result_status" == "ready-to-review-no-changes" ]]; then
        local throughput_task_msg=""
        if throughput_task_msg="$(gc_update_throughput_metrics "$tasks_db" "task-complete" "$slug" "$task_index")"; then
          if [[ -n "$throughput_task_msg" ]]; then
            info "  ${throughput_task_msg}"
            now_ts="$(date +%s)"
            throughput_next_checkpoint=$((now_ts + throughput_checkpoint_interval))
          fi
        else
          warn "  Failed to record throughput metrics for task ${task_number}."
        fi
      fi

      gc_clear_active_task

      case "$task_result_status" in
        complete|completed-no-changes|ready-to-review|ready-to-review-no-changes)
          info "  ✓ Task ${task_number} (${task_id:-no-id}) ready for review with status: ${task_result_status}"
          ;;
        retryable)
          warn "  Task ${task_number} (${task_id:-no-id}) marked retryable; inspect ${report_entry_display} and rerun when ready."
          ;;
        blocked|blocked-budget|blocked-quota|blocked-migration-transition|blocked-schema-drift|blocked-schema-guard-error|blocked-dependency\(*\)|permanent-fail|dead-letter)
          warn "  Task ${task_number} (${task_id:-no-id}) blocked; see ${report_entry_display}."
          ;;
        apply-failed-migration-context)
          warn "  Task ${task_number} (${task_id:-no-id}) flagged apply-failed-migration-context; inspect ${report_entry_display}."
          ;;
        *)
          info "  Task ${task_number} (${task_id:-no-id}) finished with status: ${task_result_status}"
          ;;
      esac

      local task_status_display="${task_result_status:-unknown}"
      if [[ "$task_status_display" == "complete" ]]; then
        task_status_display="COMPLETED"
      else
        task_status_display="${task_status_display//-/ }"
        task_status_display="${task_status_display//_/ }"
        task_status_display="$(printf '%s' "$task_status_display" | tr '[:lower:]' '[:upper:]')"
      fi
      if [[ -z "$task_notes_display" ]]; then
        task_notes_display="$task_status_display"
      fi

      printf '\n'
      gc_render_task_end_panel \
        "$banner_task_id" \
        "$task_status_display" \
        "$task_terminal_state" \
        "$task_duration_display" \
        "$task_story_points_display" \
        "$task_story_points" \
        "$task_tokens_total" \
        "$task_estimated_tokens_value" \
        "$task_tokens_display" \
        "$task_estimated_tokens_display" \
        "$task_failure_class" \
        ""
      # Write JSON & run end scripts
      gc_finalize_and_report "${task_result_status:-success}" "${task_notes_display:-}"

      (( ++processed_total ))
      (( ++iteration_processed ))

      case "$task_result_status" in
        blocked|blocked-budget|blocked-quota|blocked-schema-drift|blocked-schema-guard-error|blocked-dependency\(*\)|permanent-fail|dead-letter)
          story_failed=1
          break_after_update=1
          continue
          ;;
      esac

      if (( break_after_update )); then
        continue
      fi

      if (( sleep_between_positive )); then
        sleep "$sleep_between"
      fi

      if (( single_task_mode )); then
        break
      fi

    done

    if (( story_task_consumed )); then
      single_task_consumed=1
    fi

    if (( batch_limit_reached )); then
      break
    fi

    if (( story_failed )); then
      warn "Continuing after issues in story ${slug}; moving to the next story."
      story_failed=0
      if (( single_task_mode )); then
        gc_sync_story_totals "$tasks_db"
        gc_touch_progress
        break
      fi
      continue
    fi

    if (( idle_timeout_triggered )); then
      break
    fi

    if (( single_task_mode )); then
      gc_sync_story_totals "$tasks_db"
      gc_touch_progress
      if (( story_task_consumed )); then
        break
      fi
      continue
    fi

    gc_update_work_state "$tasks_db" "$slug" "complete" "$total_tasks_int" "$total_tasks_int" "$run_stamp"
    gc_touch_progress
    if (( keep_artifacts == 0 )); then
      rmdir "${story_run_dir}/prompts" 2>/dev/null || true
      rmdir "${story_run_dir}/out" 2>/dev/null || true
    fi

    if (( iteration_processed == story_progress_before )); then
      (( no_progress_story_count++ ))
      if (( iteration_processed == 0 && no_progress_story_limit > 0 && no_progress_story_count >= no_progress_story_limit )); then
        warn "No tasks executed across ${no_progress_story_count} consecutive stories; resynchronising metadata and restarting to avoid a prompt-preparation loop."
        if ! gc_sync_story_totals "$tasks_db"; then
          warn "Story/task metadata resync failed; continuing without metadata refresh."
        fi
        gc_touch_progress
        progress_safety_break=1
        break
      fi
    else
      no_progress_story_count=0
    fi
  done < <("$python_bin" "$story_plan_helper" "$tasks_db" "${story_filter}" "$resume_flag")

    if (( progress_safety_break )); then
      continue
    fi

    if (( single_task_mode )) && (( single_task_consumed )); then
      break
    fi

    if (( migration_transition_hard_stop )); then
      break
    fi

    if (( migration_transition_triggered )); then
      migration_transition_triggered=0
      if (( iteration_processed_any )); then
        processed_any_total=1
      fi
      continue
    fi

    if (( idle_timeout_triggered )); then
      break
    fi

    if (( iteration_processed_any )); then
      processed_any_total=1
    else
      if (( processed_any_total == 0 )); then
        info "No stories to process (already complete)."
      fi
      break
    fi

    if (( iteration_processed == 0 )); then
      (( no_progress_iterations++ ))
      if (( no_progress_iterations == 1 )); then
        warn "No tasks were executed in this pass; resynchronising story/task metadata to avoid a prompt loop."
        if ! gc_sync_story_totals "$tasks_db"; then
          warn "Story/task metadata resync failed; continuing without metadata refresh."
        fi
        gc_touch_progress
        continue
      fi
      warn "No tasks executed after metadata resync; stopping work-on-tasks to avoid an infinite prompt-preparation loop."
      work_failed=1
      manual_followups=1
      break
    else
      no_progress_iterations=0
    fi

    if (( batch_limit_reached )); then
      remaining_tasks="$(gc_count_pending_tasks "$tasks_db" || echo 0)"
      [[ "$remaining_tasks" =~ ^[0-9]+$ ]] || remaining_tasks=0
      break
    fi

    if (( memory_cycle )); then
      pending_tasks="$(gc_count_pending_tasks "$tasks_db" || echo 0)"
      [[ "$pending_tasks" =~ ^[0-9]+$ ]] || pending_tasks=0
      remaining_tasks="$pending_tasks"
      if (( work_failed == 0 )); then
        if (( iteration_processed > 0 )) && (( pending_tasks > 0 )); then
          gc_trim_memory "memory-cycle"
          info "Memory-cycle paused after ${iteration_processed} task(s); ${pending_tasks} pending."
          memory_cycle_single=1
          continue_current_run=1
        elif (( pending_tasks == 0 )); then
          gc_trim_memory "memory-cycle-final"
        else
          gc_trim_memory "memory-cycle"
        fi
      else
        gc_trim_memory "memory-cycle-error"
      fi
    fi

    if (( continue_current_run == 0 )); then
      remaining_tasks="$(gc_count_pending_tasks "$tasks_db" || echo 0)"
      [[ "$remaining_tasks" =~ ^[0-9]+$ ]] || remaining_tasks=0
      local unstarted_tasks
      unstarted_tasks="$(gc_count_unstarted_tasks "$tasks_db" || echo 0)"
      [[ "$unstarted_tasks" =~ ^[0-9]+$ ]] || unstarted_tasks=0

      if (( manual_followups > 0 )); then
        if (( unstarted_tasks > 0 )); then
          info "Manual follow-ups recorded; ${unstarted_tasks} task(s) still pending — continuing backlog."
          continue_current_run=1
        elif (( remaining_tasks > 0 )); then
          warn "Manual follow-ups detected; backlog paused with ${remaining_tasks} review task(s)."
        fi
      elif (( work_failed == 0 && manual_followups == 0 && memory_cycle == 0 && batch_limit_reached == 0 && effective_batch_size == 0 && iteration_processed > 0 && remaining_tasks > 0 )); then
        if [[ -n "$story_filter" ]]; then
          info "Remaining tasks detected beyond filtered story; rerun with a broader filter to continue."
        else
          info "${remaining_tasks} task(s) remain; continuing work-on-tasks automatically."
          continue_current_run=1
        fi
      fi
    fi

    if (( continue_current_run )); then
      continue
    fi

    break
  done

  if (( idle_timeout_triggered )); then
    warn "work-on-tasks halted by idle timeout after ${idle_timeout}s without progress."
  fi

  if (( processed_any_total == 0 )); then
    gc_clear_active_task
    return 0
  fi

  gc_clear_active_task

  throughput_msg=""
  if throughput_msg="$(gc_update_throughput_metrics "$tasks_db" "flush")"; then
    if [[ -n "$throughput_msg" ]]; then
      info "$throughput_msg"
    fi
  else
    warn "Failed to finalise throughput metrics."
  fi

  if (( backlog_guard_enabled )); then
    local backlog_guard_snapshot_output_after=""
    backlog_snapshot_after_path="${run_dir}/backlog-after.json"
    if backlog_guard_snapshot_output_after="$(gc_backlog_guard_snapshot "$tasks_db" "" "$backlog_guard_window_value" "$backlog_guard_wip_limit" 2>/dev/null)"; then
      if [[ -n "$backlog_guard_snapshot_output_after" ]]; then
        printf '%s\n' "$backlog_guard_snapshot_output_after" >"$backlog_snapshot_after_path"
        local backlog_guard_messages=""
        if backlog_guard_messages="$(gc_backlog_guard_compare "$backlog_snapshot_before_path" "$backlog_snapshot_after_path" "$backlog_guard_wip_limit" 2>/dev/null)"; then
          if [[ -n "$backlog_guard_messages" ]]; then
            local backlog_alerts_path="${run_dir}/backlog-alerts.log"
            printf '%s\n' "$backlog_guard_messages" >"$backlog_alerts_path"
            while IFS=$'\t' read -r backlog_level backlog_message; do
              if [[ -z "$backlog_level" && -z "$backlog_message" ]]; then
                continue
              fi
              case "${backlog_level}" in
                WARN)
                  warn "$backlog_message"
                  ;;
                INFO)
                  info "$backlog_message"
                  ;;
                FREEZE)
                  warn "$backlog_message"
                  if [[ -n "$intake_lock_path" && ! -f "$intake_lock_path" ]]; then
                    {
                      printf 'frozen_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
                      printf 'frozen_by=work-on-tasks\n'
                      printf 'reason=%s\n' "$backlog_message"
                    } >"$intake_lock_path"
                    warn "Intake frozen to contain duplicate ingress → ${intake_lock_path#${PROJECT_ROOT:-$PWD}/}"
                  fi
                  ;;
                *)
                  info "$backlog_message"
                  ;;
              esac
            done <<<"$backlog_guard_messages"
          fi
        fi
      fi
    fi
  fi

  if (( batch_limit_reached )); then
    info "Batch size limit hit after ${processed_total} task(s); rerun to continue from the next pending task."
  fi

  if (( usage_limit_triggered )); then
    warn "Codex usage limit confirmed by provider; halt further work until additional quota is available."
  fi

  if (( loop_guard_triggered )); then
    warn "LOOP_GUARD_TRIPPED: work-on-tasks halted to avoid infinite loop."
    return "$loop_guard_exit_code"
  fi

  if (( run_blocked_quota )); then
    warn "Run terminated because a prompt exceeded the configured token budget (status: blocked-quota)."
  fi

  if (( migration_transition_hard_stop )); then
    warn "Run paused because the migration epoch changed too many times during a single run; rerun work-on-tasks after investigating pending migrations."
  elif (( migration_epoch_refreshes > 0 )); then
    info "Migration epoch refreshed ${migration_epoch_refreshes} time(s) during this run; backlog was reloaded automatically."
  fi

  local budget_report_helper
  local budget_report_path="${LOG_DIR:-${PROJECT_ROOT:-$PWD}/.gpt-creator/logs}/budget-report.md"
  if budget_report_helper="$(gc_clone_python_tool "generate_budget_report.py" "$PROJECT_ROOT" 2>/dev/null)"; then
    local budget_tool_actions_json
    budget_tool_actions_json="$(gc_budget_collect_tool_actions_json)"
    "$python_bin" "$budget_report_helper" \
      --usage-file "${LOG_DIR:-${PROJECT_ROOT:-$PWD}/.gpt-creator/logs}/codex-usage.ndjson" \
      --run-id "$run_stamp" \
      --stage-limits "${GC_BUDGET_STAGE_LIMITS_JSON:-{}}" \
      --tool-actions "$budget_tool_actions_json" \
      --output "$budget_report_path" || warn "Failed to generate budget-report.md"
  fi

  if [[ $work_failed -eq 0 ]]; then
    if (( batch_limit_reached )); then
      ok "work-on-tasks paused → ${run_dir}"
    else
      ok "work-on-tasks complete → ${run_dir}"
    fi
    if (( manual_followups )); then
      warn "Manual review needed for some tasks — see notes above and preserved output artifacts."
    fi
  else
    warn "work-on-tasks completed with issues — inspect ${run_dir}"
    return 1
  fi
}
