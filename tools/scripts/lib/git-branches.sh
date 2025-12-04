#!/usr/bin/env bash
set -euo pipefail

: "${GC_GIT_BRANCHING:=1}"
: "${GC_GIT_REMOTE:=origin}"
: "${GC_GIT_DEV_BRANCH:=dev}"
: "${GC_GIT_MAIN_BRANCH:=main}"
: "${GC_GIT_TASK_PREFIX:=}"
: "${GC_GIT_AUTOMATION_AUTHOR_NAME:=gpt-creator automation}"
: "${GC_GIT_AUTOMATION_AUTHOR_EMAIL:=automation@gpt-creator}"
: "${GC_GIT_BRANCHING_LOG_VERSION:=v20251202-2}"

gc_git_state_dir() {
  local root
  root="$(gc_git_repo_root)"
  [[ -n "$root" ]] || return 1
  printf '%s/.gpt-creator/state\n' "$root"
}

_gc_git() {
  local git_dir="${GC_GIT_DIR:-${PROJECT_ROOT:-$PWD}}"
  git -C "$git_dir" -c advice.detachedHead=false "$@"
}

gc_git_repo_root() {
  local git_dir="${GC_GIT_DIR:-${PROJECT_ROOT:-$PWD}}"
  git -C "$git_dir" rev-parse --show-toplevel 2>/dev/null || echo ""
}

gc_git_sanitize_branch() {
  tr "[:upper:]" "[:lower:]" | sed -E "s/[^a-z0-9]+/-/g; s/^-+|-+$//g; s/-{2,}/-/g" | cut -c1-48
}

gc_git_branch_exists() { _gc_git show-ref --verify --quiet "refs/heads/$1" >/dev/null 2>&1; }
gc_git_remote_branch_exists() { _gc_git ls-remote --exit-code --heads "$GC_GIT_REMOTE" "$1" >/dev/null 2>&1; }
gc_git_checkout() { _gc_git checkout -q "$1"; }
gc_git_create_from() { _gc_git checkout -q -B "$2" "$1"; }
gc_git_current_branch() { _gc_git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""; }
gc_git_has_changes() { [[ -n "$(_gc_git status --porcelain 2>/dev/null)" ]]; }

gc_git_dirty_preview() {
  _gc_git status --porcelain=v1 2>/dev/null | head -n 20 | tr $'\n' ';' | sed 's/;*$//'
}

gc_git_commit_with_identity() {
  local message="${1:-}"
  shift || true
  GIT_TERMINAL_PROMPT=0 \
  GIT_COMMIT_GPGSIGN=0 \
  GIT_AUTHOR_NAME="${GC_GIT_AUTOMATION_AUTHOR_NAME}" \
  GIT_AUTHOR_EMAIL="${GC_GIT_AUTOMATION_AUTHOR_EMAIL}" \
  GIT_COMMITTER_NAME="${GC_GIT_AUTOMATION_AUTHOR_NAME}" \
  GIT_COMMITTER_EMAIL="${GC_GIT_AUTOMATION_AUTHOR_EMAIL}" \
    _gc_git commit --no-verify --no-gpg-sign "$@" -m "$message"
}

gc_git_log() {
  local msg="$*"
  local root="${GC_GIT_DIR:-${PROJECT_ROOT:-$PWD}}"
  local log_path="${GC_GIT_LOG:-${root}/.gpt-creator/logs/git/$(date -u +%Y%m%d).log}"
  mkdir -p "$(dirname "$log_path")" 2>/dev/null || true
  printf "%s %s\n" "$(date -u +%FT%TZ)" "$msg" | tee -a "$log_path" >&2
  echo "gpt-creator:     Note: Action: git/log | Result: $msg" >&2
}

