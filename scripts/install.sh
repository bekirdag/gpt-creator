#!/usr/bin/env bash
# macOS installer for gpt-creator
set -Eeuo pipefail

PREFIX="/usr/local"
SKIP_PREFLIGHT=0
FORCE=0

usage() {
  cat <<EOF
gpt-creator installer (macOS)

Usage:
  ./install.sh [--prefix /usr/local] [--skip-preflight] [--force]

Installs:
  • CLI symlink → \$PREFIX/bin/gpt-creator
  • App files   → \$PREFIX/lib/gpt-creator
  • Shell completions (zsh/bash/fish)

Preflight checks: Docker, Node 20+, pnpm, mysql client, Codex client, OPENAI_API_KEY
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="${2:-/usr/local}"; shift 2 ;;
    --skip-preflight) SKIP_PREFLIGHT=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer targets macOS (Darwin)." >&2; exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
APP_DIR="$PREFIX/lib/gpt-creator"
BIN_DIR="$PREFIX/bin"
APP_BIN="$APP_DIR/bin/gpt-creator"
LINK_PATH="$BIN_DIR/gpt-creator"

need_cmd() { command -v "$1" >/dev/null 2>&1; }
as_root() {
  local target="$1"
  shift
  if [[ -w "$target" ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

ver_major() { echo "${1#v}" | awk -F. '{print $1}'; }

preflight() {
  echo "› Preflight…"
  need_cmd docker || { echo "✖ docker not found. Install Docker Desktop." >&2; exit 1; }
  if ! docker info >/dev/null 2>&1; then
    echo "✖ Docker is installed but not running. Start Docker Desktop." >&2; exit 1;
  fi

  need_cmd node || { echo "✖ node not found. Install Node 20+ (brew install node@20)." >&2; exit 1; }
  local nv; nv="$(node -v)"; local major; major="$(ver_major "$nv")"
  if (( major < 20 )); then echo "✖ Node $nv found; require ≥ v20." >&2; exit 1; fi

  need_cmd pnpm || { echo "✖ pnpm not found. Install via corepack: 'corepack enable && corepack prepare pnpm@latest --activate'." >&2; exit 1; }

  need_cmd mysql || { echo "✖ mysql client not found. Install: 'brew install mysql-client' and ensure it’s on PATH." >&2; exit 1; }

  if ! need_cmd codex && ! need_cmd codex-client; then
    echo "✖ Codex client not found (expected 'codex' or 'codex-client' on PATH)." >&2; exit 1;
  fi

  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "✖ OPENAI_API_KEY not set in env. Export it before running the CLI." >&2; exit 1;
  fi
  echo "✔ Preflight OK."
}

install_files() {
  echo "› Installing files to $APP_DIR …"
  as_root "$PREFIX" mkdir -p "$APP_DIR"
  # Copy only what's needed (bin + templates + scripts + docs); falls back to repo if structure differs.
  rsync -a --delete \
    --include '/bin/' --include '/bin/*' \
    --include '/templates/***' \
    --include '/scripts/***' \
    --include '/docs/***' \
    --include '/README*' \
    --exclude='*' \
    "$REPO_DIR"/ "$APP_DIR"/ || {
      echo "rsync minimal copy failed; copying full repo…"
      as_root "$PREFIX" cp -R "$REPO_DIR"/. "$APP_DIR"/
    }

  # Ensure executable bit set on CLI entrypoint
  if [[ -f "$APP_BIN" ]]; then
    as_root "$PREFIX" chmod +x "$APP_BIN"
  else
    echo "› Copying CLI entrypoint to $APP_BIN"
    as_root "$PREFIX" mkdir -p "$(dirname "$APP_BIN")"
    as_root "$PREFIX" install -m 0755 "$REPO_DIR/bin/gpt-creator" "$APP_BIN"
  fi
}

install_link() {
  echo "› Linking $LINK_PATH → $APP_BIN"
  as_root "$PREFIX" mkdir -p "$BIN_DIR"
  if [[ -L "$LINK_PATH" || -e "$LINK_PATH" ]]; then
    if [[ $FORCE -eq 1 ]]; then as_root "$PREFIX" rm -f "$LINK_PATH"; else
      echo "✖ $LINK_PATH exists. Re-run with --force to replace." >&2; exit 1; fi
  fi
  as_root "$PREFIX" ln -s "$APP_BIN" "$LINK_PATH"
  if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
    echo "⚠ $BIN_DIR is not on PATH. Add: export PATH=\"$BIN_DIR:\$PATH\"" >&2
  fi
}

install_completions() {
  echo "› Installing shell completions…"
  # zsh
  local zcomp
  if need_cmd brew; then
    zcomp="$(brew --prefix)/share/zsh/site-functions"
  else
    zcomp="$PREFIX/share/zsh/site-functions"
  fi
  as_root "$PREFIX" mkdir -p "$zcomp"
  as_root "$PREFIX" tee "$zcomp/_gpt-creator" >/dev/null <<'ZSHC'
#compdef gpt-creator
_arguments -s \
  '1:subcommand:(create-project help)' \
  '2:path:_files -/'
ZSHC

  # bash
  local bdir="$PREFIX/etc/bash_completion.d"
  as_root "$PREFIX" mkdir -p "$bdir"
  as_root "$PREFIX" tee "$bdir/gpt-creator" >/dev/null <<'BASHC'
_gpt_creator_complete() {
  local cur prev
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "create-project help" -- "$cur") )
  elif [[ "${COMP_WORDS[1]}" == "create-project" ]]; then
    COMPREPLY=( $(compgen -o plusdirs -f -- "$cur") )
  fi
}
complete -F _gpt_creator_complete gpt-creator
BASHC

  # fish
  local fdir="${HOME}/.config/fish/completions"
  mkdir -p "$fdir"
  tee "$fdir/gpt-creator.fish" >/dev/null <<'FISHC'
complete -c gpt-creator -n "not __fish_seen_subcommand_from create-project help" -a "create-project help"
complete -c gpt-creator -n "__fish_seen_subcommand_from create-project" -a "(__fish_complete_directories)"
FISHC
}

main() {
  [[ $SKIP_PREFLIGHT -eq 1 ]] || preflight
  install_files
  install_link
  install_completions
  echo "✔ Installed. Try:"
  echo "    gpt-creator create-project /path/to/project"
}

main "$@"
