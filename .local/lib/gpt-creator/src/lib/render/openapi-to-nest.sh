#!/usr/bin/env bash
# openapi-to-nest.sh — generate NestJS controllers/services from OpenAPI
# Parse OpenAPI to generate NestJS routes, DTOs, and services.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  die "constants.sh not found"
fi

generate_nest_from_openapi() {
  local openapi="$1"
  local output_dir="$2"
  [[ -f "$openapi" ]] || die "OpenAPI spec not found: $openapi"
  mkdir -p "$output_dir"
  # Codex or OpenAPI Generator can be used for scaffolding here
  # This is a placeholder for future code generation
  echo "Generating NestJS code from OpenAPI: $openapi → $output_dir"
  codex_call "generate-nest" "$openapi" "$output_dir"
}

# Usage: generate_nest_from_openapi <openapi-file> <output-dir>