gc_git_autosnap() {
  # Capture pending edits before any branch switch to avoid checkout failures.
  local context="${1:-branch switch}"
  gc_git_has_changes || { gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap skip — tree already clean (${context})"; return 0; }
  local dirty_preview
  dirty_preview="$(gc_git_dirty_preview)"
  gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap start (${context}); dirty preview: ${dirty_preview:-<unknown>}"
  local ts head msg
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  msg="chore(gpt-creator): autosnap before ${context} ${ts}"
  if ! _gc_git add -A >/dev/null 2>&1; then
    gc_git_log "[git] autosnap staging failed; working tree still dirty"
    return 1
  fi
  if _gc_git diff --cached --quiet >/dev/null 2>&1; then
    return 0
  fi
  if gc_git_commit_with_identity "$msg" -q; then
    head="$(gc_git_current_branch)"
    local sha
    sha="$(_gc_git rev-parse --short HEAD 2>/dev/null || true)"
    gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap commit recorded on ${head:-HEAD} ${sha:+[$sha]} (${context})"
    gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap post-commit dirty preview (${context}): $(gc_git_dirty_preview)"
  else
    gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap commit failed; leaving tree dirty (${context})"
    return 1
  fi
  if gc_git_has_changes; then
    gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap warning — working tree still dirty after commit (${context})"
    return 1
  fi
  return 0
}

gc_git_push_set_upstream() {
  local branch="${1:-}"
  [[ -n "$branch" ]] || return 0
  gc_git_log "[git] pushing ${branch} to ${GC_GIT_REMOTE} (set-upstream)"
  if _gc_git push -u "$GC_GIT_REMOTE" "$branch" >/dev/null 2>&1; then
    gc_git_log "[git] push/upstream ok → ${branch}"
    return 0
  fi
  gc_git_log "[git] push failed silently; retrying with verbose output"
  if _gc_git push -u "$GC_GIT_REMOTE" "$branch"; then
    gc_git_log "[git] push/upstream ok → ${branch}"
    return 0
  fi
  gc_git_log "[git] push still failing; fetching ${branch} from ${GC_GIT_REMOTE} before rebase"
  _gc_git fetch -q "$GC_GIT_REMOTE" "$branch" >/dev/null 2>&1 || true
  _gc_git rebase "$GC_GIT_REMOTE/$branch" >/dev/null 2>&1 || true
  if _gc_git push -u "$GC_GIT_REMOTE" "$branch" >/dev/null 2>&1; then
    gc_git_log "[git] push/upstream ok (post-rebase) → ${branch}"
    return 0
  fi
  gc_git_log "[git] push still failing; force pushing with lease"
  if _gc_git push --force-with-lease -u "$GC_GIT_REMOTE" "$branch"; then
    gc_git_log "[git] force push (with lease) → ${branch}"
    return 0
  fi
  gc_git_log "[git] push failed for ${branch}"
  return 1
}

gc_git_merge_no_ff() {
  _gc_git merge --no-ff -q --no-edit "$1" >/dev/null 2>&1
}

gc_git_status_ok() {
  local s
  s="$(printf "%s" "${1:-}" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"
  case "$s" in
    SUCCESS|COMPLETE|COMPLETED|COMPLETED_OK|COMPLETED_NO_CHANGES|READY_TO_REVIEW|READY_TO_REVIEW_NO_CHANGES) return 0 ;;
    *) return 1 ;;
  esac
}

