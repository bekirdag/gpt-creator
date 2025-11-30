#!/usr/bin/env bash
# Merges the working gc/auto/* branch back into the default branch, pushes, and cleans.

set -Eeuo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$root" ]]; then
  echo "[finalize] not inside a git repository." >&2
  exit 2
fi
cd "$root"

git config user.name  "${GC_GIT_AUTHOR_NAME:-gpt-creator}"
git config user.email "${GC_GIT_AUTHOR_EMAIL:-gpt-creator@local}"
git config commit.gpgsign "${GC_GIT_SIGN:-false}"

detect_default() {
  git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's@^origin/@@' || echo main
}
DEFAULT_BRANCH="${GC_DEFAULT_BRANCH:-$(detect_default)}"

CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CUR_BRANCH" =~ ^gc/auto/ ]]; then
  SAFE_BRANCH="$CUR_BRANCH"
else
  SAFE_BRANCH="${GC_SAFE_BRANCH:-$CUR_BRANCH}"
fi

IFS=: read -r -a EXCLUDES <<< "${GC_PATCH_EXCLUDES:-apps/**/dist-tests/*:.gpt-creator/tmp/*}"

touch .gitignore
ign_changed=0
for pat in "${EXCLUDES[@]}"; do
  [[ -n "$pat" ]] || continue
  if ! grep -qxF "$pat" .gitignore; then
    echo "$pat" >> .gitignore
    ign_changed=1
  fi
done
if (( ign_changed )); then
  git add .gitignore
  git commit -m "chore(gpt-creator): ignore generated artifacts" --no-verify || true
fi

git fetch origin --prune

if git rev-parse --verify "origin/${DEFAULT_BRANCH}" >/dev/null 2>&1; then
  default_ref="origin/${DEFAULT_BRANCH}"
else
  default_ref="$DEFAULT_BRANCH"
fi

if git diff --quiet --exit-code "${default_ref}"...HEAD; then
  echo "[finalize] no changes to merge."
  exit 0
fi

git switch "$SAFE_BRANCH"

for pat in "${EXCLUDES[@]}"; do
  [[ -n "$pat" ]] || continue
  git ls-files -- "$pat" | xargs -r git rm -r --cached --
done
if ! git diff --cached --quiet; then
  git commit -m "chore(gpt-creator): drop generated artifacts" --no-verify
fi

if git rev-parse --verify "$default_ref" >/dev/null 2>&1; then
  if ! git rebase -X ours "$default_ref"; then
    git rebase --abort || true
    git merge --no-edit -X ours "$default_ref" || true
  fi
fi

git switch "$DEFAULT_BRANCH"
git reset --hard "$default_ref"
if ! git merge --no-edit -X theirs "$SAFE_BRANCH"; then
  git merge --squash "$SAFE_BRANCH"
  git commit -m "chore(gpt-creator): squash merge from $SAFE_BRANCH" --no-verify
fi

for _ in 1 2 3; do
  if git push origin "$DEFAULT_BRANCH"; then
    break
  fi
  git fetch origin --prune
  git pull --rebase || true
done

git push origin --delete "$SAFE_BRANCH" 2>/dev/null || true
git branch -D "$SAFE_BRANCH" 2>/dev/null || true
git switch "$DEFAULT_BRANCH"
git reset --hard "$default_ref"
git clean -fdx

echo "[finalize] merged ${SAFE_BRANCH} → ${DEFAULT_BRANCH}, pushed, and cleaned."
