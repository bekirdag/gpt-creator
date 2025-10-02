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

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  CLI_NAME="gpt-creator"
  log(){ printf "[generate-docker] %s\n" "$*"; }
  die(){ printf "[generate-docker][ERROR] %s\n" "$*" >&2; exit 1; }
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
version: "3.9"
services:
  db:
    image: mysql:8.0
    container_name: ${PROJECT_SLUG}_db
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
    container_name: ${PROJECT_SLUG}_api
    depends_on:
      db:
        condition: service_healthy
    environment:
      NODE_ENV: development
      DATABASE_URL: mysql://${DB_USER}:${DB_PASS}@db:3306/${DB_NAME}
      PORT: 3000
    command: sh -c "corepack enable pnpm && cd /workspace && pnpm install --frozen-lockfile=false && cd apps/api && pnpm run start:dev"
    ports:
      - "3000:3000"
    volumes:
      - ..:/workspace

  web:
    build:
      context: ..
      dockerfile: docker/web.Dockerfile
    container_name: ${PROJECT_SLUG}_web
    environment:
      NODE_ENV: development
      VITE_API_BASE: http://localhost:3000/api/v1
    command: sh -c "corepack enable pnpm && cd /workspace && pnpm install --frozen-lockfile=false && cd apps/web && pnpm run dev -- --host 0.0.0.0"
    ports:
      - "5173:5173"
    volumes:
      - ..:/workspace

  admin:
    build:
      context: ..
      dockerfile: docker/admin.Dockerfile
    container_name: ${PROJECT_SLUG}_admin
    environment:
      NODE_ENV: development
      VITE_API_BASE: http://localhost:3000/api/v1
    command: sh -c "corepack enable pnpm && cd /workspace && pnpm install --frozen-lockfile=false && cd apps/admin && pnpm run dev -- --host 0.0.0.0"
    ports:
      - "5174:5173"
    volumes:
      - ..:/workspace

  proxy:
    image: nginx:alpine
    container_name: ${PROJECT_SLUG}_proxy
    depends_on:
      - web
      - admin
      - api
    ports:
      - "8080:80"
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
    }

    location /admin/ {
      proxy_pass http://admin:5173/;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host;
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
RECAPTCHA_SITE_KEY=
RECAPTCHA_SECRET=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
ENV

log "Wrote docker assets to: ${OUT_PATH}"
