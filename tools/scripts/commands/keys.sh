#!/usr/bin/env bash
# shellcheck shell=bash

cmd_keys() {
  local action="${1:-list}"
  case "$action" in
    list|status)
      shift || true
      if (($#)); then
        die "keys ${action} does not take additional arguments"
      fi
      gc_api_keys_list
      ;;
    set)
      shift || true
      local target="${1:-}"
      [[ -n "$target" ]] || die "keys set requires a service name or environment variable"
      gc_api_keys_set "$target"
      ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd keys)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/keys_usage.txt"
        fi
        return 0
        ;;
    *)
      if (($# > 1)); then
        die "Unknown keys action: $*"
      fi
      gc_api_keys_set "$action"
      ;;
  esac
}
