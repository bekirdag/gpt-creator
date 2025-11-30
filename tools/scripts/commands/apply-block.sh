#!/usr/bin/env bash
# shellcheck shell=bash

cmd_apply_block() {
  local helper="${CLI_ROOT}/bin/gpt-creator-apply-block.js"
  if [[ ! -f "$helper" ]]; then
    die "apply-block helper missing at ${helper}"
  fi
  if ! command -v node >/dev/null 2>&1; then
    die "node is required to run gpt-creator apply-block"
  fi
  node "$helper" "$@"
}
