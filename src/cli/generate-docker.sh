#!/usr/bin/env bash
# gpt-creator · generate-docker.sh
# Scaffold Dockerfiles and docker-compose for local dev.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

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
  cat <<'USAGE'
Usage:
  gpt-creator generate docker [--out docker]
Options:
  --out   Output directory for docker assets. Default: docker
USAGE
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

cat > "${compose}" <<YML
services:
  db:
    image: mysql:8.0
    container_name: ${PROJECT_SLUG}-db
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASS}
      MYSQL_ROOT_HOST: '%'
      MYSQL_DATABASE: ${DB_NAME}
      MYSQL_USER: ${DB_USER}
      MYSQL_PASSWORD: ${DB_PASS}
    ports:
      - "${DB_HOST_PORT}:3306"
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p${DB_ROOT_PASS}"]
      interval: 5s
      timeout: 3s
      retries: 30
    volumes:
      - db_data:/var/lib/mysql

  api:
    build:
      context: ..
      dockerfile: docker/api.Dockerfile
    container_name: ${PROJECT_SLUG}-api
    depends_on:
      db:
        condition: service_healthy
    environment:
      NODE_ENV: development
      DATABASE_URL: mysql://${DB_USER}:${DB_PASS}@db:3306/${DB_NAME}
      PORT: 3000
      GC_SERVICE: api
    command: sh -c "corepack enable pnpm && cd /workspace && CI=1 pnpm install --frozen-lockfile=false && cd apps/api && pnpm run start:dev"
    ports:
      - "${API_HOST_PORT}:3000"
    volumes:
      - ..:/workspace

  web:
    build:
      context: ..
      dockerfile: docker/web.Dockerfile
    container_name: ${PROJECT_SLUG}-web
    environment:
      NODE_ENV: development
      VITE_API_BASE: ${API_BASE_URL}
      GC_SERVICE: web
    command: sh -c "corepack enable pnpm && cd /workspace && CI=1 pnpm install --frozen-lockfile=false && cd apps/web && pnpm run dev -- --host 0.0.0.0"
    ports:
      - "${WEB_HOST_PORT}:5173"
    volumes:
      - ..:/workspace

  admin:
    build:
      context: ..
      dockerfile: docker/admin.Dockerfile
    container_name: ${PROJECT_SLUG}-admin
    environment:
      NODE_ENV: development
      VITE_API_BASE: ${API_BASE_URL}
      GC_SERVICE: admin
    command: sh -c "corepack enable pnpm && cd /workspace && CI=1 pnpm install --frozen-lockfile=false && cd apps/admin && pnpm run dev -- --host 0.0.0.0"
    ports:
      - "${ADMIN_HOST_PORT}:5173"
    volumes:
      - ..:/workspace

  proxy:
    image: nginx:alpine
    container_name: ${PROJECT_SLUG}-proxy
    depends_on:
      - web
      - admin
      - api
    ports:
      - "${PROXY_HOST_PORT}:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro

volumes:
  db_data: {}
YML

cat > "${api_df}" <<'DOCKER'
# API (NestJS) development Dockerfile
FROM node:20-alpine
RUN corepack enable pnpm && mkdir -p /workspace/apps/api
WORKDIR /workspace/apps/api
EXPOSE 3000
CMD ["sh", "-c", "while true; do sleep 3600; done"]
DOCKER

cat > "${web_df}" <<'DOCKER'
# Website (Vue 3) development Dockerfile
FROM node:20-alpine
RUN corepack enable pnpm && mkdir -p /workspace/apps/web
WORKDIR /workspace/apps/web
EXPOSE 5173
CMD ["sh", "-c", "while true; do sleep 3600; done"]
DOCKER

cat > "${admin_df}" <<'DOCKER'
# Admin (Vue 3) development Dockerfile
FROM node:20-alpine
RUN corepack enable pnpm && mkdir -p /workspace/apps/admin
WORKDIR /workspace/apps/admin
EXPOSE 5173
CMD ["sh", "-c", "while true; do sleep 3600; done"]
DOCKER

cat > "${nginx_conf}" <<'NGINX'
events {}
http {
  server {
    listen 80;
    server_name _;

    location / {
      proxy_pass http://web:5173;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host;
      proxy_redirect off;
    }

    location /admin/ {
      proxy_pass http://admin:5173;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host;
      proxy_redirect off;
    }

    location /api/ {
      proxy_pass http://api:3000/api/;
      proxy_set_header Host $host;
    }
  }
}
NGINX

cat > "${env_example}" <<ENV
# Copy to .env.local and edit as needed
DATABASE_URL=mysql://${DB_USER}:${DB_PASS}@127.0.0.1:${DB_HOST_PORT}/${DB_NAME}
DB_HOST_PORT=${DB_HOST_PORT}
API_HOST_PORT=${API_HOST_PORT}
WEB_HOST_PORT=${WEB_HOST_PORT}
ADMIN_HOST_PORT=${ADMIN_HOST_PORT}
PROXY_HOST_PORT=${PROXY_HOST_PORT}
VITE_API_BASE=${API_BASE_URL}
RECAPTCHA_SITE_KEY=
RECAPTCHA_SECRET=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
ENV

log "Wrote docker assets to: ${OUT_PATH}"
