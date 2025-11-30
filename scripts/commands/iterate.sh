#!/usr/bin/env bash
# shellcheck shell=bash

cmd_iterate() {
  warn "'iterate' is deprecated; prefer 'gpt-creator create-tasks' followed by 'gpt-creator work-on-tasks'."

  local root="" jira=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      --jira) jira="$(abs_path "$2")"; shift 2;;
      --no-verify) shift;;
      --verify) shift;;
      *) break;;
    esac
  done
  ensure_ctx "$root"
  [[ -n "$jira" ]] || jira="${INPUT_DIR}/jira.md"
  [[ -f "$jira" ]] || die "Jira tasks file not found: ${jira}"

  local tasks_json_local="${PLAN_DIR}/jira-tasks.local.json"
  gc_parse_jira_tasks "$jira" "$tasks_json_local"
  ok "Parsed Jira tasks → ${tasks_json_local}"
  local tasks_json="${tasks_json_local}"

  local codex_parse_prompt="${PLAN_DIR}/iterate-codex-parse.md"
  local codex_raw_json="${PLAN_DIR}/jira-tasks.codex.raw.txt"
  local codex_json="${PLAN_DIR}/jira-tasks.codex.json"
  {
    gc_render_template "prompts/iterate_parse_prefix.md" >"$codex_parse_prompt"
    cat "$jira" >>"$codex_parse_prompt"
    printf '\n' >>"$codex_parse_prompt"
    gc_render_template "prompts/iterate_parse_suffix.md" >>"$codex_parse_prompt"
  }
