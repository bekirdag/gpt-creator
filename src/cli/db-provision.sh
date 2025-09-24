#!/usr/bin/env bash
# gpt-creator · db-provision.sh
# Bring up MySQL (docker-compose), wait for readiness, create DB if needed.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.yml"

log(){ printf "[db-provision] %s\n" "$*"; }
die(){ printf "[db-provision][ERROR] %s\n" "$*" >&2; exit 1; }

dc() { docker compose -f "${COMPOSE_FILE}" "$@"; }

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-yoga_app}"
DB_USER="${DB_USER:-yoga}"
DB_PASS="${DB_PASS:-yoga}"

usage() {
  cat <<'USAGE'
Usage: gpt-creator db provision [--import path.sql]

Starts MySQL container (docker-compose), waits for readiness, optionally imports an SQL dump.
USAGE
}

SQL_IMPORT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --import) SQL_IMPORT="${2:-}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

log "Starting DB service ..."
dc up -d db

log "Waiting for MySQL to become healthy ..."
for i in $(seq 1 60); do
  if dc exec -T db sh -lc 'mysqladmin ping -h 127.0.0.1 -p"$MYSQL_ROOT_PASSWORD" --silent' >/dev/null 2>&1; then
    log "MySQL is healthy"
    break
  fi
  sleep 2
done

if [[ -n "${SQL_IMPORT}" ]]; then
  [[ -f "${SQL_IMPORT}" ]] || die "Not found: ${SQL_IMPORT}"
  log "Importing ${SQL_IMPORT} ..."
  dc cp "${SQL_IMPORT}" db:/import.sql
  dc exec -T db sh -lc 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /import.sql'
  log "Import complete."
fi

# Write a local .env with DATABASE_URL for convenience
ENV_PATH="${ROOT_DIR}/.env.local"
echo "DATABASE_URL=mysql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}" > "${ENV_PATH}"
log "Wrote ${ENV_PATH}"
