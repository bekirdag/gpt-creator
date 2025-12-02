#!/usr/bin/env bash
# verify/check-openapi.sh — validate an OpenAPI spec via swagger-cli or openapi-generator
set -Eeuo pipefail

SPEC="${1:-openapi.yaml}"

# If spec not found, try to discover
if [[ ! -f "$SPEC" ]]; then
  SPEC="$( (git ls-files '**/openapi.@(yaml|yml|json)' 2>/dev/null || true;             find . -maxdepth 3 -type f \( -name 'openapi.yaml' -o -name 'openapi.yml' -o -name 'openapi.json' \) ) | head -n1)"
fi

[[ -n "$SPEC" && -f "$SPEC" ]] || { echo "OpenAPI spec not found."; exit 2; }

echo "Validating: $SPEC"

if command -v npx >/dev/null 2>&1; then
  npx -y @apidevtools/swagger-cli@4.0.4 validate "$SPEC"
  echo "✅ OpenAPI is valid (swagger-cli)."
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$PWD":/local openapitools/openapi-generator-cli:v7.7.0 validate -i "/local/${SPEC#./}"
  echo "✅ OpenAPI is valid (openapi-generator)."
  exit 0
fi

echo "⚠️  Neither npx nor docker method available. Install Node or Docker to validate."
exit 3
