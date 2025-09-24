#!/usr/bin/env bash
# shellcheck shell=bash
# term.sh — terminal helpers: tty detection, size, cursor, links

if [[ -n "${_GPTC_TERM_SOURCED:-}" ]]; then
  return 0
fi
_GPTC_TERM_SOURCED=1

# Is stdout a TTY?
term::is_tty() {
  [[ -t 1 ]]
}

# Columns / rows (fallbacks: 80x24)
term::cols() {
  if command -v tput >/dev/null 2>&1; then tput cols 2>/dev/null || echo 80; else echo 80; fi
}
term::rows() {
  if command -v tput >/dev/null 2>&1; then tput lines 2>/dev/null || echo 24; else echo 24; fi
}

# Cursor show/hide (no‑ops on non‑TTY)
term::cursor_hide() { term::is_tty && printf "\e[?25l"; }
term::cursor_show() { term::is_tty && printf "\e[?25h"; }

# Clear rest of line
term::clear_eol() { term::is_tty && printf "\e[K"; }

# Truncate with ellipsis to N columns (approximate, plain bytes)
#   term::ellipsis "long text" 60
term::ellipsis() {
  local s="${1:-}" max="${2:-80}"
  local len=${#s}
  (( len <= max )) && { printf "%s" "$s"; return; }
  local cut=$(( max>1 ? max-1 : 1 ))
  printf "%s…" "${s:0:cut}"
}

# Clickable link for supporting terminals (OSC 8); degrades to 'text (url)'
#   term::link "text" "url"
term::link() {
  local text="${1:-}" url="${2:-}"
  if [[ -t 1 ]]; then
    printf "\e]8;;%s\e\\%s\e]8;;\e\\" "$url" "$text"
  else
    printf "%s (%s)" "$text" "$url"
  fi
}
