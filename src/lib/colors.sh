#!/usr/bin/env bash
# shellcheck shell=bash
# colors.sh — minimal ANSI color helpers (auto‑disable on non‑TTY or NO_COLOR)
# Usage:
#   source "${BASH_SOURCE[0]%/*}/colors.sh"
#   echo -e "${CLR_GREEN}ok${CLR_RESET}" or color::wrap "$CLR_BOLD$CLR_BLUE" "text"
#   Set NO_COLOR=1 to disable.

if [[ -n "${_GPTC_COLORS_SOURCED:-}" ]]; then
  return 0
fi
_GPTC_COLORS_SOURCED=1

# Detect color support
_gptc_color_enabled=0
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  # Respect TERM color capability where available
  if command -v tput >/dev/null 2>&1; then
    if [[ $(tput colors 2>/dev/null || echo 0) -ge 8 ]]; then
      _gptc_color_enabled=1
    fi
  else
    _gptc_color_enabled=1
  fi
fi

if [[ "$_gptc_color_enabled" -eq 1 ]]; then
  CLR_RESET=$'\e[0m'
  CLR_BOLD=$'\e[1m'
  CLR_DIM=$'\e[2m'
  CLR_ITALIC=$'\e[3m'
  CLR_UNDER=$'\e[4m'

  CLR_BLACK=$'\e[30m'
  CLR_RED=$'\e[31m'
  CLR_GREEN=$'\e[32m'
  CLR_YELLOW=$'\e[33m'
  CLR_BLUE=$'\e[34m'
  CLR_MAGENTA=$'\e[35m'
  CLR_CYAN=$'\e[36m'
  CLR_WHITE=$'\e[37m'

  CLR_BBLACK=$'\e[90m'   # bright/gray
  CLR_BRED=$'\e[91m'
  CLR_BGREEN=$'\e[92m'
  CLR_BYELLOW=$'\e[93m'
  CLR_BBLUE=$'\e[94m'
  CLR_BMAGENTA=$'\e[95m'
  CLR_BCYAN=$'\e[96m'
  CLR_BWHITE=$'\e[97m'
else
  CLR_RESET=""; CLR_BOLD=""; CLR_DIM=""; CLR_ITALIC=""; CLR_UNDER=""
  CLR_BLACK=""; CLR_RED=""; CLR_GREEN=""; CLR_YELLOW=""; CLR_BLUE=""; CLR_MAGENTA=""; CLR_CYAN=""; CLR_WHITE=""
  CLR_BBLACK=""; CLR_BRED=""; CLR_BGREEN=""; CLR_BYELLOW=""; CLR_BBLUE=""; CLR_BMAGENTA=""; CLR_BCYAN=""; CLR_BWHITE=""
fi

# Helper to wrap text with arbitrary style sequences
#   color::wrap "<style sequences>" "text"
color::wrap() {
  local style="${1:-}"; shift || true
  printf "%s%s%s" "$style" "$*" "$CLR_RESET"
}
