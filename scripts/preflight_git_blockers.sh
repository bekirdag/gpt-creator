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
# Grep only tracked files for conflict markers
if git ls-files -z | xargs -0 grep -nE '^(<<<<<<<|=======|>>>>>>>)' --color=never >/dev/null 2>&1; then
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
