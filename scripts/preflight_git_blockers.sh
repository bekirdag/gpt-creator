#!/usr/bin/env bash
set -euo pipefail

# 1) Conflicts → blocked-merge-conflict
log_conflict_hint() {
  printf '[git-preflight] %s\n' "$*" >&2
}

conflict_index_output="$(git ls-files -u || true)"
if [[ -n "$conflict_index_output" ]]; then
  first_conflict_path="$(printf '%s\n' "$conflict_index_output" | cut -f4- | head -n1)"
  if [[ -n "${first_conflict_path:-}" ]]; then
    log_conflict_hint "Merge markers present in index for ${first_conflict_path}"
  else
    log_conflict_hint "Merge markers present in index (unable to resolve path)"
  fi
  echo blocked-merge-conflict
  exit 3
fi
first_reject="$(find . -type f -name '*.rej' -print -quit || true)"
if [[ -n "$first_reject" ]]; then
  log_conflict_hint "Found unresolved patch reject file ${first_reject#./}"
  echo blocked-merge-conflict
  exit 3
fi
# Grep only tracked files (excluding common vendor caches) for conflict markers
conflict_excludes=(
  ':(exclude)node_modules/**'
  ':(exclude).pnpm/**'
  ':(exclude)vendor/**'
)
if [[ -n "${GC_CONFLICT_EXCLUDE_PATHS:-}" ]]; then
  IFS=':' read -ra _gc_conflict_extra <<< "${GC_CONFLICT_EXCLUDE_PATHS}"
  for extra in "${_gc_conflict_extra[@]}"; do
    [[ -n "$extra" ]] || continue
    conflict_excludes+=(":(exclude)${extra}")
  done
  unset _gc_conflict_extra
fi
declare -a conflict_pathspecs=()
if ((${#conflict_excludes[@]})); then
  conflict_pathspecs+=(-- "${conflict_excludes[@]}")
fi
conflict_marker_file=""
while IFS= read -r -d '' tracked_file; do
  if grep -nE '^(<<<<<<<|=======|>>>>>>>)' --color=never -- "$tracked_file" >/dev/null 2>&1; then
    conflict_marker_file="$tracked_file"
    break
  fi
done < <(git ls-files -z "${conflict_pathspecs[@]}")
if [[ -n "$conflict_marker_file" ]]; then
  log_conflict_hint "Detected conflict markers (<<<<<<<) in ${conflict_marker_file}"
  echo blocked-merge-conflict
  exit 3
fi

# 2) Dirty working tree → blocked-dirty-tree
# (untracked respected via .gitignore; anything still showing is "dirty")
if [[ -n "$(git status --porcelain=v1)" ]]; then
  echo blocked-dirty-tree
  exit 2
fi

echo ok
