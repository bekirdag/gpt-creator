#!/usr/bin/env bash
# shellcheck shell=bash
# mysql.sh — helpers for MySQL DB operations (client, container)
if [[ -n "${GC_LIB_MYSQL_SH:-}" ]]; then return 0; fi
GC_LIB_MYSQL_SH=1

# Start MySQL in a container (docker-compose) from default location
mysql_start() {
  # Pulls MySQL image if not available, then starts container
  if ! docker ps -q --filter "name=yoga_db" | grep -q .; then
    docker-compose up -d db
    echo "MySQL container started."
  else
    echo "MySQL container already running."
  fi
}

# Stop MySQL container
mysql_stop() {
  docker-compose stop db
  echo "MySQL container stopped."
}

# Import SQL dump to MySQL container
mysql_import() {
  local sql_file="$1"
  if [[ -z "$sql_file" || ! -f "$sql_file" ]]; then
    echo "Error: SQL file required."
    return 1
  fi
  docker exec -i yoga_db mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" yoga_db < "$sql_file"
  echo "SQL dump imported."
}

# Run MySQL client within the container
mysql_client() {
  docker exec -it yoga_db mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" yoga_db
}

# Check MySQL health
mysql_health_check() {
  if docker exec yoga_db mysqladmin ping -h "127.0.0.1" --silent; then
    echo "MySQL is healthy."
  else
    echo "MySQL is not responding!"
    return 1
  fi
}
