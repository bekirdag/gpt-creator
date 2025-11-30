#!/usr/bin/env bash
# shellcheck shell=bash

cmd_bootstrap() {
  local template_request="auto"
  local path=""
  local fresh=0
  local rfp_path=""
  local bootstrap_surfaces=""
  local -a BOOTSTRAP_SURFACES_ARR=()
  local -a BOOTSTRAP_DOCKER_SERVICES=()
  local bootstrap_has_docker=0
  local bootstrap_has_db=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --template)
        template_request="${2:?--template requires a value (template name or 'auto')}"
        shift 2
        ;;
      --skip-template)
        template_request="skip"
        shift
        ;;
      --rfp)
        rfp_path="${2:?--rfp requires a file path}"
        shift 2
        ;;
      --fresh)
        fresh=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd bootstrap)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/bootstrap_usage.txt"
        fi
        return 0
        ;;
      *)
        if [[ -z "$path" ]]; then
          path="$1"
        else
          die "Unexpected argument: $1"
        fi
        shift
        ;;
    esac
  done

  [[ -n "$path" ]] || die "bootstrap requires a path"

  if [[ -n "$rfp_path" ]]; then
    [[ -f "$rfp_path" ]] || die "RFP file not found: ${rfp_path}"
  fi

  local project_root
  project_root="$(abs_path "$path")"
  mkdir -p "$project_root"

  ensure_ctx "$project_root"
  gc_load_cmd scan
  gc_load_cmd normalize
  gc_load_cmd create-jira-tasks
  gc_load_cmd plan
  gc_load_cmd generate
  gc_load_cmd db
  gc_load_cmd run
  info "Project root: ${PROJECT_ROOT}"

  if (( fresh )); then
    gc_bootstrap_reset_state
  fi

  mkdir -p "$(gc_bootstrap_state_dir)"

  if gc_bootstrap_step_is_done template; then
    info "Step 'template' already completed; skipping."
  else
    if gc_apply_project_template "$PROJECT_ROOT" "$template_request"; then
      gc_bootstrap_mark_step template "done"
    else
      gc_bootstrap_mark_step template "failed"
      die "Project template application failed"
    fi
  fi

  if [[ -n "$rfp_path" ]]; then
    local staged_rfp="${INPUT_DIR}/rfp.md"
    local staged_docs_rfp="${STAGING_DIR}/docs/rfp.md"
    if gc_bootstrap_step_is_done stage-rfp; then
      if [[ ! -f "$staged_rfp" || ! -f "$staged_docs_rfp" ]]; then
        info "Restaging RFP (previous artifacts missing)."
        gc_bootstrap_mark_step stage-rfp "reset"
      fi
    fi
    if ! gc_bootstrap_step_is_done stage-rfp; then
      mkdir -p "${INPUT_DIR}"
      cp "$rfp_path" "$staged_rfp"
      mkdir -p "${STAGING_DIR}/docs"
      cp "$rfp_path" "${STAGING_DIR}/docs/rfp.md"
      gc_bootstrap_mark_step stage-rfp "done"
      info "Staged RFP → ${staged_rfp}"
    else
      info "Step 'stage-rfp' already completed; skipping."
    fi
  fi

  info "[1/10] Scanning documentation"
  if ! gc_bootstrap_run_step scan cmd_scan --project "$PROJECT_ROOT"; then
    die "Bootstrap halted during scan"
  fi

  info "[2/10] Normalizing documentation"
  if ! gc_bootstrap_run_step normalize cmd_normalize --project "$PROJECT_ROOT"; then
    die "Bootstrap halted during normalize"
  fi

  info "[3/10] Generating Product Requirements Document"
  if gc_bootstrap_step_is_done create-pdr; then
    info "Step 'create-pdr' already completed; skipping."
  else
    if ! gc_bootstrap_have_rfp; then
      warn "No RFP found in staging; skipping create-pdr. Provide --rfp or add .gpt-creator/staging/docs/rfp.md to enable this step."
      gc_bootstrap_mark_step create-pdr "done"
    elif bash "$CLI_ROOT/src/cli/create-pdr.sh" --project "$PROJECT_ROOT"; then
      gc_bootstrap_mark_step create-pdr "done"
    else
      gc_bootstrap_mark_step create-pdr "failed"
      die "create-pdr failed"
    fi
  fi

  info "[4/10] Generating System Design Specification"
  if gc_bootstrap_step_is_done create-sds; then
    info "Step 'create-sds' already completed; skipping."
  else
    if bash "$CLI_ROOT/src/cli/create-sds.sh" --project "$PROJECT_ROOT"; then
      gc_bootstrap_mark_step create-sds "done"
    else
      gc_bootstrap_mark_step create-sds "failed"
      die "create-sds failed"
    fi
  fi

  info "[5/11] Generating database schema & seed dumps"
  if gc_bootstrap_step_is_done create-db-dump; then
    info "Step 'create-db-dump' already completed; skipping."
  else
    if bash "$CLI_ROOT/src/cli/create-db-dump.sh" --project "$PROJECT_ROOT"; then
      gc_bootstrap_mark_step create-db-dump "done"
    else
      gc_bootstrap_mark_step create-db-dump "failed"
      die "create-db-dump failed"
    fi
  fi

  info "[6/11] Mining Jira tasks"
  if ! gc_bootstrap_step_is_done create-jira-tasks; then
    if cmd_create_jira_tasks --project "$PROJECT_ROOT"; then
      gc_bootstrap_mark_step create-jira-tasks "done"
    else
      gc_bootstrap_mark_step create-jira-tasks "failed"
      die "create-jira-tasks failed"
    fi
  else
    info "Step 'create-jira-tasks' already completed; skipping."
  fi

  info "[7/11] Planning build"
  if ! gc_bootstrap_step_is_done plan; then
    if cmd_plan --project "$PROJECT_ROOT"; then
      gc_bootstrap_mark_step plan "done"
    else
      gc_bootstrap_mark_step plan "failed"
      die "plan step failed"
    fi
  else
    info "Step 'plan' already completed; skipping."
  fi

  bootstrap_surfaces="$(gc_resolve_surfaces "$PROJECT_ROOT" "" "$rfp_path")"
  read -r -a BOOTSTRAP_SURFACES_ARR <<<"$bootstrap_surfaces"
  if [[ -n "$bootstrap_surfaces" ]]; then
    info "Selected surfaces: ${BOOTSTRAP_SURFACES_ARR[*]}"
  fi
  local bootstrap_docker_services_str=""
  bootstrap_docker_services_str="$(gc_docker_services_from_surfaces "${BOOTSTRAP_SURFACES_ARR[@]}")"
  read -r -a BOOTSTRAP_DOCKER_SERVICES <<<"$bootstrap_docker_services_str"
  local surface
  for surface in "${BOOTSTRAP_SURFACES_ARR[@]}"; do
    case "$surface" in
      docker) bootstrap_has_docker=1 ;;
      db) bootstrap_has_db=1 ;;
    esac
  done
  if (( ${#BOOTSTRAP_DOCKER_SERVICES[@]} > 0 )); then
    bootstrap_has_docker=1
  fi

  if ! gc_bootstrap_step_is_done generate; then
    info "[8/11] Generating stack code"
    local generation_failed=0
    if (( ${#BOOTSTRAP_SURFACES_ARR[@]} == 0 )); then
      warn "No surfaces detected; defaulting to api db (no docker)."
      BOOTSTRAP_SURFACES_ARR=(api db)
      bootstrap_has_db=1
      bootstrap_has_docker=0
      BOOTSTRAP_DOCKER_SERVICES=()
    fi
    for surface in "${BOOTSTRAP_SURFACES_ARR[@]}"; do
      case "$surface" in
        docker) continue ;;
      esac
      if ! cmd_generate "$surface" --project "$PROJECT_ROOT"; then
        generation_failed=1
        break
      fi
    done
    if (( generation_failed )); then
      gc_bootstrap_mark_step generate "failed"
      die "generate step failed"
    fi
    if (( bootstrap_has_docker )); then
      if ! GC_DOCKER_SERVICES="${BOOTSTRAP_DOCKER_SERVICES[*]}" cmd_generate docker --project "$PROJECT_ROOT"; then
        gc_bootstrap_mark_step generate "failed"
        die "generate step failed"
      fi
    else
      info "Skipping docker assets because 'docker' was not selected or no docker services were detected (set GC_DOCKER_SERVICES to force generation)."
    fi
    gc_bootstrap_mark_step generate "done"
  else
    info "Step 'generate' already completed; skipping."
  fi

  info "[9/11] Provisioning infrastructure"
  if ! gc_bootstrap_step_is_done db-provision; then
    if (( bootstrap_has_db && bootstrap_has_docker )); then
      if cmd_db provision --project "$PROJECT_ROOT"; then
        gc_bootstrap_mark_step db-provision "done"
      else
        gc_bootstrap_mark_step db-provision "failed"
        die "Database provision failed"
      fi
    else
      info "Skipping DB provision (db or docker not selected)."
      gc_bootstrap_mark_step db-provision "done"
    fi
  else
    info "Step 'db-provision' already completed; skipping."
  fi

  info "[10/11] Starting stack"
  if ! gc_bootstrap_step_is_done run-up; then
    if (( bootstrap_has_docker )); then
      if cmd_run up --project "$PROJECT_ROOT"; then
        gc_bootstrap_mark_step run-up "done"
      else
        gc_bootstrap_mark_step run-up "failed"
        die "Stack start failed"
      fi
    else
      info "Skipping stack startup (docker not selected)."
      gc_bootstrap_mark_step run-up "done"
    fi
  else
    info "Step 'run-up' already completed; skipping."
  fi

  if ! gc_bootstrap_step_is_done verify; then
    gc_bootstrap_mark_step verify "done"
  else
    info "Step 'verify' already completed; skipping."
  fi

  info "[11/11] Finalizing bootstrap"
  gc_bootstrap_mark_complete
  ok "Bootstrap complete — code, docs, and backlog generated"
}
