#!/usr/bin/env bash
# Template rendering/copy helpers shared across commands.

if [[ -n "${GC_LIB_TEMPLATES_SH:-}" ]]; then
  return 0
fi
GC_LIB_TEMPLATES_SH=1

copy_template_tree() {
  local src="${1:?source template dir required}"
  local dst="${2:?destination path required}"
  if [[ ! -d "$src" ]]; then
    die "Template source not found: ${src}"
  fi
  mkdir -p "$dst"
  (cd "$src" && tar -cf - .) | (cd "$dst" && tar -xf -)
}
