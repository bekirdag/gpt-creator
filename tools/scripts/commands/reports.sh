#!/usr/bin/env bash
# shellcheck shell=bash

cmd_reports() {
  local root=""
  local mode="list"
  local slug=""
  local open_editor=0
  local work_branch=""
  local push_after=1
  local prompt_only=0
  local reporter_filter=""
  local close_invalid=0
  local close_comment="Authenticity failed (automated by gpt-creator reports audit)."
  local close_comment_set=0
  local include_closed=0
  local audit_limit=""
  local audit_limit_set=0
  local digests_path=""
  local digests_path_set=0
  local invalid_label=""
  local invalid_label_set=0
  local allow_pairs=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      list)
        mode="list"
        shift
        ;;
      backlog)
        mode="backlog"
        shift
        ;;
      auto)
        mode="auto"
        shift
        ;;
      audit)
        mode="audit"
        shift
        ;;
      work)
        mode="work"
        shift
        if [[ $# -eq 0 ]]; then
          die "reports work requires a slug identifier"
        fi
        slug="$1"
        shift
        ;;
      show)
        mode="show"
        shift
        if [[ $# -eq 0 ]]; then
          die "reports show requires a slug identifier"
        fi
        slug="$1"
        shift
        ;;
      --project)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --open)
        open_editor=1
        shift
        ;;
      --branch)
        work_branch="$2"
        shift 2
        ;;
      --no-push)
        push_after=0
        shift
        ;;
      --push)
        push_after=1
        shift
        ;;
      --prompt-only)
        prompt_only=1
        shift
        ;;
      --reporter)
        reporter_filter="$2"
        shift 2
        ;;
      --close-invalid)
        close_invalid=1
        shift
        ;;
      --no-close-invalid)
        close_invalid=0
        shift
        ;;
      --comment)
        close_comment="${2:?--comment requires text}"
        close_comment_set=1
        shift 2
        ;;
      --include-closed)
        include_closed=1
        shift
        ;;
      --limit)
        audit_limit="${2:?--limit requires a positive integer}"
        audit_limit_set=1
        shift 2
        ;;
      --digests)
        digests_path="${2:?--digests requires a file path}"
        digests_path_set=1
        shift 2
        ;;
      --allow)
        allow_pairs+=("${2:?--allow requires VERSION=SHA256}")
        shift 2
        ;;
      --label-invalid)
        invalid_label="${2:?--label-invalid requires a value}"
        invalid_label_set=1
        shift 2
        ;;
      --no-label-invalid)
        invalid_label=""
        invalid_label_set=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd reports)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/reports_usage.txt"
        fi
        return 0
        ;;
      *)
        if [[ -z "$slug" && "$mode" == "list" ]]; then
          mode="show"
          slug="$1"
          shift
        else
          die "Unknown reports argument: $1"
        fi
        ;;
    esac
  done

  if [[ "$mode" == "show" && -z "$slug" ]]; then
    die "reports show requires a slug identifier"
  fi

  if [[ "$mode" == "work" && -z "$slug" ]]; then
    die "reports work requires a slug identifier"
  fi

  if [[ "$mode" == "work" && "$open_editor" -ne 0 ]]; then
    die "--open cannot be combined with reports work"
  fi

  if [[ "$mode" == "auto" && "$open_editor" -ne 0 ]]; then
    die "--open cannot be combined with reports auto"
  fi

  if [[ "$mode" == "auto" && -n "$work_branch" ]]; then
    die "--branch is not supported for reports auto"
  fi

  if [[ "$mode" != "work" && "$mode" != "auto" ]]; then
    if [[ -n "$work_branch" || "$prompt_only" -ne 0 || "$push_after" -ne 1 ]]; then
      die "reports options --branch/--no-push/--prompt-only are only valid with 'work' or 'auto'"
    fi
  fi

  if [[ "$mode" != "auto" && -n "$reporter_filter" ]]; then
    die "--reporter is only supported with reports auto"
  fi

  if [[ -n "$audit_limit" ]]; then
    if [[ ! "$audit_limit" =~ ^[0-9]+$ ]]; then
      die "--limit expects a non-negative integer"
    fi
  fi

  if [[ "$mode" != "audit" ]]; then
    if (( close_invalid != 0 || include_closed != 0 || close_comment_set != 0 || audit_limit_set != 0 || digests_path_set != 0 || invalid_label_set != 0 || ${#allow_pairs[@]} != 0 )); then
      die "reports options --close-invalid/--include-closed/--limit/--digests/--allow/--label-invalid/--comment are only valid with 'audit'"
    fi
  fi

  local pair_entry
  for pair_entry in "${allow_pairs[@]}"; do
    if [[ ! "$pair_entry" =~ ^[^=]+=[0-9a-fA-F]{64}$ ]]; then
      die "--allow expects VERSION=SHA256 (got '${pair_entry}')"
    fi
  done

  if [[ "$mode" != "audit" ]]; then
    if [[ -n "$root" ]]; then
      ensure_ctx "$root"
    else
      ensure_ctx "${PROJECT_ROOT:-$PWD}"
    fi
  elif [[ -n "$root" ]]; then
    ensure_ctx "$root"
  fi

  local reports_dir=""
  if [[ "$mode" != "audit" ]]; then
    reports_dir="$(gc_reports_dir)" || die "Unable to access issue report directory"
  fi

  case "$mode" in
    audit)
      local repo="${GC_GITHUB_REPO:-}"
      local token="${GC_GITHUB_TOKEN:-}"
      if [[ -z "$repo" || -z "$token" ]]; then
        die "reports audit requires GC_GITHUB_REPO and GC_GITHUB_TOKEN to be set"
      fi
      local state="open"
      if (( include_closed )); then
        state="all"
      fi
      if [[ -z "$digests_path" ]]; then
        if [[ -n "${GC_REPORT_DIGESTS_PATH:-}" ]]; then
          digests_path="${GC_REPORT_DIGESTS_PATH}"
        elif [[ -n "${CLI_ROOT:-}" && -f "${CLI_ROOT}/config/release-digests.json" ]]; then
          digests_path="${CLI_ROOT}/config/release-digests.json"
        fi
      fi
      local allow_join=""
      if ((${#allow_pairs[@]} > 0)); then
        allow_join="$(printf '%s\n' "${allow_pairs[@]}")"
      fi
      local github_audit_helper
      github_audit_helper="$(gc_clone_python_tool "github_audit_auto_reports.py" "${PROJECT_ROOT:-$PWD}")" || github_audit_helper=""
      if [[ -n "$github_audit_helper" ]]; then
        "$python_bin" "$github_audit_helper" "$repo" "$token" "$state" "$close_invalid" "$close_comment" "$audit_limit" "$digests_path" "$invalid_label" "$allow_join"
      else
        warn "GitHub audit helper unavailable; skipping auto-report audit."
      fi
      return
      ;;
    list|backlog)
      if [[ -z "$(find "$reports_dir" -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) -print -quit 2>/dev/null)" ]]; then
        info "No issue reports recorded yet."
        return 0
      fi
      local reports_summary_helper
      reports_summary_helper="$(gc_clone_python_tool "reports_summarize.py" "${PROJECT_ROOT:-$PWD}")" || reports_summary_helper=""
      if [[ -n "$reports_summary_helper" ]]; then
        "$python_bin" "$reports_summary_helper" "$reports_dir" "$mode"
      else
        warn "Reports summary helper unavailable; skipping report summary."
      fi
      ;;
    auto)
      local reporter="${reporter_filter:-$(gc_reports_current_user)}"
      info "Auto-processing reports for reporter: ${reporter}"
      local auto_slugs=()
      local reports_list_helper
      reports_list_helper="$(gc_clone_python_tool "reports_list_by_reporter.py" "${PROJECT_ROOT:-$PWD}")" || reports_list_helper=""
      if [[ -n "$reports_list_helper" ]]; then
        while IFS= read -r slug_entry; do
          [[ -n "$slug_entry" ]] && auto_slugs+=("$slug_entry")
        done < <("$python_bin" "$reports_list_helper" "$reports_dir" "$reporter")
      fi
      if ((${#auto_slugs[@]} == 0)); then
        info "No matching reports for reporter '${reporter}'."
        return 0
      fi
      local slug_entry
      for slug_entry in "${auto_slugs[@]}"; do
        info "Resolving report ${slug_entry}"
        if ! gc_reports_run_work "$slug_entry" "" "$push_after" "$prompt_only" "$reporter"; then
          die "Codex failed while processing report ${slug_entry}"
        fi
      done
      ;;
    show)
      local report_path=""
      if ! report_path="$(gc_reports_resolve_slug "$slug")"; then
        die "No issue report found for slug: ${slug}"
      fi
      info "Report file: ${report_path}"
      printf '\n'
      cat "$report_path"
      printf '\n'
      if (( open_editor )); then
        local editor_cmd="${EDITOR_CMD:-${EDITOR:-vi}}"
        if [[ -z "$editor_cmd" ]]; then
          warn "EDITOR_CMD not set; skipping --open"
        else
          info "Opening report in ${editor_cmd}"
          if ! bash -lc "${editor_cmd} \"${report_path}\""; then
            warn "Failed to launch editor command: ${editor_cmd}"
          fi
        fi
      fi
      ;;
    work)
      if ! gc_reports_run_work "$slug" "$work_branch" "$push_after" "$prompt_only" ""; then
        die "Codex failed to resolve report ${slug}"
      fi
      ;;
  esac
}
