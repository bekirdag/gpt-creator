#!/usr/bin/env bash
# shellcheck shell=bash

cmd_refine_tasks() {
  local root="" story_filter="" model_override="" dry_run=0 force=0
  case "${GC_DRY_RUN:-}" in
    1|true|yes|on) dry_run=1 ;;
  esac
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --story) story_filter="$2"; shift 2;;
      --model) model_override="$2"; shift 2;;
      --dry-run) dry_run=1; shift;;
      --force) force=1; shift;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd refine-tasks)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/refine_tasks_usage.txt"
        fi
        return 0
        ;;
      *) break;;
    esac
  done

  ensure_ctx "$root"

  local tasks_db="${PLAN_DIR}/tasks/tasks.db"
  [[ -f "$tasks_db" ]] || die "Tasks database not found: ${tasks_db}"

  local python_bin="${PYTHON_BIN:-python3}"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    die "Python runtime '$python_bin' not available; cannot refine tasks."
  fi

  local pipeline_dir="${PLAN_DIR}/create-jira-tasks"
  local json_tasks_dir="${pipeline_dir}/json/tasks"
  [[ -d "$json_tasks_dir" ]] || die "Tasks JSON directory not found: ${json_tasks_dir}"

  local have_refined
  local refine_init_helper
  refine_init_helper="$(gc_clone_python_tool "refine_tasks_init_db.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  have_refined="$($python_bin "$refine_init_helper" "$tasks_db")"

  local summary
  local refine_summary_helper
  refine_summary_helper="$(gc_clone_python_tool "refine_tasks_summary.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  summary="$($python_bin "$refine_summary_helper" "$tasks_db" "$story_filter")" || die "Failed to summarise tasks backlog"

  local total_tasks refined_tasks pending_tasks total_stories pending_stories
  read -r total_tasks refined_tasks pending_tasks total_stories pending_stories <<<"$summary"

  if (( force )); then
    local refine_reset_helper
    refine_reset_helper="$(gc_clone_python_tool "refine_tasks_reset.py" "${PROJECT_ROOT:-$PWD}")" || return 1
    "$python_bin" "$refine_reset_helper" "$tasks_db"
    refined_tasks=0
    pending_tasks=$total_tasks
  fi

  info "Backlog summary → tasks: total=${total_tasks}, refined=${refined_tasks}, pending=${pending_tasks}; stories: total=${total_stories}, pending=${pending_stories}${story_filter:+ (filter='${story_filter}')}."

  local codex_cmd="${CODEX_BIN:-${CODEX_CMD:-codex}}"
  if (( dry_run == 0 )) && ! command -v "$codex_cmd" >/dev/null 2>&1; then
    warn "Codex CLI '$codex_cmd' not found; switching to --dry-run."
    dry_run=1
  fi

  local model_name="${model_override:-${CODEX_MODEL:-$GC_DEFAULT_MODEL}}"

  # shellcheck source=src/lib/create-jira-tasks/pipeline.sh
  source "${CLI_ROOT}/src/lib/create-jira-tasks/pipeline.sh"

  local force_flag=0
  local skip_refine=0
  local dry_flag="$dry_run"
  cjt::init "$PROJECT_ROOT" "$model_name" "$force_flag" "$skip_refine" "$dry_flag"
  # shellcheck disable=SC2034
  CJT_DOC_FILES=()
  cjt::build_context_files

  export CJT_SYNC_DB=1
  export CJT_TASKS_DB_PATH="$tasks_db"
  export CJT_IGNORE_REFINE_STATE=1
  export CJT_REFINE_FORCE=$force
  export CJT_HAVE_REFINED_COLUMN="$have_refined"
  export CJT_REFINE_TOTAL_TASKS="$total_tasks"
  export CJT_REFINE_REFINED_TASKS="$refined_tasks"
  export CJT_REFINE_PENDING_TASKS="$pending_tasks"
  export CJT_REFINE_TOTAL_STORIES="$total_stories"
  export CJT_REFINE_PENDING_STORIES="$pending_stories"
  if [[ -n "$story_filter" ]]; then
    export CJT_ONLY_STORY_SLUG="$story_filter"
  fi
  if (( force )); then
    export CJT_REFINE_MODE="all"
  fi

  cjt::refine_tasks
  ok "Task refinement complete"
}
