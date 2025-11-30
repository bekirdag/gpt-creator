#!/usr/bin/env bash
# shellcheck shell=bash

cmd_dag() {
  local root="" action="" story=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|-p)
        root="$(abs_path "$2")"
        shift 2
        ;;
      validate)
        action="validate"
        shift
        break
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd dag)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/dag_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown argument for dag: $1"
        ;;
    esac
  done

  [[ -n "$action" ]] || die "dag requires a subcommand (e.g. 'dag validate')"
  ensure_ctx "$root"

  case "$action" in
    validate)
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --story)
            story="$2"
            shift 2
            ;;
          --help|-h)
        if tmpl="$(gc_help_template_for_cmd dag)"; then
          gc_render_template "${tmpl}"
        else
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd dag)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/dag_validate_usage.txt"
        fi
        return 0
        ;;
          *)
            die "Unknown argument for dag validate: $1"
            ;;
        esac
      done
      local dag_helper
      dag_helper="$(gc_clone_python_tool "dag_inspect.py" "${PROJECT_ROOT:-$PWD}")" || return 1
      if [[ -n "$story" ]]; then
        python3 "$dag_helper" validate --project-root "${PROJECT_ROOT:-$PWD}" --story "$story"
      else
        python3 "$dag_helper" validate --project-root "${PROJECT_ROOT:-$PWD}"
      fi
      ;;
    *)
      die "Unknown dag subcommand: ${action}"
      ;;
  esac
}

