#!/usr/bin/env bash
# shellcheck shell=bash
# log.sh — structured logging with levels + colors
# Levels: DEBUG < INFO < WARN < ERROR
#   export GPTC_LOG_LEVEL=INFO   # default
#   export NO_COLOR=1            # disable ANSI

if [[ -n "${_GPTC_LOG_SOURCED:-}" ]]; then
  return 0
fi
_GPTC_LOG_SOURCED=1

# shellcheck disable=SC1091
source "${BASH_SOURCE[0]%/*}/colors.sh"
source "${BASH_SOURCE[0]%/*}/term.sh"

: "${GPTC_LOG_LEVEL:=INFO}"

_log_level_num() {
  case "$1" in
    DEBUG) echo 10;;
    INFO)  echo 20;;
    WARN)  echo 30;;
    ERROR) echo 40;;
    *)     echo 20;;
  esac
}

_log_enabled() {
  local want="$1"
  [[ $(_log_level_num "$want") -ge $(_log_level_num "$GPTC_LOG_LEVEL") ]]
}

# Timestamp (ISO‑8601-ish)
_log_ts() {
  date +"%Y-%m-%dT%H:%M:%S%z"
}

# Core printer
#   _log <LEVEL> <emoji> <color> <message...>
_log() {
  local lvl="$1"; shift
  local emoji="$1"; shift
  local color="$1"; shift
  local ts; ts="$(_log_ts)"
  printf "%s %b%s%-5s%b %s\n" "$ts" "$color" "$emoji " "$lvl" "$CLR_RESET" "$*"
}

log::set_level() { GPTC_LOG_LEVEL="${1:-INFO}"; }

log::debug() { _log_enabled DEBUG && _log DEBUG "·" "$CLR_DIM" "$*"; }
log::info()  { _log_enabled INFO  && _log INFO  "ℹ" "$CLR_BBLUE" "$*"; }
log::warn()  { _log_enabled WARN  && _log WARN  "!" "$CLR_BYELLOW" "$*"; }
log::error() { _log_enabled ERROR && _log ERROR "✖" "$CLR_BRED" "$*"; }
log::ok()    { _log_enabled INFO  && _log INFO  "✔" "$CLR_BGREEN" "$*"; }

# Horizontal rule (fills terminal width)
log::hr() {
  local cols; cols="$(term::cols)"
  printf "%${cols}s" "" | tr " " "─"
  printf "\n"
}

# Prompt (yes/no). Returns 0 for yes, 1 for no.
#   log::confirm "Proceed?" [default=y|n]
log::confirm() {
  local msg="${1:-Proceed?}" def="${2:-y}" ans
  local prompt="[y/N]"; [[ "$def" =~ ^[Yy]$ ]] && prompt="[Y/n]"
  printf "%s %s " "$(color::wrap "$CLR_BOLD" "$msg")" "$prompt"
  read -r ans || true
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[Yy]$ ]]
}
