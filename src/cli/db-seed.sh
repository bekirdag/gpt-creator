#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# Optional shared helpers
if [[ -f "$ROOT_DIR/src/gpt-creator.sh" ]]; then source "$ROOT_DIR/src/gpt-creator.sh"; fi
if [[ -f "$ROOT_DIR/src/constants.sh" ]]; then source "$ROOT_DIR/src/constants.sh"; fi

slugify() {
  local s="${1:-}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
  s="$(printf '%s' "$s" | tr -cs 'a-z0-9' '-')"
  s="$(printf '%s' "$s" | sed -E 's/-+/-/g; s/^-+//; s/-+$//')"
  printf '%s\n' "${s:-gptcreator}"
}

PROJECT_SLUG="${GC_DOCKER_PROJECT_NAME:-$(slugify "$(basename "$ROOT_DIR")")}";
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$PROJECT_SLUG}"

PROJECT_ROOT_DIR="${PROJECT_ROOT:-$ROOT_DIR}"
TMP_DIR="${PROJECT_ROOT_DIR}/.gpt-creator/tmp"

# Fallback helpers if not sourced
gc_cli_log(){ printf "[%s] %s\n" "$(date +'%H:%M:%S')" "$*"; }
gc_cli_warn(){ printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
gc_cli_die(){ printf "\033[31m[ERROR]\033[0m %s\n" "$*" >&2; exit 1; }
gc_cli_heading(){ printf "\n\033[36m== %s ==\033[0m\n" "$*"; }
usage() {
  cat <<EOF
Usage: $(basename "$0") [--service db] [--compose <file>] [--from sql_file]
   --service   Docker Compose service name for MySQL (default: db)
   --compose   Path to docker compose file (default: ./docker/compose.yaml or ./docker-compose.yml)
   --from      Optional path to a seed .sql file. If omitted, default seeds are applied.
EOF
}

SERVICE="db"
COMPOSE_FILE=""
FROM_SQL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE="${2:-}"; shift 2;;
    --compose) COMPOSE_FILE="${2:-}"; shift 2;;
    --from) FROM_SQL="${2:-}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) gc_cli_die "Unknown arg: $1 (see --help)";;
  esac
done

if [[ -z "${COMPOSE_FILE}" ]]; then
  if [[ -f "$ROOT_DIR/docker/compose.yaml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker/compose.yaml";
  elif [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then COMPOSE_FILE="$ROOT_DIR/docker-compose.yml";
  else
    gc_cli_die "No docker compose file found (expected docker/compose.yaml or docker-compose.yml)"
  fi
fi

CID="$(COMPOSE_PROJECT_NAME="$PROJECT_SLUG" docker compose -f "$COMPOSE_FILE" ps -q "$SERVICE" || true)"
[[ -n "$CID" ]] || gc_cli_die "Service '$SERVICE' not found or not running. Start with: gpt-creator run compose-up"

gc_cli_heading "Seeding database in service '$SERVICE'"

if [[ -n "${FROM_SQL}" ]]; then
  [[ -f "$FROM_SQL" ]] || gc_cli_die "--from file not found: $FROM_SQL"
  PROJECT_ROOT="$PROJECT_ROOT_DIR" "$ROOT_DIR/src/cli/db-import.sh" --service "$SERVICE" --compose "$COMPOSE_FILE" --file "$FROM_SQL" -y
  exit 0
fi

# Default idempotent seed set (safe to re-run)
SEED_FILE="$TMP_DIR/seed-default.sql"
mkdir -p "$TMP_DIR"

cat > "$SEED_FILE" <<'SQL'
-- Default idempotent seeds (safe to run multiple times)
SET NAMES utf8mb4;

-- class_types
CREATE TABLE IF NOT EXISTS class_types (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  `key` VARCHAR(40) UNIQUE NOT NULL,
  label_tr VARCHAR(80) NOT NULL,
  label_en VARCHAR(80) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO class_types (`key`, label_tr, label_en) VALUES
  ('yoga-1','Yoga 1','Yoga 1'),
  ('yoga-2','Yoga 2','Yoga 2'),
  ('her-seviye','Her Seviye','All Levels'),
  ('fly-yoga','Fly Yoga','Aerial Yoga'),
  ('hamile','Hamile Yogası','Prenatal')
ON DUPLICATE KEY UPDATE label_tr=VALUES(label_tr), label_en=VALUES(label_en);

-- instructors
CREATE TABLE IF NOT EXISTS instructors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  slug VARCHAR(80) UNIQUE NOT NULL,
  full_name VARCHAR(120) NOT NULL,
  photo_url TEXT NULL,
  short_bio TEXT NULL,
  specialties TEXT NULL,
  display_order INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO instructors (slug, full_name, short_bio, display_order) VALUES
  ('burcu','Burcu', 'Eğitmen', 1),
  ('ceren','Ceren', 'Eğitmen', 2),
  ('fulya','Fulya', 'Eğitmen', 3),
  ('nilay','Nilay', 'Eğitmen', 4)
ON DUPLICATE KEY UPDATE full_name=VALUES(full_name);

-- pages (minimal placeholders)
CREATE TABLE IF NOT EXISTS pages (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  slug VARCHAR(120) UNIQUE NOT NULL,
  title VARCHAR(160) NOT NULL,
  body TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO pages (slug, title, body) VALUES
  ('gizlilik','Gizlilik','Gizlilik Politikası (taslak)'),
  ('kvkk','KVKK','KVKK Aydınlatma Metni (taslak)'),
  ('sartlar','Şartlar','Kullanım Şartları (taslak)')
ON DUPLICATE KEY UPDATE title=VALUES(title);
SQL

gc_cli_log "Applying default seeds…"
PROJECT_ROOT="$PROJECT_ROOT_DIR" "$ROOT_DIR/src/cli/db-import.sh" --service "$SERVICE" --compose "$COMPOSE_FILE" --file "$SEED_FILE" -y
gc_cli_log "Seed complete."
