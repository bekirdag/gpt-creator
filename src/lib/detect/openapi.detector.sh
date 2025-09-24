#!/usr/bin/env bash
# openapi.detector.sh — detect OpenAPI specification files (YAML/JSON)
# Detects OpenAPI specs in YAML or JSON format based on content or file extension.
if [[ -n "${GC_LIB_OPENAPI_DETECTOR_SH:-}" ]]; then return 0; fi
GC_LIB_OPENAPI_DETECTOR_SH=1

detect_openapi() {
  local file="$1"
  if [[ -f "$file" && "$file" =~ (openapi|swagger) && "$file" =~ .*\.(yaml|yml|json)$ ]]; then
    echo "OpenAPI detected: $file"
  fi
}

# Usage: detect_openapi "/path/to/file.yaml"
