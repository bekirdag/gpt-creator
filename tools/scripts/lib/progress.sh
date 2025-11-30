#!/usr/bin/env bash
# Progress artifact migration and sweep helpers.

GC_PROGRESS_DIR_MIGRATIONS=(
  "Design::staging/docs"
  "legal_editor_tmp::artifacts"
)

GC_PROGRESS_FILE_MIGRATIONS=(
  "tmp_*::artifacts/tmp"
  "final_*::artifacts/final"
  "dump_*::artifacts/dump"
  "diff*::artifacts/diff"
  "change_*::artifacts/change"
  "changes_*::artifacts/change"
  "codex_*::artifacts/codex"
  "backlog.md::artifacts/planning"
  "plan.md::artifacts/planning"
  "tasks.json::staging/plan/legacy"
  "encoded*::artifacts/encoded"
  "breadcrumbs*.json::artifacts/ui"
  "cli_content.json::artifacts/context"
  "focusTrap.json::artifacts/ui"
  "navStore.json::artifacts/ui"
  "service_content.json::artifacts/context"
  "login_diff.txt::artifacts/diff"
  "login_json.txt::artifacts/context"
  "output_payload.json::artifacts/output"
  "changes_output.json::artifacts/change"
  "changes_strings.txt::artifacts/change"
  "*.patch::artifacts/patches"
  "*_patch.jsonstr::artifacts/patches"
  "*.rej::artifacts/patches"
  "*.rej.orig::artifacts/patches"
  "*.orig::artifacts/patches"
)

GC_PROGRESS_MIGRATION_LAST_COUNT=0

gc_move_progress_artifact() {
  local source_path="${1:-}"
  local target_dir="${2:-}"
  [[ -e "$source_path" ]] || return 1
  [[ -d "$target_dir" ]] || mkdir -p "$target_dir"
  local filename target
  filename="$(basename "$source_path")"
  target="${target_dir}/${filename}"
  if [[ -e "$target" ]]; then
    local idx=1
    while [[ -e "$target" ]]; do
      target="${target_dir}/${idx}-${filename}"
      idx=$((idx + 1))
    done
  fi
  if mv -- "$source_path" "$target"; then
    printf '%s\t%s\n' "$source_path" "$target"
    return 0
  fi
  return 1
}

