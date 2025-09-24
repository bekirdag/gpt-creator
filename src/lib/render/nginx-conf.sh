#!/usr/bin/env bash
# nginx-conf.sh — generate Nginx configuration for reverse proxy
# Configures reverse proxy for the API, frontend, and admin components.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  die "constants.sh not found"
fi

generate_nginx_conf() {
  local output_file="$1"
  mkdir -p "$(dirname "$output_file")"
  # Basic reverse proxy configuration for Nginx
  echo "Generating Nginx configuration → $output_file"
  codex_call "generate-nginx-conf" "" "$output_file"
}

# Usage: generate_nginx_conf <output-file>
