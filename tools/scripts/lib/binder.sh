#!/usr/bin/env bash
# Binder helpers and CLI integration.

gc_parse_duration_seconds() {
  local value="${1:-}"
  local default="${2:-0}"
  if [[ -z "$value" ]]; then
    echo "$default"
    return
  fi
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$value"
    return
  fi
  if [[ "$value" =~ ^([0-9]+)([smhd])$ ]]; then
    local number="${BASH_REMATCH[1]}"
    local unit="${BASH_REMATCH[2]}"
    case "$unit" in
      s) echo "$number" ;;
      m) echo $((number * 60)) ;;
      h) echo $((number * 3600)) ;;
      d) echo $((number * 86400)) ;;
      *) echo "$default" ;;
    esac
    return
  fi
  echo "$default"
}

gc_parse_size_bytes() {
  local value="${1:-}"
  local default="${2:-0}"
  if [[ -z "$value" ]]; then
    echo "$default"
    return
  fi
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "$value"
    return
  fi
  if [[ "$value" =~ ^([0-9]+)([KMG]B?|[kmg]b?)$ ]]; then
    local number="${BASH_REMATCH[1]}"
    local unit="${BASH_REMATCH[2],,}"
    case "$unit" in
      kb|k) echo $((number * 1024)) ;;
      mb|m) echo $((number * 1024 * 1024)) ;;
      gb|g) echo $((number * 1024 * 1024 * 1024)) ;;
      *) echo "$default" ;;
    esac
    return
  fi
  echo "$default"
}

gc_binder_clear_story() {
  local project_root="${1:?project root required}"
  local epic_slug="${2:-}"
  local story_slug="${3:-}"
  local helper_path
  helper_path="$(gc_clone_python_tool "task_binder.py" "$project_root")" || return 1
  python3 "$helper_path" clear --project "$project_root" --epic "$epic_slug" --story "$story_slug"
}

cmd_binder() {
  local action="${1:-}"
  if [[ -z "$action" || "$action" == "-h" || "$action" == "--help" ]]; then
    gc_render_template "help/binder_usage.txt"
    return 0
  fi
  shift || true
  case "$action" in
    clear)
      local project="${PROJECT_ROOT:-$PWD}"
      local epic=""
      local story=""
      local task=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --project|-p)
            project="$(abs_path "${2:?project path required}")"
            shift 2
            ;;
          --story)
            story="${2:?story slug required}"
            shift 2
            ;;
          --epic)
            epic="${2:-}"
            shift 2
            ;;
          --task)
            task="${2:-}"
            shift 2
            ;;
          -h|--help)
            gc_render_template "help/binder_clear_usage.txt"
            return 0
            ;;
          --)
            shift
            break
            ;;
          *)
            die "Unknown option for binder clear: $1"
            ;;
        esac
      done
      [[ -n "$story" ]] || die "--story is required for binder clear"
      local helper_path
      helper_path="$(gc_clone_python_tool "task_binder.py" "$project")" || return 1
      if [[ -n "$task" ]]; then
        python3 "$helper_path" clear --project "$project" --epic "${epic:-$story}" --story "$story" --task "$task"
      else
        python3 "$helper_path" clear --project "$project" --epic "${epic:-$story}" --story "$story"
      fi
      ;;
    *)
      die "Unknown binder subcommand: ${action}"
      ;;
  esac
}
