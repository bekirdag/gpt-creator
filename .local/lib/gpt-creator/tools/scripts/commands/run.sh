#!/usr/bin/env bash
# shellcheck shell=bash

cmd_run() {
  local action="${1:-}"; shift || true
  [[ -n "$action" ]] || die "run requires: up|down|logs|open"
  local root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      *) break;;
    esac
  done
  ensure_ctx "$root"
  local compose_file="$PROJECT_ROOT/docker/docker-compose.yml"

  ensure_ports_available() {
    local updated=0
    # API
    local api_port="${GC_API_HOST_PORT:-${API_HOST_PORT:-3000}}"
    if port_in_use "$api_port"; then
      local new_port; new_port="$(find_free_port "$api_port")"
      info "Port ${api_port} in use; remapping API to ${new_port}"
      api_port="$new_port"; updated=1
      gc_set_env_var API_HOST_PORT "$api_port"
      gc_set_env_var GC_API_HOST_PORT "$api_port"
      gc_set_env_var GC_API_BASE_URL "http://localhost:${api_port}/api/v1"
      gc_set_env_var GC_API_HEALTH_URL "http://localhost:${api_port}/api/v1/health"
      gc_set_env_var VITE_API_BASE "http://localhost:${api_port}/api/v1"
    fi
    # Web/Admin/Proxy
    local web_port="${GC_WEB_HOST_PORT:-${WEB_HOST_PORT:-5173}}"
    local admin_port="${GC_ADMIN_HOST_PORT:-${ADMIN_HOST_PORT:-5174}}"
    local proxy_port="${GC_PROXY_HOST_PORT:-${PROXY_HOST_PORT:-8080}}"
    if port_in_use "$web_port"; then
      local new_port; new_port="$(find_free_port "$web_port")"
      info "Port ${web_port} in use; remapping Web to ${new_port}"
      web_port="$new_port"; updated=1; gc_set_env_var WEB_HOST_PORT "$web_port"; gc_set_env_var GC_WEB_HOST_PORT "$web_port"
    fi
    if port_in_use "$admin_port"; then
      local new_port; new_port="$(find_free_port "$admin_port")"
      info "Port ${admin_port} in use; remapping Admin to ${new_port}"
      admin_port="$new_port"; updated=1; gc_set_env_var ADMIN_HOST_PORT "$admin_port"; gc_set_env_var GC_ADMIN_HOST_PORT "$admin_port"
    fi
    if port_in_use "$proxy_port"; then
      local new_port; new_port="$(find_free_port "$proxy_port")"
      info "Port ${proxy_port} in use; remapping Proxy to ${new_port}"
      proxy_port="$new_port"; updated=1; gc_set_env_var PROXY_HOST_PORT "$proxy_port"; gc_set_env_var GC_PROXY_HOST_PORT "$proxy_port"
    fi
    if (( updated )); then
      gc_set_env_var GC_WEB_URL "http://localhost:${GC_PROXY_HOST_PORT:-$proxy_port}/"
      gc_set_env_var GC_ADMIN_URL "http://localhost:${GC_PROXY_HOST_PORT:-$proxy_port}/admin/"
      gc_load_env
      cmd_generate docker --project "$PROJECT_ROOT"
    fi
  }

  ensure_service_deps() {
    local svc="$1" expected_bin="$2"
    local host_bin="$PROJECT_ROOT/apps/${svc}/node_modules/.bin/${expected_bin}"
    if [[ -x "$host_bin" ]]; then
      return 0
    fi
    info "[deps] Installing dependencies for ${svc} (missing ${expected_bin})"
    if ! docker_compose -f "$compose_file" run --rm --entrypoint "pnpm" "$svc" install; then
      warn "[deps] pnpm install failed for ${svc}"
    fi
  }

  case "$action" in
    up)
      [[ -f "$compose_file" ]] || die "Compose file not found at ${compose_file}; generate docker assets first."
      ensure_ports_available
      compose_file="$PROJECT_ROOT/docker/docker-compose.yml"
      ensure_service_deps api nest
      ensure_service_deps web vite
      ensure_service_deps admin vite
      gc_refresh_stack_prepare_node_modules
      docker_compose -f "$compose_file" up -d
      ok "Stack is starting (check docker compose ps)"
      local api_base="${GC_API_BASE_URL:-http://localhost:3000/api/v1}"
      local web_url="${GC_WEB_URL:-http://localhost:8080/}"
      local admin_url="${GC_ADMIN_URL:-http://localhost:8080/admin/}"
      local health_timeout="${GC_DOCKER_HEALTH_TIMEOUT:-30}"
      local health_interval="${GC_DOCKER_HEALTH_INTERVAL:-1}"
      wait_for_endpoint "${api_base%/}/health" "API /health" "$health_timeout" "$health_interval" || true
      local web_ping="${web_url%/}/__vite_ping"
      if ! wait_for_endpoint "$web_ping" "Web (vite ping)" "$health_timeout" "$health_interval"; then
        wait_for_endpoint "${web_url%/}/" "Web" "$health_timeout" "$health_interval" || true
      fi
      local admin_ping="${admin_url%/}/__vite_ping"
      if ! wait_for_endpoint "$admin_ping" "Admin (vite ping)" "$health_timeout" "$health_interval"; then
        wait_for_endpoint "${admin_url%/}/" "Admin" "$health_timeout" "$health_interval" || true
      fi
      ;;
    down)
      [[ -f "$compose_file" ]] || die "Compose file not found at ${compose_file}"
      docker_compose -f "$compose_file" down
      ok "Stack shut down"
      ;;
    logs)
      [[ -f "$compose_file" ]] || die "Compose file not found at ${compose_file}"
      docker_compose -f "$compose_file" logs -f
      ;;
    open)
      if command -v open >/dev/null 2>&1; then
        open "http://localhost:8080" || open "http://localhost:5173" || true
      else
        ${EDITOR_CMD} "$PROJECT_ROOT" || true
      fi
      ;;
    *) die "Unknown run action: ${action}";;
  esac
}
