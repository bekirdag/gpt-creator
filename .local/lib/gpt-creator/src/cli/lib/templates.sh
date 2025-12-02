#!/usr/bin/env bash

# Utility helpers for rendering templates without inline heredocs.
# Expected environment:
#   GC_TEMPLATE_ROOT   — absolute path to assets/templates (required)
#
# Additional environment variables can be exported/set prior to rendering and
# will be interpolated using Python's string.Template safe substitution.

gc_cli_require_template_runtime() {
  if [[ -z "${GC_TEMPLATE_ROOT:-}" ]]; then
    echo "[templates] GC_TEMPLATE_ROOT not set" >&2
    return 1
  fi
  if ! command -v "${PYTHON_BIN:-python3}" >/dev/null 2>&1; then
    echo "[templates] python runtime '${PYTHON_BIN:-python3}' not found" >&2
    return 1
  fi
}

gc_cli_template_path() {
  local rel="${1:?template relative path required}"
  printf '%s/%s' "${GC_TEMPLATE_ROOT}" "$rel"
}

gc_cli_render_template() {
  local rel="${1:?template relative path required}"
  gc_cli_require_template_runtime || return 1
  local template_path
  template_path="$(gc_cli_template_path "$rel")"
  if [[ ! -f "$template_path" ]]; then
    echo "[templates] template missing: ${template_path}" >&2
    return 1
  fi
  "${PYTHON_BIN:-python3}" -c 'import os, sys
from string import Template

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = fh.read()
tmpl = Template(data)
sys.stdout.write(tmpl.safe_substitute(os.environ))' "$template_path"
}

gc_cli_json_escape() {
  local value="${1:-}"
  gc_cli_require_template_runtime || return 1
  "${PYTHON_BIN:-python3}" -c 'import json, sys
print(json.dumps(sys.argv[1]))' "$value"
}

