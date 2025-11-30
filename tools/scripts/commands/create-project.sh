#!/usr/bin/env bash
# shellcheck shell=bash

cmd_create_project() {
  local template_request="auto"
  local path=""
  local surfaces_override=""
  local rfp_path=""
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
      --surfaces)
        surfaces_override="${2:?--surfaces requires a value (e.g., api,db,docker)}"
        shift 2
        ;;
      --rfp)
        rfp_path="${2:?--rfp requires a file path}"
        shift 2
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd create-project)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/create_project_usage.txt"
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

  [[ -n "$path" ]] || die "create-project requires a path"

  local project_root
  project_root="$(abs_path "$path")"
  mkdir -p "$project_root"

  if ! gc_apply_project_template "$project_root" "$template_request"; then
    warn "Project template application reported issues; continuing with base scaffolding."
  fi

  ensure_ctx "$project_root"
  gc_load_cmd scan
  gc_load_cmd normalize
  gc_load_cmd plan
  gc_load_cmd generate
  gc_load_cmd db
  gc_load_cmd run
  info "Project root: ${PROJECT_ROOT}"

  cmd_scan --project "$PROJECT_ROOT"
  cmd_normalize --project "$PROJECT_ROOT"

  local surfaces=""
  surfaces="$(gc_resolve_surfaces "$PROJECT_ROOT" "$surfaces_override" "$rfp_path")"
  read -r -a SURFACES_ARR <<<"$surfaces"
  if (( ${#SURFACES_ARR[@]} == 0 )); then
    warn "No surfaces detected; defaulting to api db (no docker)."
    SURFACES_ARR=(api db)
  fi
  info "Selected surfaces: ${SURFACES_ARR[*]}"

  cmd_plan --project "$PROJECT_ROOT"

  local has_docker=0 has_db=0
  local docker_services_str=""
  local -a docker_services=()
  for surface in "${SURFACES_ARR[@]}"; do
    case "$surface" in
      docker) has_docker=1 ;;
      db) has_db=1 ;;
    esac
  done
  docker_services_str="$(gc_docker_services_from_surfaces "${SURFACES_ARR[@]}")"
  read -r -a docker_services <<<"$docker_services_str"
  if (( ${#docker_services[@]} > 0 )); then
    has_docker=1
  fi

  for surface in "${SURFACES_ARR[@]}"; do
    case "$surface" in
      docker) ;;
      *) cmd_generate "$surface" --project "$PROJECT_ROOT" ;;
    esac
  done

  if (( has_docker )) && (( ${#docker_services[@]} > 0 )); then
    GC_DOCKER_SERVICES="${docker_services[*]}" cmd_generate docker --project "$PROJECT_ROOT"
  elif (( has_docker )); then
    info "Skipping docker assets because no docker services were detected (set GC_DOCKER_SERVICES to force generation)."
  else
    info "Skipping docker assets because 'docker' was not selected for this project."
  fi

  if (( has_db && has_docker )); then
    cmd_db provision --project "$PROJECT_ROOT" || warn "Database provision step reported an error"
  else
    info "Skipping DB provision (db or docker not selected)."
  fi
  if (( has_docker )); then
    cmd_run up --project "$PROJECT_ROOT" || warn "Stack start reported an error"
  else
    info "Skipping stack startup (docker not selected)."
  fi
  ok "Project bootstrap complete"
}
