#!/usr/bin/env bash
# openapi.parse.sh — parse OpenAPI specification for structured information (used in gpt-creator)

if [[ -n "${GC_LIB_OPENAPI_PARSE_SH:-}" ]]; then return 0; fi
GC_LIB_OPENAPI_PARSE_SH=1

# Parse OpenAPI (extract basic info: endpoints, methods, parameters, responses)
parse_openapi() {
  local file="$1"
  [[ -f "$file" ]] || { echo "parse_openapi: file not found: $file" >&2; return 2; }
  python3 -c "import json, sys; data = json.load(sys.stdin); print(json.dumps(data.get('paths', {}), indent=2))" < "$file"
}

# Usage: parse_openapi "openapi.yaml"
