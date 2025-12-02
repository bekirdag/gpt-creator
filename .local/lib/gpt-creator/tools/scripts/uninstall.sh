#!/usr/bin/env bash
# Uninstall gpt-creator from macOS
set -Eeuo pipefail

PREFIX="/usr/local"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="${2:-/usr/local}"; shift 2 ;;
    -h|--help) echo "Usage: ./uninstall.sh [--prefix /usr/local]"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

APP_DIR="$PREFIX/lib/gpt-creator"
BIN_DIR="$PREFIX/bin"
LINK_PATH="$BIN_DIR/gpt-creator"

as_root() { if [[ -w "$1" ]]; then shift; "$@"; else sudo "$@"; fi; }

echo "› Removing $LINK_PATH"
as_root "$PREFIX" rm -f "$LINK_PATH" || true

echo "› Removing $APP_DIR"
as_root "$PREFIX" rm -rf "$APP_DIR" || true

# Remove completions
echo "› Removing shell completions"
if command -v brew >/dev/null 2>&1; then
  ZCOMP="$(brew --prefix)/share/zsh/site-functions/_gpt-creator"
else
  ZCOMP="$PREFIX/share/zsh/site-functions/_gpt-creator"
fi
BASHC="$PREFIX/etc/bash_completion.d/gpt-creator"
FISHC="${HOME}/.config/fish/completions/gpt-creator.fish"

as_root "$PREFIX" rm -f "$ZCOMP" || true
as_root "$PREFIX" rm -f "$BASHC" || true
rm -f "$FISHC" || true

echo "✔ Uninstalled."
