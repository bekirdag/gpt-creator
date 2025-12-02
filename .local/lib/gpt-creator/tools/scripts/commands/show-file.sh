#!/usr/bin/env bash
# shellcheck shell=bash

cmd_show_file() {
  local project="${PROJECT_ROOT:-$PWD}"
  local target_path=""
  local range_spec="" head_lines="" tail_lines="" refresh=0 diff_mode=0
  local max_lines="${GC_SHOW_FILE_MAX_LINES:-400}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project)
        project="$(abs_path "$2")"
        shift 2
        ;;
      --range)
        if [[ $# -lt 2 ]]; then
          die "--range requires an argument in the form START:END (e.g. 120:160)"
        fi
        local next_range="$2"
        if [[ -z "$next_range" || "$next_range" == --* ]]; then
          die "--range requires an argument in the form START:END (e.g. 120:160)"
        fi
        range_spec="$next_range"
        shift 2
        ;;
      --head)
        if [[ $# -lt 2 ]]; then
          die "--head requires a positive line count"
        fi
        local next_head="$2"
        if [[ -z "$next_head" || "$next_head" == --* ]]; then
          die "--head requires a positive line count"
        fi
        warn "Tip: prefer --range start:end or --tail N for targeted snippets; --head is retained for compatibility."
        head_lines="$next_head"
        shift 2
        ;;
      --tail)
        if [[ $# -lt 2 ]]; then
          die "--tail requires a positive line count"
        fi
        local next_tail="$2"
        if [[ -z "$next_tail" || "$next_tail" == --* ]]; then
          die "--tail requires a positive line count"
        fi
        tail_lines="$next_tail"
        shift 2
        ;;
      --max-lines)
        if [[ $# -lt 2 ]]; then
          die "--max-lines requires a positive line count"
        fi
        local next_max="$2"
        if [[ -z "$next_max" || "$next_max" == --* ]]; then
          die "--max-lines requires a positive line count"
        fi
        max_lines="$next_max"
        shift 2
        ;;
      --refresh|--force)
        refresh=1
        shift
        ;;
      --diff)
        diff_mode=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd show-file)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/show_file_usage.txt"
        fi
        return 0
        ;;
      --)
        shift
        break
        ;;
      -*)
        die "Unknown show-file option: ${1}"
        ;;
      *)
        if [[ -z "$target_path" ]]; then
          target_path="$1"
          shift
        else
          break
        fi
        ;;
    esac
  done

  [[ -n "$target_path" ]] || die "show-file requires a path argument"
  local project_abs
  project_abs="$(abs_path "$project")"
  local resolved_path
  resolved_path="$(abs_path "$target_path")"

  if [[ ! -f "$resolved_path" && "$target_path" != /* ]]; then
    local staging_root
    staging_root="$(abs_path "${project_abs}/.gpt-creator/staging")"
    local staging_candidate="${staging_root}/${target_path#./}"
    staging_candidate="$(abs_path "$staging_candidate")"
    if [[ "$staging_candidate" == "${staging_root}"/* && -f "$staging_candidate" ]]; then
      resolved_path="$staging_candidate"
    fi
  fi

  [[ -f "$resolved_path" ]] || die "File not found: ${target_path}"

  [[ -z "$max_lines" || "$max_lines" =~ ^[0-9]+$ ]] || die "--max-lines must be numeric"
  [[ -z "$head_lines" || "$head_lines" =~ ^[0-9]+$ ]] || die "--head value must be numeric"
  [[ -z "$tail_lines" || "$tail_lines" =~ ^[0-9]+$ ]] || die "--tail value must be numeric"

  local cache_dir="${GC_TMP_DIR:-${project_abs}/.gpt-creator/tmp}/view-cache"
  mkdir -p "$cache_dir"

  local rel_path="$resolved_path"
  if [[ "$resolved_path" == "$project_abs"* ]]; then
    rel_path="${resolved_path#$project_abs/}"
  fi

  local helper_path
  helper_path="$(gc_clone_python_tool "show_file.py" "${PROJECT_ROOT:-$PWD}")" || return 1

  GC_SHOW_FILE_PROJECT="$project_abs" \
  GC_SHOW_FILE_PATH="$resolved_path" \
  GC_SHOW_FILE_REL="$rel_path" \
  GC_SHOW_FILE_RANGE="$range_spec" \
  GC_SHOW_FILE_HEAD="$head_lines" \
  GC_SHOW_FILE_TAIL="$tail_lines" \
  GC_SHOW_FILE_MAX_LINES="$max_lines" \
  GC_SHOW_FILE_REFRESH="$refresh" \
  GC_SHOW_FILE_DIFF="$diff_mode" \
  GC_SHOW_FILE_CACHE_DIR="$cache_dir" \
  python3 "$helper_path"
}
