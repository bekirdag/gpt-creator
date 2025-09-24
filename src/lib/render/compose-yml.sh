#!/usr/bin/env bash
# compose-yml.sh — generate Docker Compose YAML configuration for the project
# Set up services for the API, database, and frontend components.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  die "constants.sh not found"
fi

generate_compose_yml() {
  local output_file="$1"
  mkdir -p "$(dirname "$output_file")"
  # Generate a basic Docker Compose YAML file (for API, DB, Web)
  echo "Generating Docker Compose configuration → $output_file"
  codex_call "generate-docker-compose" "" "$output_file"
}

# Usage: generate_compose_yml <output-file>