gc_git_branching_init() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 0
  local root; root="$(gc_git_repo_root)"; [ -n "$root" ] || { gc_git_log "[git] not a git repo; branching disabled"; return 0; }
  gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] git-branches helper loaded (branching=${GC_GIT_BRANCHING})"
  gc_git_log "[git] syncing remote refs from ${GC_GIT_REMOTE} before dev branch init"
  if _gc_git fetch -q "$GC_GIT_REMOTE" --prune >/dev/null 2>&1; then
    gc_git_log "[git] remote refs fetched from ${GC_GIT_REMOTE}"
  else
    gc_git_log "[git] remote fetch failed; continuing with local refs"
  fi
  gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] autosnap before dev branch preparation (if dirty)"
  gc_git_autosnap "dev branch init" || true
  local base_ref="$GC_GIT_MAIN_BRANCH"
  if _gc_git symbolic-ref -q refs/remotes/"$GC_GIT_REMOTE"/HEAD >/dev/null 2>&1; then
    base_ref="$(_gc_git symbolic-ref -q --short refs/remotes/"$GC_GIT_REMOTE"/HEAD | cut -d/ -f2)"
  fi
  if ! gc_git_branch_exists "$GC_GIT_DEV_BRANCH"; then
    if gc_git_remote_branch_exists "$GC_GIT_DEV_BRANCH"; then
      gc_git_log "[git] tracking ${GC_GIT_REMOTE}/${GC_GIT_DEV_BRANCH} locally"
      _gc_git checkout -q -t "$GC_GIT_REMOTE/$GC_GIT_DEV_BRANCH" >/dev/null 2>&1 || true
    else
      gc_git_log "[git] creating local ${GC_GIT_DEV_BRANCH} from ${base_ref}"
      if ! gc_git_create_from "$base_ref" "$GC_GIT_DEV_BRANCH"; then
        gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] failed to create ${GC_GIT_DEV_BRANCH} from ${base_ref}; aborting git branching init"
        return 1
      fi
      gc_git_push_set_upstream "$GC_GIT_DEV_BRANCH" || true
    fi
  fi
  local current_branch
  current_branch="$(gc_git_current_branch)"
  gc_git_log "[git] pre-switch autosnap if dirty"
  gc_git_autosnap "dev branch checkout" || true
  if ! gc_git_checkout "$GC_GIT_DEV_BRANCH"; then
    local dirty_dev_checkout
    dirty_dev_checkout="$(gc_git_dirty_preview)"
    gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${GC_GIT_DEV_BRANCH} failed; dirty preview: ${dirty_dev_checkout:-<unknown>}; attempting autosnap + retry"
    gc_git_autosnap "retry ${GC_GIT_DEV_BRANCH} checkout" || true
    if ! gc_git_checkout "$GC_GIT_DEV_BRANCH"; then
      gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${GC_GIT_DEV_BRANCH} still failing; leaving working tree as-is"
      return 1
    fi
  fi
  _gc_git pull --ff-only "$GC_GIT_REMOTE" "$GC_GIT_DEV_BRANCH" >/dev/null 2>&1 || true
  local dev_head
  dev_head="$(_gc_git rev-parse --short HEAD 2>/dev/null || echo "")"
  gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] ready on ${GC_GIT_DEV_BRANCH} ${dev_head:+[$dev_head]}"
}

