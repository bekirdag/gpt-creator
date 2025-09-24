#!/usr/bin/env bash
# openapi-to-client.sh — generate API client from OpenAPI
# Parse OpenAPI and generate typed client (JavaScript/TypeScript) for frontend.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  die "constants.sh not found"
fi

generate_client_from_openapi() {
  local openapi="$1"
  local output_dir="$2"
  [[ -f "$openapi" ]] || die "OpenAPI spec not found: $openapi"
  mkdir -p "$output_dir"
  # This could use tools like OpenAPI Generator, or a Codex-based solution
  echo "Generating client from OpenAPI: $openapi → $output_dir"
  codex_call "generate-client" "$openapi" "$output_dir"
}

# Usage: generate_client_from_openapi <openapi-file> <output-dir>
