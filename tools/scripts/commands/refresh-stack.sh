#!/usr/bin/env bash
# shellcheck shell=bash

cmd_refresh_stack() {
  local root="" compose_override="" sql_override="" seed_override=""
  local skip_import=0 skip_seed=0
  local only_services="" skip_services=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --compose) compose_override="$(abs_path "$2")"; shift 2;;
      --sql) sql_override="$(abs_path "$2")"; shift 2;;
      --seed) seed_override="$(abs_path "$2")"; shift 2;;
      --no-import) skip_import=1; shift;;
      --no-seed) skip_seed=1; shift;;
      --only-services) only_services="${2:-}"; shift 2;;
      --skip-services) skip_services="${2:-}"; shift 2;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd refresh-stack)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/refresh_stack_usage.txt"
        fi
        return 0
        ;;
      *) break;;
    esac
  done

  ensure_ctx "$root"
  gc_load_cmd generate

  local -a refresh_sql_init_files=() refresh_sql_schema_files=() refresh_sql_seed_files=() refresh_sql_all_files=()
  local refresh_sql_default_db_name="" refresh_sql_default_db_user="" refresh_sql_default_db_password="" refresh_sql_default_user_host=""
  eval "$(gc_refresh_stack_collect_sql "$PROJECT_ROOT")"

  if [[ -n "$sql_override" ]]; then
    refresh_sql_schema_files=("$sql_override")
  fi
  if [[ -n "$seed_override" ]]; then
    refresh_sql_seed_files=("$seed_override")
  fi

  local env_updated=0
  if [[ -n "$refresh_sql_default_db_name" && "$refresh_sql_default_db_name" != "$GC_DB_NAME" ]]; then
    gc_set_env_var DB_NAME "$refresh_sql_default_db_name"
    gc_set_env_var GC_DB_NAME "$refresh_sql_default_db_name"
    env_updated=1
  fi
  if [[ -n "$refresh_sql_default_db_user" && "$refresh_sql_default_db_user" != "$GC_DB_USER" ]]; then
    gc_set_env_var DB_USER "$refresh_sql_default_db_user"
    gc_set_env_var GC_DB_USER "$refresh_sql_default_db_user"
    env_updated=1
  fi
  if [[ -n "$refresh_sql_default_db_password" && "$refresh_sql_default_db_password" != "$GC_DB_PASSWORD" ]]; then
    gc_set_env_var DB_PASSWORD "$refresh_sql_default_db_password"
    gc_set_env_var GC_DB_PASSWORD "$refresh_sql_default_db_password"
    env_updated=1
  fi
  if (( env_updated )); then
    gc_load_env
    local host_port="${GC_DB_HOST_PORT:-${DB_HOST_PORT:-3306}}"
    local database_url="mysql://${GC_DB_USER}:${GC_DB_PASSWORD}@127.0.0.1:${host_port}/${GC_DB_NAME}"
    gc_set_env_var DATABASE_URL "$database_url"
  fi

  info "Using database '${GC_DB_NAME}' with user '${GC_DB_USER}'"

  local docker_services_resolved=""
  if [[ -n "${GC_DOCKER_SERVICES:-}" ]]; then
    docker_services_resolved="${GC_DOCKER_SERVICES}"
  else
    local detected_surfaces=""
    detected_surfaces="$(gc_detect_surfaces "$PROJECT_ROOT")"
    if [[ -n "$detected_surfaces" ]]; then
      local -a detected_surfaces_arr=()
      read -r -a detected_surfaces_arr <<<"$detected_surfaces"
      docker_services_resolved="$(gc_docker_services_from_surfaces "${detected_surfaces_arr[@]}")"
      if [[ -n "$docker_services_resolved" ]]; then
        GC_DOCKER_SERVICES="$docker_services_resolved"
      fi
    fi
  fi

  local compose_file="$compose_override"
  if [[ -n "$compose_file" ]]; then
    compose_file="$(abs_path "$compose_file")"
  else
    info "Rendering docker assets from templates"
    if [[ -n "$docker_services_resolved" ]]; then
      if ! GC_DOCKER_SERVICES="$docker_services_resolved" cmd_generate docker --project "$PROJECT_ROOT"; then
        die "Failed to generate docker assets"
      fi
    else
      if [[ -f "${PROJECT_ROOT}/docker/compose.yaml" ]]; then
        compose_file="${PROJECT_ROOT}/docker/compose.yaml"
      elif [[ -f "${PROJECT_ROOT}/docker/docker-compose.yml" ]]; then
        compose_file="${PROJECT_ROOT}/docker/docker-compose.yml"
      elif [[ -f "${PROJECT_ROOT}/docker-compose.yml" ]]; then
        compose_file="${PROJECT_ROOT}/docker-compose.yml"
      else
        die "No docker services detected and no compose file found. Set GC_DOCKER_SERVICES or provide --compose/--only-services."
      fi
    fi
    if [[ -z "$compose_file" ]]; then
      if [[ -f "${PROJECT_ROOT}/docker/compose.yaml" ]]; then
        compose_file="${PROJECT_ROOT}/docker/compose.yaml"
      elif [[ -f "${PROJECT_ROOT}/docker/docker-compose.yml" ]]; then
        compose_file="${PROJECT_ROOT}/docker/docker-compose.yml"
      elif [[ -f "${PROJECT_ROOT}/docker-compose.yml" ]]; then
        compose_file="${PROJECT_ROOT}/docker-compose.yml"
      fi
    fi
    if [[ -z "$compose_file" ]]; then
      die "Compose file not found after generation. Expected docker/compose.yaml or docker-compose.yml"
    fi
  fi

  info "Refreshing Docker stack for ${GC_DOCKER_PROJECT_NAME}"

  info "Stopping existing containers (removing volumes)"
  docker_compose -f "$compose_file" down -v --remove-orphans || true

  local slug="$GC_DOCKER_PROJECT_NAME"
  local -a stale_containers=(
    "${slug}-db"
    "${slug}-api"
    "${slug}-web"
    "${slug}-admin"
    "${slug}-proxy"
    "${slug}_db"
    "${slug}_api"
    "${slug}_web"
    "${slug}_admin"
    "${slug}_proxy"
  )
  local container
  for container in "${stale_containers[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -Fxq "$container"; then
      info "Removing leftover container ${container}"
      docker rm -f "$container" >/dev/null 2>&1 || true
    fi
  done

  if (( ${#refresh_sql_all_files[@]} > 0 )); then
    info "Discovered SQL assets:"
    local listed
    for listed in "${refresh_sql_all_files[@]}"; do
      if [[ "$listed" == "$PROJECT_ROOT/"* ]]; then
        info "  - ${listed#$PROJECT_ROOT/}"
      else
        info "  - ${listed}"
      fi
    done
  else
    info "No SQL assets discovered automatically."
  fi

  local -a all_services=()
  if [[ -n "$docker_services_resolved" ]]; then
    read -r -a all_services <<<"$docker_services_resolved"
  else
    all_services=()
  fi
  local -a services_to_start=()
  if [[ -n "$only_services" ]]; then
    local normalized_only="${only_services//,/ }"
    read -r -a services_to_start <<< "$normalized_only"
  else
    services_to_start=("${all_services[@]}")
  fi
  if [[ -n "$skip_services" ]]; then
    local -a skip_list=()
    local normalized_skip="${skip_services//,/ }"
    read -r -a skip_list <<< "$normalized_skip"
    if (( ${#skip_list[@]} > 0 )); then
      local -a filtered=()
      local svc skip_flag skip_item
      for svc in "${services_to_start[@]}"; do
        skip_flag=0
        for skip_item in "${skip_list[@]}"; do
          [[ -z "$skip_item" ]] && continue
          if [[ "$svc" == "$skip_item" ]]; then
            skip_flag=1
            break
          fi
        done
        if (( skip_flag == 0 )); then
          filtered+=("$svc")
        fi
      done
      services_to_start=("${filtered[@]}")
    fi
  fi
  if (( ${#services_to_start[@]} > 0 )); then
    # Deduplicate and drop empties
    local -a deduped=()
    local svc seen_services=""
    for svc in "${services_to_start[@]}"; do
      [[ -z "$svc" ]] && continue
      case " $seen_services " in
        *" $svc "*) continue ;;
      esac
      deduped+=("$svc")
      seen_services+=" $svc"
    done
    services_to_start=("${deduped[@]}")
  fi

  # Prune compose to selected services
  if [[ -f "$compose_file" && ${#services_to_start[@]} -gt 0 ]]; then
    local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
    if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
      scripts_root="${CLI_ROOT}/scripts"
    fi
    local prune_helper="${scripts_root}/python/prune_compose_services.py"
    if [[ -f "$prune_helper" ]]; then
      python3 "$prune_helper" "$compose_file" "${services_to_start[@]}" || warn "Compose pruning reported an error; continuing."
    else
      warn "prune_compose_services.py missing; skipping compose pruning."
    fi
  fi

  if (( ${#services_to_start[@]} == 0 )); then
    warn "No services selected to start; skipping docker compose up."
  else
    info "Building and starting containers (${services_to_start[*]})"
    GC_DOCKER_VERBOSE="${GC_DOCKER_VERBOSE:-1}"
    gc_refresh_stack_prepare_node_modules
    docker_compose -f "$compose_file" up -d --build "${services_to_start[@]}"
    gc_start_created_containers "$compose_file" "${services_to_start[@]}"
  fi

  local db_requested=0
  local svc
  for svc in "${services_to_start[@]}"; do
    if [[ "$svc" == "db" ]]; then
      db_requested=1
      break
    fi
  done

  local db_container=""
  if (( db_requested )); then
    db_container="$(docker_compose -f "$compose_file" ps -q db || true)"
    if [[ -n "$db_container" ]]; then
      info "Waiting for MySQL to be ready…"
      local mysql_timeout="${GC_DOCKER_HEALTH_TIMEOUT:-10}"
      local sleep_interval="${GC_DOCKER_HEALTH_INTERVAL:-1}"
      (( sleep_interval <= 0 )) && sleep_interval=1
      local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
      if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
        scripts_root="${CLI_ROOT}/scripts"
      fi
      local wait_helper="${scripts_root}/python/wait_for_mysql.py"
      if [[ -f "$wait_helper" ]] && "${PYTHON_BIN:-python3}" "$wait_helper" "$db_container" "$mysql_timeout" "$sleep_interval"; then
        info "MySQL is ready."
      else
        warn "MySQL readiness timeout after ${mysql_timeout}s (continuing)."
      fi
    else
      warn "Database container did not start; SQL import will be skipped."
    fi
  else
    info "Database service excluded from start; skipping readiness wait."
  fi

  docker_compose -f "$compose_file" ps

  local db_port="3306"
  local root_user="${DB_ROOT_USER:-root}"
  local root_pass="${DB_ROOT_PASSWORD:-${GC_DB_ROOT_PASSWORD:-}}"
  local app_user="${DB_USER:-$GC_DB_USER}"
  local app_pass="${DB_PASSWORD:-$GC_DB_PASSWORD}"
  local db_name="${DB_NAME:-$GC_DB_NAME}"
  local app_host="${refresh_sql_default_user_host:-%}"
  local python_bin="${PYTHON_BIN:-python3}"

  local import_rc=0 seed_rc=0
  local schema_attempted=0 seed_attempted=0

  if [[ -z "$db_container" ]]; then
    (( skip_import == 0 )) && import_rc=1
    (( skip_seed == 0 )) && seed_rc=1
  else
    if (( skip_import == 0 || skip_seed == 0 )); then
      local ensure_sql=""
      if command -v "$python_bin" >/dev/null 2>&1; then
        local ensure_helper
        ensure_helper="$(gc_clone_python_tool "gc_refresh_stack_ensure_sql.py" "${PROJECT_ROOT:-$PWD}")" || return 1
        ensure_sql="$("$python_bin" "$ensure_helper" "$db_name" "$app_user" "$app_pass" "$app_host")"
      else
        warn "Skipping database/user ensure; ${python_bin} not available."
      fi
      if [[ -n "$ensure_sql" ]]; then
        if ! gc_refresh_stack_exec_inline_sql "$db_container" "$root_user" "$root_pass" "" "$db_port" <<<"$ensure_sql"; then
          warn "Failed to ensure database or user; continuing with imports."
        else
          info "Ensured database ${db_name} and user ${app_user}"
        fi
      fi
    fi

    if (( skip_import == 0 )) && (( ${#refresh_sql_init_files[@]} + ${#refresh_sql_schema_files[@]} == 0 )); then
      info "No schema SQL files found; skipping import."
      skip_import=1
    fi
    if (( skip_seed == 0 )) && (( ${#refresh_sql_seed_files[@]} == 0 )); then
      info "No seed SQL files found; skipping seeding."
      skip_seed=1
    fi

    if (( skip_import == 0 || skip_seed == 0 )); then
      local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
      if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
        scripts_root="${CLI_ROOT}/scripts"
      fi
      local db_helper="${scripts_root}/python/refresh_stack_db.py"
      if [[ -f "$db_helper" ]]; then
        local db_output
        if db_output="$("${python_bin}" "$db_helper" "$db_container" "$root_user" "$root_pass" "$app_user" "$app_pass" "$db_name" "$db_port" "${refresh_sql_init_files[@]}" "${refresh_sql_schema_files[@]}" -- "${refresh_sql_seed_files[@]}")"; then
          local parsed
          if parsed="$("${python_bin}" - "$db_output" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
print(data.get("schema_rc", 1))
print(data.get("seed_rc", 1))
print(len(data.get("schema_applied", [])))
print(len(data.get("seed_applied", [])))
PY
)"; then
            read -r import_rc seed_rc schema_attempted seed_attempted <<<"$parsed"
          else
            warn "Failed to parse refresh_stack_db.py output; assuming errors."
            import_rc=1
            seed_rc=1
          fi
        else
          warn "refresh_stack_db.py failed; falling back to bash SQL execution."
          import_rc=1
          seed_rc=1
        fi
      else
        warn "refresh_stack_db.py missing; skipping Python-based SQL import."
        import_rc=1
        seed_rc=1
      fi
    fi
  fi

  info "Verifying Docker service health"
  local stack_health_rc=0
  if gc_refresh_stack_wait_for_containers "$compose_file" "${GC_DOCKER_HEALTH_TIMEOUT:-10}" "${GC_DOCKER_HEALTH_INTERVAL:-1}"; then
    ok "Docker services healthy"
  else
    stack_health_rc=1
    warn "Docker services reported issues; inspect compose logs for details."
  fi

  local status=0
  (( import_rc != 0 )) && status=1
  (( seed_rc != 0 )) && status=1
  (( stack_health_rc != 0 )) && status=1

  if (( status == 0 )); then
    ok "Stack refreshed successfully"
  else
    warn "Stack refresh completed with issues; inspect logs above."
  fi
  return $status
}
