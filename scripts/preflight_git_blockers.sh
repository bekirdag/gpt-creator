#!/usr/bin/env bash
set -euo pipefail

# 1) Conflicts → blocked-merge-conflict
if [[ -n "$(git ls-files -u || true)" ]]; then
  echo blocked-merge-conflict
  exit 3
fi
if find . -type f -name '*.rej' -print -quit | grep -q .; then
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
if git ls-files -z "${conflict_pathspecs[@]}" | xargs -0 --no-run-if-empty grep -nE '^(<<<<<<<|=======|>>>>>>>)' --color=never >/dev/null 2>&1; then
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
