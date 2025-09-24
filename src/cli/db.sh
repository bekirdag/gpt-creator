#!/usr/bin/env bash
# gpt-creator · db.sh
# Convenience DB commands (status/import/dump/shell) using docker-compose.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.yml"

log(){ printf "[db] %s\n" "$*"; }
die(){ printf "[db][ERROR] %s\n" "$*" >&2; exit 1; }

dc() {
  if command -v docker >/dev/null 2>&1; then
    docker compose -f "${COMPOSE_FILE}" "$@"
  else
    die "docker not found"
  fi
}

usage() {
  cat <<'USAGE'
Usage: gpt-creator db <subcommand> [args]

Subcommands:
  up                    Start DB service
  down                  Stop DB service
  status                Show container status
  shell                 MySQL shell inside container
  import <file.sql>     Import SQL dump into DB
  dump [out.sql]        Dump database to file (default: dumps/backup.sql)
  url                   Print DATABASE_URL heuristic

Environment defaults (match docker-compose):
  DB_HOST=127.0.0.1  DB_PORT=3306  DB_NAME=yoga_app  DB_USER=yoga  DB_PASS=yoga
USAGE
}

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-yoga_app}"
DB_USER="${DB_USER:-yoga}"
DB_PASS="${DB_PASS:-yoga}"

cmd="${1:-}"; shift || true

case "${cmd}" in
  up)
    dc up -d db
    ;;
  down)
    dc stop db
    ;;
  status|"")
    dc ps
    ;;
  shell)
    dc exec db mysql -u"${DB_USER}" -p"${DB_PASS}" "${DB_NAME}"
    ;;
  import)
    file="${1:-}"; [[ -f "${file}" ]] || die "Usage: gpt-creator db import <file.sql>"
    log "Importing ${file} → ${DB_NAME}"
    dc cp "${file}" db:/import.sql
    dc exec -T db sh -lc 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /import.sql'
    log "Import complete"
    ;;
  dump)
    out="${1:-${ROOT_DIR}/dumps/backup.sql}"
    mkdir -p "$(dirname "${out}")"
    log "Dumping ${DB_NAME} → ${out}"
    dc exec -T db sh -lc 'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' > "${out}"
    log "Dump complete"
    ;;
  url)
    echo "mysql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    ;;
  *)
    usage; exit 2;;
esac
