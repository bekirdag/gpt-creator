#!/usr/bin/env bash
# gpt-creator · generate-docker.sh
# Scaffold Dockerfiles and docker-compose for local dev.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GC_TEMPLATE_ROOT="${ROOT_DIR}/assets/templates"
# shellcheck disable=SC1091
source "${ROOT_DIR}/src/cli/lib/templates.sh"

slugify() {
  local s="${1:-}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

log(){ printf "[generate-docker] %s\n" "$*"; }
die(){ printf "[generate-docker][ERROR] %s\n" "$*" >&2; exit 1; }

RESERVED_PORTS=""

port_reserved() {
  local port="$1"
  case " ${RESERVED_PORTS:-} " in
    *" ${port} "*) return 0 ;;
  esac
  return 1
}

reserve_port() {
  local port="$1"
  [[ -n "$port" ]] || return 0
  port_reserved "$port" && return 0
  if [[ -z "${RESERVED_PORTS:-}" ]]; then
    RESERVED_PORTS="$port"
  else
    RESERVED_PORTS+=" $port"
  fi
}

PROJECT_SLUG="${GC_DOCKER_PROJECT_NAME:-$(slugify "$(basename "$ROOT_DIR")")}";
export PROJECT_SLUG

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ROOT_DIR}/.env"
  set +a
fi

DB_NAME="${DB_NAME:-${GC_DB_NAME:-${PROJECT_SLUG}_app}}"
DB_USER="${DB_USER:-${GC_DB_USER:-${PROJECT_SLUG}_user}}"
DB_PASS="${DB_PASSWORD:-${GC_DB_PASSWORD:-${PROJECT_SLUG}_pass}}"
DB_ROOT_PASS="${DB_ROOT_PASSWORD:-root}"
DB_HOST_PORT="${DB_HOST_PORT:-3306}"
API_HOST_PORT="${API_HOST_PORT:-${GC_API_HOST_PORT:-3000}}"
WEB_HOST_PORT="${WEB_HOST_PORT:-${GC_WEB_HOST_PORT:-5173}}"
ADMIN_HOST_PORT="${ADMIN_HOST_PORT:-${GC_ADMIN_HOST_PORT:-5174}}"
PROXY_HOST_PORT="${PROXY_HOST_PORT:-${GC_PROXY_HOST_PORT:-8080}}"

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  elif command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -E "\\.${port} .*LISTEN" >/dev/null && return 0
  fi
  return 1
}

find_free_port() {
  local start="$1"
  local port="$start"; local limit=$((start+100))
  while (( port <= limit )); do
    if ! port_in_use "$port" && ! port_reserved "$port"; then
      printf '%s\n' "$port"
      return 0
    fi
    ((port++)) || true
  done
  printf '%s\n' "$start"
}

ensure_port() {
  local label="$1" current="$2" default="${3:-$2}"
  local port="$current"
  [[ -n "$port" && "$port" =~ ^[0-9]+$ ]] || port="$default"
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    port="$default"
  fi
  local attempts=0
  local limit=200
  while (( attempts < limit )); do
    if (( port < 1 || port > 65535 )); then
      port="$default"
    fi
    local conflict=0
    if port_in_use "$port"; then
      conflict=1
    elif port_reserved "$port" && [[ "$port" != "$current" ]]; then
      conflict=1
    fi
    if (( conflict == 0 )); then
      break
    fi
    ((port++))
    ((attempts++))
  done
  if (( attempts >= limit )); then
    log "Unable to find free port for ${label}; using ${port}" >&2
  elif [[ -n "$current" && "$port" != "$current" ]]; then
    log "Port ${current} in use; remapping ${label} to ${port}" >&2
  fi
  reserve_port "$port"
  printf '%s\n' "$port"
}

