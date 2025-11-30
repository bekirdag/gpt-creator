#!/usr/bin/env bash
# shellcheck shell=bash

cmd_tui() {
  ensure_go_runtime
  local go_bin="${GC_GO_BIN:-${GO_BIN:-go}}"
  if ! command -v "$go_bin" >/dev/null 2>&1; then
    die "Go 1.21+ is required to run the gpt-creator TUI. Automatic setup failed; install Go manually and set GO_BIN."
  fi
  local tui_dir="${CLI_ROOT}/tui"
  if [[ ! -d "$tui_dir" ]]; then
    die "TUI sources not found at ${tui_dir}"
  fi
  local skip_tidy="${GC_SKIP_TUI_TIDY:-}"
  info "Launching gpt-creator TUI (preview)"
  (
    cd "$tui_dir"
    local go_dir_readonly=0
    local readonly_path=""
    if [[ ! -w go.mod ]]; then
      go_dir_readonly=1
      readonly_path="${tui_dir}/go.mod"
    elif [[ -e go.sum && ! -w go.sum ]]; then
      go_dir_readonly=1
      readonly_path="${tui_dir}/go.sum"
    fi
    if [[ -z "$skip_tidy" ]]; then
      if (( go_dir_readonly )); then
        warn "Skipping 'go mod tidy' because ${readonly_path} is not writable"
      else
        info "Ensuring TUI Go modules are tidy"
        if ! "$go_bin" mod tidy >/dev/null 2>&1; then
          warn "'go mod tidy' reported issues; retrying with output"
          if ! "$go_bin" mod tidy; then
            die "Failed to tidy Go modules required for the TUI"
          fi
        fi
      fi
    fi
    if (( go_dir_readonly )) && [[ "${GOFLAGS:-}" != *"-mod="* ]]; then
      export GOFLAGS="${GOFLAGS:+${GOFLAGS} }-mod=readonly"
    fi
    "$go_bin" run . "$@"
  )
}
