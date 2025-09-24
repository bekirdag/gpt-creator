#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# Optional shared helpers
if [[ -f "$ROOT_DIR/src/gpt-creator.sh" ]]; then source "$ROOT_DIR/src/gpt-creator.sh"; fi
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then source "$ROOT_DIR/src/constants.sh"; fi

# Fallback helpers if not sourced
type log >/dev/null 2>&1 || log(){ printf "[%s] %s\n" "$(date +'%H:%M:%S')" "$*"; }
type warn >/dev/null 2>&1 || warn(){ printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
type die >/dev/null 2>&1 || die(){ printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
type heading >/dev/null 2>&1 || heading(){ printf "\n\033[36m== %s ==\033[0m\n" "$*"; }
usage() {
  cat <<EOF
Usage: $(basename "$0") [-f|--file sql_file] [--service db] [--compose <file>] [-y]
  -f, --file      Path to SQL dump (if omitted, will auto-discover under ./staging/sql or ./input)
      --service   Docker Compose service name for MySQL (default: db)
      --compose   Path to docker compose file (default: ./docker/compose.yaml or ./docker-compose.yml)
  -y              Do not prompt for confirmation
EOF
}

SQL_FILE=""
SERVICE="db"
COMPOSE_FILE=""
AUTO_YES="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file) SQL_FILE="${2:-}"; shift 2;;
    --service) SERVICE="${2:-}"; shift 2;;
    --compose) COMPOSE_FILE="${2:-}"; shift 2;;
    -y) AUTO_YES="true"; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1 (see --help)";;
  esac
done

# Resolve compose file
if [[ -z "${COMPOSE_FILE}" ]]; then
  if [[ -f "$ROOT_DIR/docker/compose.yaml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker/compose.yaml";
  elif [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker-compose.yml";
  else
    die "No docker compose file found (expected docker/compose.yaml or docker-compose.yml)"
  fi
fi

# Discover SQL if not provided
if [[ -z "${SQL_FILE}" ]]; then
  candidates=()
  while IFS= read -r -d '' f; do candidates+=("$f"); done < <(find "$ROOT_DIR" -type f \( -name "*.sql" -o -name "sql_dump*.sql" \) \( -path "*/staging/sql/*" -o -path "*/input/*" -o -path "$ROOT_DIR" \) -print0 || true)
  if [[ ${#candidates[@]} -eq 0 ]]; then
    die "No SQL file found. Provide with --file or place under ./staging/sql or ./input"
  fi
  # Pick the most recent
  IFS=$'\n' sorted=($(printf "%s\n" "${candidates[@]}" | xargs -I{} bash -lc 'printf "%s\t%s\n" "$(stat -f %m "{}" 2>/dev/null || stat -c %Y "{}")" "{}"' | sort -nr | cut -f2-))
  SQL_FILE="${sorted[0]}"
  log "Auto-discovered SQL file: $SQL_FILE"
fi

[[ -f "$SQL_FILE" ]] || die "SQL file not found: $SQL_FILE"

heading "Importing SQL → MySQL in service '$SERVICE'"
# Ensure service is up
CID="$(docker compose -f "$COMPOSE_FILE" ps -q "$SERVICE" || true)"
[[ -n "$CID" ]] || die "Service '$SERVICE' not found or not running. Start with: gpt-creator run compose-up"

if [[ "$AUTO_YES" != "true" ]]; then
  read -r -p "This will import '$SQL_FILE' into the DB inside '$SERVICE'. Continue? [y/N] " ans
  [[ "${ans:-}" =~ ^[Yy]$ ]] || { warn "Aborted."; exit 1; }
fi

# Copy SQL to container
TMP_IN="/tmp/import-$(date +%s).sql"
log "Copying SQL into container $CID:$TMP_IN"
docker cp "$SQL_FILE" "$CID:$TMP_IN"

# Build import command in-container (handle empty password gracefully)
log "Running mysql client in container…"
docker exec -i "$CID" sh -lc '
  set -e
  PASS="${MYSQL_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"
  PASS_OPT=""
  if [ -n "$PASS" ]; then PASS_OPT="-p$PASS"; fi
  USER_OPT="-u${MYSQL_USER:-root}"
  DB="${MYSQL_DATABASE:-app}"
  PORT="${MYSQL_PORT:-3306}"
  echo "mysql --protocol=TCP -h 127.0.0.1 -P $PORT $USER_OPT (db=$DB) < $TMP_IN"
  mysql --protocol=TCP -h 127.0.0.1 -P "$PORT" $USER_OPT $PASS_OPT "$DB" < "$TMP_IN"
  rm -f "$TMP_IN" || true
' TMP_IN="$TMP_IN"

log "Import complete."
