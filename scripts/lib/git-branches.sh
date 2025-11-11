#!/usr/bin/env bash
set -euo pipefail

: "${GC_GIT_BRANCHING:=1}"                 # 1=on, 0=off
: "${GC_GIT_REMOTE:=origin}"
: "${GC_GIT_DEV_BRANCH:=dev}"
: "${GC_GIT_MAIN_BRANCH:=main}"            # fallback if origin/HEAD missing

_gc_git() { git -c advice.detachedHead=false "$@"; }
gc_git_repo_root() { _gc_git rev-parse --show-toplevel 2>/dev/null || echo ""; }
gc_git_sanitize_branch() {
  tr "[:upper:]" "[:lower:]" | sed -E "s/[^a-z0-9]+/-/g; s/^-+|-+$//g; s/-{2,}/-/g" | cut -c1-48
}
gc_git_branch_exists() { _gc_git show-ref --verify --quiet "refs/heads/$1"; }
gc_git_remote_branch_exists() { _gc_git ls-remote --exit-code --heads "$GC_GIT_REMOTE" "$1" >/dev/null 2>&1; }
gc_git_checkout() { _gc_git checkout -q "$1"; }
gc_git_create_from() { _gc_git checkout -q -B "$2" "$1"; }
gc_git_safe_commit_all() {
  if [ -n "$(_gc_git status --porcelain)" ]; then
    _gc_git add -A
    _gc_git commit -q -m "$1" || true
  fi
}
gc_git_push_set_upstream() { _gc_git push -u "$GC_GIT_REMOTE" "$1" >/dev/null 2>&1 || _gc_git push -u "$GC_GIT_REMOTE" "$1"; }
gc_git_merge_ff_only() { _gc_git merge --ff-only "$1"; }
gc_git_merge_no_ff() { _gc_git merge --no-ff -q --no-edit "$1" || return 1; }

gc_git_branching_init() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 0
  local root; root="$(gc_git_repo_root)"; [ -n "$root" ] || { echo "[git] not a git repo; branching disabled" >&2; return 0; }
  _gc_git fetch -q "$GC_GIT_REMOTE" --prune || true
  local base_ref; base_ref="$GC_GIT_MAIN_BRANCH"
  # Prefer remote HEAD if available
  if _gc_git symbolic-ref -q refs/remotes/"$GC_GIT_REMOTE"/HEAD >/dev/null 2>&1; then
    base_ref="$(_gc_git symbolic-ref -q --short refs/remotes/"$GC_GIT_REMOTE"/HEAD | cut -d/ -f2)"
  fi
  # Ensure dev branch exists, create from base if missing
  if ! gc_git_branch_exists "$GC_GIT_DEV_BRANCH"; then
    if gc_git_remote_branch_exists "$GC_GIT_DEV_BRANCH"; then
      _gc_git checkout -q -t "$GC_GIT_REMOTE/$GC_GIT_DEV_BRANCH"
    else
      gc_git_create_from "$base_ref" "$GC_GIT_DEV_BRANCH"
      gc_git_push_set_upstream "$GC_GIT_DEV_BRANCH" || true
    fi
  else
    gc_git_checkout "$GC_GIT_DEV_BRANCH"
    # Fast-forward dev to remote if possible
    _gc_git pull --ff-only "$GC_GIT_REMOTE" "$GC_GIT_DEV_BRANCH" >/dev/null 2>&1 || true
  fi
}

# Exports GC_GIT_CURRENT_TASK_BRANCH
gc_git_begin_task_branch() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 0
  local task_id="$1"
  local slug="task/$(printf "%s" "$task_id" | gc_git_sanitize_branch)"
  export GC_GIT_CURRENT_TASK_BRANCH="$slug"
  if gc_git_branch_exists "$slug"; then
    gc_git_checkout "$slug"
  else
    gc_git_checkout "$GC_GIT_DEV_BRANCH"
    gc_git_create_from "$GC_GIT_DEV_BRANCH" "$slug"
  fi
  mkdir -p .gpt-creator/state && printf "%s\n" "$slug" > .gpt-creator/state/current-branch
}

# args: <task_id> <status> <reason-file?>
gc_git_finalize_task_branch() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 0
  local task_id="$1"; local status="$2"; local reason_file="${3:-}"
  local msg="gpt-creator: task ${task_id} → ${status}"
  if [ -n "$reason_file" ] && [ -f "$reason_file" ]; then
    local reason; reason="$(tr -d "\0" < "$reason_file" | head -c 500)"
    msg="${msg} — ${reason}"
  fi
  gc_git_safe_commit_all "$msg"
  if [ -n "${GC_GIT_CURRENT_TASK_BRANCH:-}" ]; then
    gc_git_push_set_upstream "${GC_GIT_CURRENT_TASK_BRANCH:-}" || true
  fi
  # Merge on success-like terminal states only
  case "$status" in
    SUCCESS|COMPLETED|COMPLETED_OK|COMPLETED_NO_CHANGES)
      gc_git_checkout "$GC_GIT_DEV_BRANCH"
      _gc_git pull --ff-only "$GC_GIT_REMOTE" "$GC_GIT_DEV_BRANCH" >/dev/null 2>&1 || true
      gc_git_merge_no_ff "${GC_GIT_CURRENT_TASK_BRANCH:-}" || { echo "[git] merge failed; leaving branch unmerged" >&2; return 0; }
      _gc_git push "$GC_GIT_REMOTE" "$GC_GIT_DEV_BRANCH" || true
      ;;
    *) : ;; # leave feature branch as-is for follow-up
  esac
  gc_git_checkout "$GC_GIT_DEV_BRANCH"
}
