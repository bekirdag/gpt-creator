#!/usr/bin/env bash
# shellcheck shell=bash
# spinner.sh — lightweight TTY spinner
# Usage:
#   source spinner.sh
#   spinner::start "Doing work..."
#   <do stuff>
#   spinner::stop ok   # or 'fail'

# shellcheck disable=SC1091
source "${BASH_SOURCE[0]%/*}/colors.sh"
source "${BASH_SOURCE[0]%/*}/term.sh"

if [[ -n "${_GPTC_SPINNER_SOURCED:-}" ]]; then
  return 0
fi
_GPTC_SPINNER_SOURCED=1

_GPTC_SPINNER_PID=""
_GPTC_SPINNER_MSG=""
_GPTC_SPINNER_FRAMES=( "⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏" )

spinner::start() {
  _GPTC_SPINNER_MSG="${1:-Working}"
  if ! term::is_tty; then
    printf "%s ...\n" "$_GPTC_SPINNER_MSG"
    return 0
  fi
  term::cursor_hide
  (
    trap 'exit 0' TERM
    local i=0
    while :; do
      local f="${_GPTC_SPINNER_FRAMES[i % ${#_GPTC_SPINNER_FRAMES[@]}]}"
      printf "\r%s %s" "$f" "$_GPTC_SPINNER_MSG"
      term::clear_eol
      ((i++))
      sleep 0.08
    done
  ) &
  _GPTC_SPINNER_PID=$!
  disown "$_GPTC_SPINNER_PID" 2>/dev/null || true
}

spinner::update() {
  _GPTC_SPINNER_MSG="$*"
}

spinner::stop() {
  local status="${1:-ok}"
  if [[ -n "$_GPTC_SPINNER_PID" ]] && kill -0 "$_GPTC_SPINNER_PID" 2>/dev/null; then
    kill -TERM "$_GPTC_SPINNER_PID" 2>/dev/null || true
    wait "$_GPTC_SPINNER_PID" 2>/dev/null || true
  fi
  _GPTC_SPINNER_PID=""
  if term::is_tty; then
    local icon color msg="$_GPTC_SPINNER_MSG"
    case "$status" in
      ok|success)   icon="✔"; color="$CLR_BGREEN";;
      warn|warning) icon="!"; color="$CLR_BYELLOW";;
      *)            icon="✖"; color="$CLR_BRED";;
    esac
    printf "\r%b%s%b %s\n" "$color" "$icon" "$CLR_RESET" "$msg"
    term::cursor_show
  else
    printf "%s: %s\n" "$status" "$_GPTC_SPINNER_MSG"
  fi
}
