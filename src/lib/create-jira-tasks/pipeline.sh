#!/usr/bin/env bash
# shellcheck shell=bash

# Thin wrapper that sources the actual pipeline implementation.
if [[ -z "${CJT_PIPELINE_IMPL_SOURCED:-}" ]]; then
  CJT_PIPELINE_IMPL_SOURCED=1
  # shellcheck source=src/lib/create-jira-tasks/pipeline_impl.sh
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pipeline_impl.sh"
fi
