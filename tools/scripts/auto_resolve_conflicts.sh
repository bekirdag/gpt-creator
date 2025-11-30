#!/usr/bin/env bash
set -euo pipefail

# Auto-resolve merge artifacts (e.g., *.rej, *.orig) by restoring tracked files
# to HEAD and deleting leftover patch files. This favours repository integrity
# over preserving un-applied hunks.

project_root="${1:-.}"
cd "${project_root}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf '[auto-resolve] Not inside a git worktree; skipping cleanup.\n' >&2
  exit 0
fi

declare -a conflict_files=()
while IFS= read -r -d '' path; do
  conflict_files+=("${path}")
done < <(find . -type f \( -name '*.rej' -o -name '*.orig' \) -print0)

if ((${#conflict_files[@]} == 0)); then
  printf '[auto-resolve] No conflict artifacts detected.\n'
  exit 0
fi

strip_artifact_suffix() {
  local path="$1"
  path="${path%.rej}"
  path="${path%.orig}"
  echo "${path}"
}

restore_tracked_file() {
  local target="$1"
  if [[ -z "${target}" || ! -f "${target}" ]]; then
    return
  fi
  if git ls-files --error-unmatch "${target}" >/dev/null 2>&1; then
    git restore --source=HEAD -- "${target}" >/dev/null 2>&1 || true
  fi
}

for artifact in "${conflict_files[@]}"; do
  rel_path="${artifact#./}"
  base_path="$(strip_artifact_suffix "${rel_path}")"
  printf '[auto-resolve] Cleaning artifact %s\n' "${rel_path}"
  restore_tracked_file "${base_path}"
  rm -f -- "${rel_path}"
done

# Remove empty directories left behind (best effort).
find . -type d -empty -delete || true

printf '[auto-resolve] Cleanup complete.\n'
