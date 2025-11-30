#!/usr/bin/env bash
# shellcheck shell=bash

# Thin wrapper that sources the actual renderer implementation for reuse/import.
if [[ -z "${GC_RENDER_GPT_CREATOR_IMPL_SOURCED:-}" ]]; then
  GC_RENDER_GPT_CREATOR_IMPL_SOURCED=1
  # shellcheck source=scripts/render_gpt_creator_impl.sh
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/render_gpt_creator_impl.sh"
fi

# Forward stdin to the original main entrypoint if run directly.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  render_gpt_creator_main "$@"
fi