gc_git_begin_task_branch() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 0
  local root; root="$(gc_git_repo_root)"; [ -n "$root" ] || return 0
  local task_id="${1:-}"
  local id slug candidate
  id="$(printf "%s" "$task_id" | gc_git_sanitize_branch)"
  [[ -n "$id" ]] || id="task"
  candidate="$id"
  slug="${GC_GIT_TASK_PREFIX}${id}"
  gc_git_log "[git] autosnap before task branch switch (if dirty)"
  gc_git_autosnap "task branch switch" || true
  if gc_git_remote_branch_exists "$candidate" || gc_git_branch_exists "$candidate"; then
    slug="$candidate"
  fi
  export GC_GIT_CURRENT_TASK_BRANCH="$slug"
  gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] task branch intent=${slug} current=$(gc_git_current_branch) root=${root}"
  if gc_git_branch_exists "$slug"; then
    local dirty_before_checkout
    dirty_before_checkout="$(gc_git_dirty_preview)"
    gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] reusing existing branch ${slug}; dirty preview before checkout: ${dirty_before_checkout:-<unknown>}"
    gc_git_log "[git] autosnap before checkout of ${slug}"
    gc_git_autosnap "reuse ${slug}" || true
    if gc_git_checkout "$slug"; then
      gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${slug} ok after autosnap"
    else
      local dirty_on_failure
      dirty_on_failure="$(gc_git_dirty_preview)"
      gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${slug} failed; dirty preview: ${dirty_on_failure:-<unknown>}; attempting autosnap + retry"
      gc_git_autosnap "retry checkout ${slug}" || true
      if ! gc_git_checkout "$slug"; then
        local dirty_retry_failure
        dirty_retry_failure="$(gc_git_dirty_preview)"
        gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${slug} still failing after autosnap; dirty preview: ${dirty_retry_failure:-<unknown>}; leaving working tree as-is"
        return 1
      else
        gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${slug} succeeded after retry autosnap; dirty preview: $(gc_git_dirty_preview)"
      fi
    fi
  else
    gc_git_log "[git] creating branch ${slug} from ${GC_GIT_DEV_BRANCH}"
    gc_git_log "[git] autosnap before creating ${slug}"
    gc_git_autosnap "create ${slug}" || true
    if ! gc_git_checkout "$GC_GIT_DEV_BRANCH"; then
      gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] checkout ${GC_GIT_DEV_BRANCH} failed before creating ${slug}; dirty preview: $(gc_git_dirty_preview)"
      return 1
    fi
    if ! gc_git_create_from "$GC_GIT_DEV_BRANCH" "$slug"; then
      gc_git_log "[git][${GC_GIT_BRANCHING_LOG_VERSION}] failed to create ${slug} from ${GC_GIT_DEV_BRANCH}; leaving working tree unchanged"
      return 1
    fi
    gc_git_log "[git] created branch ${slug} from ${GC_GIT_DEV_BRANCH}"
  fi
  gc_git_log "[git] begin branch ${slug} ← ${GC_GIT_DEV_BRANCH}"
  local state_dir base_file
  state_dir="$(gc_git_state_dir 2>/dev/null || printf '%s/.gpt-creator/state' "$root")"
  mkdir -p "$state_dir" 2>/dev/null || true
  printf "%s\n" "$slug" > "${state_dir}/current-branch"
  base_file="${state_dir}/base-sha"
  local branch_base
  branch_base="$(_gc_git rev-parse HEAD 2>/dev/null | tr -d '[:space:]')"
  printf "%s\n" "$branch_base" >"$base_file" 2>/dev/null || true
  if [[ -n "$branch_base" ]]; then
    gc_git_log "[git] recorded baseline ${branch_base} for ${slug}"
  fi
  return 0
}

