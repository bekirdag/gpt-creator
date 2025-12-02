#!/usr/bin/env bash
# Help metadata loader.

if [[ -n "${GC_LIB_HELP_SH:-}" ]]; then
  return 0
fi
GC_LIB_HELP_SH=1

gc_help_template_for_cmd() {
  local cmd="${1:-}"
  [[ -n "$cmd" ]] || return 1
  local index_file="${CLI_ROOT:-$PWD}/assets/templates/help/templates_index.json"
  [[ -f "$index_file" ]] || return 1
  local tmpl=""
  tmpl="$(python3 - "$cmd" "$index_file" <<'PY'
import json, sys, pathlib
cmd = sys.argv[1]
index_path = pathlib.Path(sys.argv[2])
data = json.loads(index_path.read_text())
for entry in data:
    if entry.get("command") == cmd:
        print(entry.get("template",""))
        sys.exit(0)
sys.exit(1)
PY
)" || tmpl=""
  if [[ -n "$tmpl" && -f "$tmpl" ]]; then
    printf '%s\n' "$tmpl"
    return 0
  fi
  return 1
}
