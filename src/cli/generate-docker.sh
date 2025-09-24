#!/usr/bin/env bash
# gpt-creator · generate-docker.sh
# Scaffold Dockerfiles and docker-compose for local dev.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

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

cat > "${compose}" <<'YML'
version: "3.9"
services:
  db:
    image: mysql:8.0
    container_name: yoga_db
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: yoga_app
      MYSQL_USER: yoga
      MYSQL_PASSWORD: yoga
    ports:
      - "3306:3306"
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-proot"]
      interval: 5s
      timeout: 3s
      retries: 30
    volumes:
      - db_data:/var/lib/mysql

  api:
    build:
      context: ..
      dockerfile: docker/api.Dockerfile
    container_name: yoga_api
    depends_on:
      db:
        condition: service_healthy
    environment:
      NODE_ENV: development
      DATABASE_URL: mysql://yoga:yoga@db:3306/yoga_app
      PORT: 3000
    ports:
      - "3000:3000"
    volumes:
      - ../apps/api:/workspace/apps/api
      - ../package.json:/workspace/package.json

  web:
    build:
      context: ..
      dockerfile: docker/web.Dockerfile
    container_name: yoga_web
    environment:
      NODE_ENV: development
      VITE_API_BASE: http://localhost:3000/api/v1
    ports:
      - "5173:5173"
    volumes:
      - ../apps/web:/workspace/apps/web

  admin:
    build:
      context: ..
      dockerfile: docker/admin.Dockerfile
    container_name: yoga_admin
    environment:
      NODE_ENV: development
      VITE_API_BASE: http://localhost:3000/api/v1
    ports:
      - "5174:5173"
    volumes:
      - ../apps/admin:/workspace/apps/admin

  proxy:
    image: nginx:alpine
    container_name: yoga_proxy
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
FROM node:20-bullseye
WORKDIR /workspace
COPY package*.json ./
RUN npm ci || npm install
# Expect local volume mounts for source; install dev tools
RUN npm i -g @nestjs/cli prisma
EXPOSE 3000
CMD ["bash", "-lc", "cd apps/api && npm run start:dev"]
DOCKER

cat > "${web_df}" <<'DOCKER'
# Website (Vue 3) development Dockerfile
FROM node:20-bullseye
WORKDIR /workspace
COPY package*.json ./
RUN npm ci || npm install
EXPOSE 5173
CMD ["bash", "-lc", "cd apps/web && npm run dev -- --host 0.0.0.0"]
DOCKER

cat > "${admin_df}" <<'DOCKER'
# Admin (Vue 3) development Dockerfile
FROM node:20-bullseye
WORKDIR /workspace
COPY package*.json ./
RUN npm ci || npm install
EXPOSE 5173
CMD ["bash", "-lc", "cd apps/admin && npm run dev -- --host 0.0.0.0"]
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

cat > "${env_example}" <<'ENV'
# Copy to .env.local and edit as needed
DATABASE_URL=mysql://yoga:yoga@127.0.0.1:3306/yoga_app
RECAPTCHA_SITE_KEY=
RECAPTCHA_SECRET=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
ENV

log "Wrote docker assets to: ${OUT_PATH}"