DB_HOST_PORT="$(ensure_port "MySQL" "$DB_HOST_PORT" 3306)"
API_HOST_PORT="$(ensure_port "API" "$API_HOST_PORT" 3000)"
WEB_HOST_PORT="$(ensure_port "Web" "$WEB_HOST_PORT" 5173)"
ADMIN_HOST_PORT="$(ensure_port "Admin" "$ADMIN_HOST_PORT" 5174)"
PROXY_HOST_PORT="$(ensure_port "Proxy" "$PROXY_HOST_PORT" 8080)"

API_BASE_URL="http://localhost:${API_HOST_PORT}/api/v1"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
fi

usage() {
  (
    set -a
    # shellcheck disable=SC2034
    GEN_DOCKER_OUT_DEFAULT="${OUT_DIR:-docker}"
    set +a
    gc_cli_render_template "help/generate_docker_usage.txt"
  )
}

OUT_DIR="docker"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_DIR="${2:-}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

OUT_PATH="${ROOT_DIR}/${OUT_DIR}"
mkdir -p "${OUT_PATH}"

compose="${OUT_PATH}/docker-compose.yml"
api_df="${OUT_PATH}/api.Dockerfile"
web_df="${OUT_PATH}/web.Dockerfile"
admin_df="${OUT_PATH}/admin.Dockerfile"
nginx_conf="${OUT_PATH}/nginx.conf"
env_example="${ROOT_DIR}/.env.example"

  (
    set -a
    # shellcheck disable=SC2034
    GEN_DOCKER_PROJECT_SLUG="${PROJECT_SLUG}"
    GEN_DOCKER_DB_ROOT_PASS="${DB_ROOT_PASS}"
    GEN_DOCKER_DB_NAME="${DB_NAME}"
    GEN_DOCKER_DB_USER="${DB_USER}"
  GEN_DOCKER_DB_PASS="${DB_PASS}"
  GEN_DOCKER_DB_HOST_PORT="${DB_HOST_PORT}"
  GEN_DOCKER_API_HOST_PORT="${API_HOST_PORT}"
  GEN_DOCKER_WEB_HOST_PORT="${WEB_HOST_PORT}"
  GEN_DOCKER_ADMIN_HOST_PORT="${ADMIN_HOST_PORT}"
  GEN_DOCKER_PROXY_HOST_PORT="${PROXY_HOST_PORT}"
  GEN_DOCKER_API_BASE_URL="${API_BASE_URL}"
  GEN_DOCKER_DATABASE_URL_CONTAINER="mysql://${DB_USER}:${DB_PASS}@db:3306/${DB_NAME}"
  set +a
  gc_cli_render_template "docker/docker-compose.yml.tmpl"
) > "${compose}"

gc_cli_render_template "docker/api.Dockerfile" > "${api_df}"
gc_cli_render_template "docker/web.Dockerfile" > "${web_df}"
gc_cli_render_template "docker/admin.Dockerfile" > "${admin_df}"

gc_cli_render_template "docker/nginx.conf.tmpl" > "${nginx_conf}"

  (
    set -a
    # shellcheck disable=SC2034
    GEN_DOCKER_ENV_DB_URL="mysql://${DB_USER}:${DB_PASS}@127.0.0.1:${DB_HOST_PORT}/${DB_NAME}"
    GEN_DOCKER_DB_HOST_PORT="${DB_HOST_PORT}"
    GEN_DOCKER_API_HOST_PORT="${API_HOST_PORT}"
    GEN_DOCKER_WEB_HOST_PORT="${WEB_HOST_PORT}"
  GEN_DOCKER_ADMIN_HOST_PORT="${ADMIN_HOST_PORT}"
  GEN_DOCKER_PROXY_HOST_PORT="${PROXY_HOST_PORT}"
  GEN_DOCKER_API_BASE_URL="${API_BASE_URL}"
  set +a
  gc_cli_render_template "env/docker.env.example.tmpl"
) > "${env_example}"

log "Wrote docker assets to: ${OUT_PATH}"
