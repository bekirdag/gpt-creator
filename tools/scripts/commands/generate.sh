#!/usr/bin/env bash
# shellcheck shell=bash

cmd_generate() {
  local facet="${1:-}"; shift || true
  [[ -n "$facet" ]] || die "generate requires a facet: api|web|admin|db|docker|all"
  local root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      *) break;;
    esac
  done
  ensure_ctx "$root"
  local templates="$CLI_ROOT/templates"

  case "$facet" in
    api)
      local out="$PROJECT_ROOT/apps/api"
      mkdir -p "$out"
      copy_template_tree "$templates/api/nestjs" "$out"
      ok "API scaffolded → ${out}"
      ;;
    web)
      local out="$PROJECT_ROOT/apps/web"
      mkdir -p "$out"
      copy_template_tree "$templates/web/vue3" "$out"
      ok "Web scaffolded → ${out}"
      ;;
    admin)
      local out="$PROJECT_ROOT/apps/admin"
      mkdir -p "$out"
      copy_template_tree "$templates/admin/vue3" "$out"
      ok "Admin scaffolded → ${out}"
      ;;
    db)
      local out="$PROJECT_ROOT/db"
      mkdir -p "$out"
      copy_template_tree "$templates/db/mysql" "$out"
      ok "DB artifacts scaffolded → ${out}"
      ;;
    docker)
      local out="$PROJECT_ROOT/docker"
      mkdir -p "$out"
      local services_raw=""
      if [[ ${GC_DOCKER_SERVICES+x} ]]; then
        services_raw="${GC_DOCKER_SERVICES}"
      else
        services_raw="db api web admin proxy mobile"
      fi
      local -a docker_services=()
      for item in $services_raw; do
        docker_services+=("$item")
      done
      if (( ${#docker_services[@]} == 0 )); then
        warn "No docker services requested; skipping docker scaffold."
        return 0
      fi
      service_enabled() {
        local name="$1"
        for svc in "${docker_services[@]}"; do
          [[ "$svc" == "$name" ]] && return 0
        done
        return 1
      }
      local preferred="${GC_DB_HOST_PORT:-${DB_HOST_PORT:-${MYSQL_HOST_PORT:-3306}}}"
      gc_unreserve_port db
      if service_enabled db && port_in_use "$preferred"; then
        local next; next="$(find_free_port "$preferred")"
        if [[ "$next" != "$preferred" ]]; then
          info "Port $preferred in use; remapping MySQL to $next"
          preferred="$next"
        fi
      fi
      if service_enabled db; then
        GC_DB_HOST_PORT="$preferred"
        DB_HOST_PORT="$GC_DB_HOST_PORT"
        MYSQL_HOST_PORT="$GC_DB_HOST_PORT"
        gc_reserve_port db "$GC_DB_HOST_PORT"
        gc_set_env_var DB_HOST_PORT "$GC_DB_HOST_PORT"
        gc_set_env_var MYSQL_HOST_PORT "$GC_DB_HOST_PORT"
        gc_set_env_var GC_DB_HOST_PORT "$GC_DB_HOST_PORT"
        local local_url="mysql://${GC_DB_USER}:${GC_DB_PASSWORD}@127.0.0.1:${GC_DB_HOST_PORT}/${GC_DB_NAME}"
        gc_set_env_var DATABASE_URL "$local_url"
      fi
      local api_host_port=""
      if service_enabled api; then
        api_host_port="$(gc_pick_port "API" 3000 GC_API_HOST_PORT API_HOST_PORT)"
        GC_API_HOST_PORT="$api_host_port"
        API_HOST_PORT="$GC_API_HOST_PORT"
        gc_set_env_var API_HOST_PORT "$API_HOST_PORT"
        gc_set_env_var GC_API_HOST_PORT "$GC_API_HOST_PORT"
        gc_reserve_port api "$GC_API_HOST_PORT"
        local api_base_url="http://localhost:${GC_API_HOST_PORT}/api/v1"
        gc_set_env_var GC_API_BASE_URL "$api_base_url"
        gc_set_env_var VITE_API_BASE "$api_base_url"
        local api_health_url="${api_base_url%/}/health"
        gc_set_env_var GC_API_HEALTH_URL "$api_health_url"
      fi
      local web_host_port=""
      if service_enabled web; then
        web_host_port="$(gc_pick_port "Web" 5173 GC_WEB_HOST_PORT WEB_HOST_PORT)"
        GC_WEB_HOST_PORT="$web_host_port"
        WEB_HOST_PORT="$GC_WEB_HOST_PORT"
        gc_set_env_var WEB_HOST_PORT "$WEB_HOST_PORT"
        gc_set_env_var GC_WEB_HOST_PORT "$GC_WEB_HOST_PORT"
        gc_reserve_port web "$GC_WEB_HOST_PORT"
      fi
      local admin_host_port=""
      if service_enabled admin; then
        admin_host_port="$(gc_pick_port "Admin" 5174 GC_ADMIN_HOST_PORT ADMIN_HOST_PORT)"
        GC_ADMIN_HOST_PORT="$admin_host_port"
        ADMIN_HOST_PORT="$GC_ADMIN_HOST_PORT"
        gc_set_env_var ADMIN_HOST_PORT "$ADMIN_HOST_PORT"
        gc_set_env_var GC_ADMIN_HOST_PORT "$GC_ADMIN_HOST_PORT"
        gc_reserve_port admin "$GC_ADMIN_HOST_PORT"
      fi
      local proxy_host_port=""
      local include_proxy=0
      if service_enabled web && service_enabled admin && service_enabled api; then
        include_proxy=1
        proxy_host_port="$(gc_pick_port "Proxy" 8080 GC_PROXY_HOST_PORT PROXY_HOST_PORT)"
        GC_PROXY_HOST_PORT="$proxy_host_port"
        PROXY_HOST_PORT="$GC_PROXY_HOST_PORT"
        gc_set_env_var PROXY_HOST_PORT "$PROXY_HOST_PORT"
        gc_set_env_var GC_PROXY_HOST_PORT "$GC_PROXY_HOST_PORT"
        gc_reserve_port proxy "$GC_PROXY_HOST_PORT"
        local proxy_base="http://localhost:${GC_PROXY_HOST_PORT}"
        gc_set_env_var GC_WEB_URL "${proxy_base}/"
        gc_set_env_var GC_ADMIN_URL "${proxy_base}/admin/"
      elif service_enabled web; then
        local web_base="http://localhost:${GC_WEB_HOST_PORT:-5173}"
        gc_set_env_var GC_WEB_URL "${web_base}/"
      elif service_enabled admin; then
        local admin_base="http://localhost:${GC_ADMIN_HOST_PORT:-5174}"
        gc_set_env_var GC_ADMIN_URL "${admin_base}/"
      fi
      gc_load_env
      copy_template_tree "$templates/docker" "$out"
      if [[ -f "$out/pnpm-entry.sh" ]]; then
        chmod +x "$out/pnpm-entry.sh" || true
      fi
      # Prune docker-compose.yml to selected services
      local keep_services=()
      for svc in "${docker_services[@]}"; do
        case "$svc" in
          api|db|web|admin|mobile|proxy) keep_services+=("$svc") ;;
        esac
      done
      if (( include_proxy == 0 )); then
        # remove proxy unless explicitly included by web+admin+api
        local pruned_keep=()
        for svc in "${keep_services[@]}"; do
          [[ "$svc" == "proxy" ]] && continue
          pruned_keep+=("$svc")
        done
        keep_services=("${pruned_keep[@]}")
      fi
      if [[ -f "$out/docker-compose.yml" && ${#keep_services[@]} -gt 0 ]]; then
        local scripts_root="${GC_SCRIPTS_ROOT:-${CLI_ROOT}/tools/scripts}"
        if [[ -n "${CLI_ROOT:-}" && ! -d "$scripts_root" ]]; then
          scripts_root="${CLI_ROOT}/scripts"
        fi
        local prune_helper="${scripts_root}/python/prune_compose_services.py"
        if [[ -f "$prune_helper" ]]; then
          python3 "$prune_helper" "$out/docker-compose.yml" "${keep_services[@]}"
          ok "Docker compose pruned to services: ${keep_services[*]}"
        else
          warn "prune_compose_services.py missing; skipping compose pruning."
        fi
      fi
      ok "Docker assets scaffolded → ${out}"
      ;;
    all)
      for f in api db web admin docker; do
        cmd_generate "$f" --project "$PROJECT_ROOT"
      done
      return 0
      ;;
    *) die "Unknown facet: ${facet}";;
  esac
}