gc_migrate_progress_artifacts() {
  local project_root="$1"
  local work_dir_name="${GC_WORK_DIR_NAME:-.gpt-creator}"
  local gc_root="${project_root}/${work_dir_name}"
  local skip="${GC_SKIP_PROGRESS_MIGRATION:-0}"
  [[ -d "$project_root" ]] || return 0
  [[ "$skip" == "1" ]] && return 0
  if [[ -n "${GC_ROOT:-}" && "$project_root" == "$GC_ROOT" ]]; then
    return 0
  fi
  GC_PROGRESS_MIGRATION_LAST_COUNT=0
  local python_bin="${PYTHON_BIN:-python3}"
  local -a moved=()
  local entry src_rel dest_rel src_path dest_dir record

  for entry in "${GC_PROGRESS_DIR_MIGRATIONS[@]}"; do
    src_rel="${entry%%::*}"
    dest_rel="${entry#*::}"
    src_path="${project_root}/${src_rel}"
    [[ -d "$src_path" ]] || continue
    dest_dir="${gc_root}/${dest_rel}"
    if record="$(gc_move_progress_artifact "$src_path" "$dest_dir")"; then
      moved+=("$record")
    fi
  done

  shopt -s nullglob dotglob
  for entry in "${GC_PROGRESS_FILE_MIGRATIONS[@]}"; do
    src_rel="${entry%%::*}"
    dest_rel="${entry#*::}"
    local path
    for path in "$project_root"/$src_rel; do
      [[ -e "$path" ]] || continue
      [[ "$path" == "$gc_root"* ]] && continue
      dest_dir="${gc_root}/${dest_rel}"
      if record="$(gc_move_progress_artifact "$path" "$dest_dir")"; then
        moved+=("$record")
      fi
    done
  done
  shopt -u nullglob dotglob

  if ((${#moved[@]} > 0)); then
    local log_dir="${gc_root}/logs"
    mkdir -p "$log_dir"
    local log_file="${log_dir}/progress-migration.log"
    {
      printf -- '--- %s ---\n' "$(date '+%Y-%m-%d %H:%M:%S')"
      local row src_abs dst_abs src_relpath dst_relpath
      for row in "${moved[@]}"; do
        src_abs="${row%%$'\t'*}"
        dst_abs="${row#*$'\t'}"
        src_relpath="${src_abs#$project_root/}"
        dst_relpath="${dst_abs#$project_root/}"
        printf -- '%s -> %s\n' "$src_relpath" "$dst_relpath"
      done
    } >>"$log_file"
    info "Migrated ${#moved[@]} work artifacts into .gpt-creator (see ${log_file#$project_root/})."
  fi
  GC_PROGRESS_MIGRATION_LAST_COUNT=${#moved[@]}

  local tasks_db="${gc_root}/staging/plan/tasks/tasks.db"
  if [[ -f "$tasks_db" ]]; then
    local plan_path="${gc_root}/logs/progress-migration.plan.json"
    local map_path="${gc_root}/logs/progress-migration.map.ndjson"
    local helper_path=""
    gc_clone_python_tool "task_comments.py" "$project_root" >/dev/null 2>&1 || true
    if ! helper_path="$(gc_clone_python_tool "progress_migration.py" "$project_root")"; then
      warn "Unable to prepare progress migration helper; skipping task state reconciliation."
      return 0
    fi
    if ! command -v "$python_bin" >/dev/null 2>&1; then
      warn "Skipping task state reconciliation; ${python_bin} not available."
      return 0
    fi
    local plan_output=""
    if plan_output="$("$python_bin" "$helper_path" plan --db "$tasks_db" --output "$plan_path" 2>/dev/null)"; then
      local plan_updates=""
      local plan_stats_helper=""
      if plan_stats_helper="$(gc_clone_python_tool "progress_migration_extract_plan_updates.py" "$project_root")"; then
        plan_updates="$("$python_bin" "$plan_stats_helper" "$plan_output" 2>/dev/null)"
      fi
      if [[ -n "$plan_updates" && "$plan_updates" != "0" ]]; then
        info "Planned task migration updates for ${plan_updates} item(s); applying carry-over."
      fi
      local apply_output=""
      if apply_output="$("$python_bin" "$helper_path" apply --db "$tasks_db" --plan "$plan_path" --map-log "$map_path" 2>/dev/null)"; then
        local apply_stats=""
        local apply_stats_helper=""
        if apply_stats_helper="$(gc_clone_python_tool "progress_migration_extract_apply_stats.py" "$project_root")"; then
          apply_stats="$("$python_bin" "$apply_stats_helper" "$apply_output" 2>/dev/null)"
        fi
        if [[ -n "$apply_stats" ]]; then
          IFS=$'\t' read -r updatedTotal preservedTotal lockedTotal reopenedTotal <<<"$apply_stats"
          info "Carried forward migration state for ${updatedTotal:-0} task(s) (preserved=${preservedTotal:-0}, locked=${lockedTotal:-0}, reopened=${reopenedTotal:-0})."
        fi
      else
        warn "Failed to apply task migration plan; inspect ${plan_path#$project_root/} for details."
      fi
    fi
  fi
}

# Manual command helper to sweep legacy artifacts
cmd_sweep_artifacts() {
  local -a projects=()
  local arg project_path
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|-p)
        [[ -n "${2:-}" ]] || die "--project requires a directory path"
        project_path="$(abs_path "$2")"
        projects+=("$project_path")
        shift 2
        ;;
      -h|--help)
        gc_render_template "help/sweep_artifacts_usage.txt"
        return 0
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do
          projects+=("$(abs_path "$1")")
          shift
        done
        ;;
      -*)
        die "Unknown flag for sweep-artifacts: $1"
        ;;
      *)
        projects+=("$(abs_path "$1")")
        shift
        ;;
    esac
  done

  if ((${#projects[@]} == 0)); then
    projects+=("$(abs_path "${PROJECT_ROOT:-$PWD}")")
  fi

  local root count prev_skip_set prev_skip_val
  for root in "${projects[@]}"; do
    if [[ ! -d "$root" ]]; then
      warn "Skipping missing directory: ${root}"
      continue
    fi
    info "Tidying progress artifacts under ${root}"
    prev_skip_set=0
    prev_skip_val=""
    if [[ ${GC_SKIP_PROGRESS_MIGRATION+x} ]]; then
      prev_skip_set=1
      prev_skip_val="$GC_SKIP_PROGRESS_MIGRATION"
    else
      prev_skip_set=0
      prev_skip_val=""
    fi
    GC_SKIP_PROGRESS_MIGRATION=0
    gc_migrate_progress_artifacts "$root"
    count=${GC_PROGRESS_MIGRATION_LAST_COUNT:-0}
    if (( prev_skip_set )); then
      GC_SKIP_PROGRESS_MIGRATION="$prev_skip_val"
    else
      unset GC_SKIP_PROGRESS_MIGRATION
    fi
    if (( count > 0 )); then
      ok "Relocated ${count} artifact(s) into ${root}/.gpt-creator."
    else
      info "No legacy artifacts found outside .gpt-creator."
    fi
  done

  return 0
}

cmd_tidy_progress() {
  warn "'tidy-progress' has been renamed to 'sweep-artifacts'. Running the renamed command."
  cmd_sweep_artifacts "$@"
}
