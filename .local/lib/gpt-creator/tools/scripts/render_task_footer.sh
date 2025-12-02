#!/usr/bin/env bash

# Only enforce strict mode when executed directly, not when sourced.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
fi

# File descriptor (default stderr) to emit pretty footer panels to.
: "${GC_FOOTER_FD:=2}"
# Set to 1 to force footer rendering even when the FD is not a TTY.
: "${GC_FORCE_FOOTER:=0}"

# Prefer stderr (or a caller supplied FD) when deciding if we should render the
# pretty footer panel; this keeps the footer visible when stdout is piped.
gc_footer_is_tty() {
  if [[ "${GC_FORCE_FOOTER}" == "1" ]]; then
    return 0
  fi
  local fd="${GC_FOOTER_FD:-2}"
  [[ -t "$fd" ]]
}

render_task_end() {
  local task_id="${1:-unknown}"
  local status="${2:-UNKNOWN}"
  local project_root="${GC_GIT_DIR:-${PROJECT_ROOT:-$PWD}}"
  local dev_branch="${GC_GIT_DEV_BRANCH:-dev}"
  local branch="${GC_GIT_CURRENT_TASK_BRANCH:-}"
  local repo_ok=0
  if git -C "$project_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    repo_ok=1
    if [[ -z "$branch" ]]; then
      branch="$(git -C "$project_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
    fi
  fi
  local head_sha="n/a"
  local base_sha="n/a"
  local change_count="0"
  local upstream="none"
  if (( repo_ok )); then
    head_sha="$(git -C "$project_root" rev-parse --short HEAD 2>/dev/null || echo "n/a")"
    if [[ -n "$branch" ]]; then
      upstream="$(git -C "$project_root" rev-parse --abbrev-ref --symbolic-full-name "${branch}@\{u\}" 2>/dev/null || echo "none")"
    else
      upstream="$(git -C "$project_root" rev-parse --abbrev-ref --symbolic-full-name HEAD@\{u\} 2>/dev/null || echo "none")"
    fi
  fi
  local state_file="${project_root}/.gpt-creator/state/git-last.json"
  local merge_result="n/a"
  local git_state_helper=""
  if declare -F gc_clone_python_tool >/dev/null 2>&1; then
    git_state_helper="$(gc_clone_python_tool "git_last_state.py" "${PROJECT_ROOT:-$PWD}")" || git_state_helper=""
  fi
  if [[ -z "$git_state_helper" ]]; then
    local helper_root="${CLI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
    local scripts_root="${GC_SCRIPTS_ROOT:-${helper_root}/scripts}"
    if [[ -n "$helper_root" && -f "${scripts_root}/python/git_last_state.py" ]]; then
      git_state_helper="${scripts_root}/python/git_last_state.py"
    fi
  fi
  if [[ -n "$git_state_helper" && -f "$state_file" ]]; then
    while IFS='=' read -r key value; do
      case "$key" in
        branch) [[ -n "$value" ]] && branch="$value" ;;
        merge) merge_result="${value:-$merge_result}" ;;
        head) [[ -n "$value" ]] && head_sha="$value" ;;
        base) [[ -n "$value" ]] && base_sha="$value" ;;
        changed) [[ -n "$value" ]] && change_count="$value" ;;
      esac
    done < <(python3 "$git_state_helper" "$state_file" 2>/dev/null)
    [[ -z "$merge_result" ]] && merge_result="n/a"
  fi
  local git_log="${GC_GIT_LOG:-${project_root}/.gpt-creator/logs/git/$(date -u +%Y%m%d).log}"

  local footer_fd=""
  if gc_footer_is_tty; then
    footer_fd="${GC_FOOTER_FD:-2}"
  fi

  local block
  block="$(cat <<EOF
+==========================================================+
|                    END OF TASK REPORT                    |
+==========================================================+
  [#] Task:        ${task_id}
  [=] Status:      ${status}
  [B] Task branch: ${branch:-none}
  [U] Tracking:    ${upstream}
  [M] Merge->${dev_branch}: ${merge_result}
  [H] HEAD:        ${head_sha}
  [Δ] Files:       ${change_count}
  [↘] Base:        ${base_sha}

  Artifacts:
    - History   : ${GC_ACTIVE_TASK_OUTPUT:-n/a}
    - Git log   : ${git_log}
EOF
)"

  if [[ -n "$footer_fd" ]]; then
    printf '%s\n' "$block" >&"$footer_fd" || true
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  render_task_end "$@"
fi
