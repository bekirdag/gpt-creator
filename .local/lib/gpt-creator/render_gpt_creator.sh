#!/usr/bin/env bash
# shellcheck shell=bash

# Thin wrapper that sources the actual renderer implementation for reuse/import.
if [[ -z "${GC_RENDER_GPT_CREATOR_IMPL_SOURCED:-}" ]]; then
  GC_RENDER_GPT_CREATOR_IMPL_SOURCED=1
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  scripts_root="${GC_SCRIPTS_ROOT:-${repo_root}/tools/scripts}"
  if [[ ! -d "$scripts_root" ]]; then
    scripts_root="${repo_root}/scripts"
  fi
  # shellcheck source=scripts/render_gpt_creator_impl.sh
  . "${scripts_root}/render_gpt_creator_impl.sh"
fi

# Forward stdin to the original main entrypoint if run directly.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  render_gpt_creator_main "$@"
fi
