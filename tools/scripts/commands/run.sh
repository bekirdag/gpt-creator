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

  case "$action" in
    up)
      [[ -f "$compose_file" ]] || die "Compose file not found at ${compose_file}; generate docker assets first."
      gc_refresh_stack_prepare_node_modules
      docker_compose -f "$compose_file" up -d
      ok "Stack is starting (check docker compose ps)"
      local api_base="${GC_API_BASE_URL:-http://localhost:3000/api/v1}"
      local web_url="${GC_WEB_URL:-http://localhost:8080/}"
      local admin_url="${GC_ADMIN_URL:-http://localhost:8080/admin/}"
      local health_timeout="${GC_DOCKER_HEALTH_TIMEOUT:-10}"
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

