#!/usr/bin/env bash
# shellcheck shell=bash
# mysql.sh — helpers for MySQL DB operations (client, container)
if [[ -n "${GC_LIB_MYSQL_SH:-}" ]]; then return 0; fi
GC_LIB_MYSQL_SH=1

# Start MySQL in a container (docker-compose) from default location
mysql::_slugify() {
  local s="${1:-}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

mysql::_project_slug() {
  local slug="${GC_DOCKER_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-}}"
  if [[ -z "$slug" ]]; then
    local root="${GC_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}"
    slug="$(mysql::_slugify "$(basename "$root")")"
  fi
  printf '%s\n' "$slug"
}

mysql::_container() {
  printf '%s-db\n' "$(mysql::_project_slug)"
}

mysql_start() {
  local container
  container="$(mysql::_container)"
  if ! docker ps -q --filter "name=${container}" | grep -q .; then
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
      COMPOSE_PROJECT_NAME="$(mysql::_project_slug)" docker compose up -d db
    else
      docker-compose -p "$(mysql::_project_slug)" up -d db
    fi
    echo "MySQL container started."
  else
    echo "MySQL container already running."
  fi
}

mysql_stop() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_PROJECT_NAME="$(mysql::_project_slug)" docker compose stop db
  else
    docker-compose -p "$(mysql::_project_slug)" stop db
  fi
  echo "MySQL container stopped."
}

mysql_import() {
  local sql_file="$1"
  if [[ -z "$sql_file" || ! -f "$sql_file" ]]; then
    echo "Error: SQL file required."
    return 1
  fi
  local container
  container="$(mysql::_container)"
  local database="${MYSQL_DATABASE:-${DB_NAME:-app}}"
  docker exec -i "$container" mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "$database" < "$sql_file"
  echo "SQL dump imported."
}

mysql_client() {
  local container
  container="$(mysql::_container)"
  local database="${MYSQL_DATABASE:-${DB_NAME:-app}}"
  docker exec -it "$container" mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "$database"
}

mysql_health_check() {
  local container
  container="$(mysql::_container)"
  if docker exec "$container" mysqladmin ping -h "127.0.0.1" --silent; then
    echo "MySQL is healthy."
  else
    echo "MySQL is not responding!"
    return 1
  fi
}