gc_git_finalize_task_branch() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 0
  local root; root="$(gc_git_repo_root)"; [ -n "$root" ] || return 0
  local task_id="${1:-unknown}"
  local status="${2:-UNKNOWN}"
  local reason_file="${3:-}"
  local message="gpt-creator: task ${task_id} → ${status}"
  if [[ -n "$reason_file" && -f "$reason_file" ]]; then
    local reason
    reason="$(tr -d '\0' <"$reason_file" | head -c 500)"
    [[ -n "$reason" ]] && message="${message} — ${reason}"
  fi

  if gc_git_has_changes; then
    gc_git_log "[git] staging and committing ${task_id} updates"
    _gc_git add -A >/dev/null 2>&1 || true
    if gc_git_commit_with_identity "$message" -q; then
      gc_git_log "[git] commit: ${message}"
    else
      gc_git_log "[git] commit failed for ${task_id}; leaving tree dirty"
    fi
  else
    gc_git_log "[git] no local changes to commit for ${task_id}"
  fi

  if [[ -n "${GC_GIT_CURRENT_TASK_BRANCH:-}" ]]; then
    gc_git_log "[git] pushing ${GC_GIT_CURRENT_TASK_BRANCH} upstream"
    gc_git_push_set_upstream "$GC_GIT_CURRENT_TASK_BRANCH" || true
  fi

  local merge_result="skipped"
  local state_dir base_file base_sha head_sha changed_count="0" commit_count="0"
  state_dir="$(gc_git_state_dir 2>/dev/null || printf '%s/.gpt-creator/state' "$root")"
  base_file="${state_dir}/base-sha"
  if [[ -f "$base_file" ]]; then
    base_sha="$(tr -d '[:space:]' <"$base_file")"
  fi
  head_sha="$(_gc_git rev-parse HEAD 2>/dev/null || echo "")"
  if [[ -n "$base_sha" && -n "$head_sha" ]]; then
    changed_count="$(_gc_git diff --name-only "$base_sha" "$head_sha" 2>/dev/null | sed '/^$/d' | wc -l | tr -d '[:space:]')"
    [[ -n "$changed_count" ]] || changed_count="0"
    commit_count="$(_gc_git rev-list --count "$base_sha..$head_sha" 2>/dev/null | tr -d '[:space:]')"
    [[ -n "$commit_count" ]] || commit_count="0"
  fi
  export GC_LAST_BRANCH_CHANGED="${changed_count}"
  gc_git_log "[git] files changed since task start: ${changed_count} (commits since start: ${commit_count})"

  local should_merge=0
  if gc_git_status_ok "$status"; then
    should_merge=1
  fi
  if (( should_merge )) && [[ -n "${GC_GIT_CURRENT_TASK_BRANCH:-}" ]]; then
    gc_git_checkout "$GC_GIT_DEV_BRANCH"
    _gc_git pull --ff-only "$GC_GIT_REMOTE" "$GC_GIT_DEV_BRANCH" >/dev/null 2>&1 || true
    gc_git_log "[git] merging ${GC_GIT_CURRENT_TASK_BRANCH} into ${GC_GIT_DEV_BRANCH}"
    if gc_git_merge_no_ff "${GC_GIT_CURRENT_TASK_BRANCH}"; then
      if _gc_git push "$GC_GIT_REMOTE" "$GC_GIT_DEV_BRANCH" >/dev/null 2>&1; then
        gc_git_log "[git] merged ${GC_GIT_CURRENT_TASK_BRANCH} → ${GC_GIT_DEV_BRANCH} and pushed update"
      else
        gc_git_log "[git] merged ${GC_GIT_CURRENT_TASK_BRANCH} → ${GC_GIT_DEV_BRANCH} but push failed"
      fi
      merge_result="ok"
    else
      gc_git_log "[git] merge failed; leaving branch unmerged"
      merge_result="failed"
    fi
  else
    if [[ "${changed_count:-0}" =~ ^[0-9]+$ ]] && (( changed_count == 0 )) && [[ "${commit_count:-0}" =~ ^[0-9]+$ ]] && (( commit_count == 0 )); then
      merge_result="skipped-no-changes"
    fi
  fi

  printf '{"branch":"%s","merge":"%s","base":"%s","head":"%s","changed":%s,"commits":%s}\n' \
    "${GC_GIT_CURRENT_TASK_BRANCH:-}" "$merge_result" "${base_sha:-}" "${head_sha:-}" "${changed_count:-0}" "${commit_count:-0}" \
    > "${state_dir}/git-last.json" 2>/dev/null || true
  gc_git_checkout "$GC_GIT_DEV_BRANCH"
}

gc_git_changes_since_task_branch() {
  [ "$GC_GIT_BRANCHING" = "1" ] || return 1
  local root; root="$(gc_git_repo_root)"; [ -n "$root" ] || return 1
  local base_file="${root}/.gpt-creator/state/base-sha"
  [[ -f "$base_file" ]] || return 1
  local base_sha
  base_sha="$(tr -d '[:space:]' <"$base_file")"
  [[ -n "$base_sha" ]] || return 1
  local head_sha
  head_sha="$(_gc_git rev-parse HEAD 2>/dev/null || echo "")"
  [[ -n "$head_sha" ]] || return 1
  local count
  count="$(_gc_git diff --name-only "$base_sha" "$head_sha" 2>/dev/null | sed '/^$/d' | wc -l | tr -d '[:space:]')"
  [[ -n "$count" ]] || count="0"
  printf '%s\n' "$count"
}
