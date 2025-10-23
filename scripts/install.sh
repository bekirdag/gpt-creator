#!/usr/bin/env bash
# Unix installer for gpt-creator (macOS / Linux)
set -Eeuo pipefail

PREFIX="/usr/local"
SKIP_PREFLIGHT=0
FORCE=0

usage() {
  cat <<EOF
gpt-creator installer (macOS / Linux)

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

OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin)
    INSTALL_MODE="macos"
    ;;
  Linux)
    INSTALL_MODE="linux"
    ;;
  *)
    echo "Unsupported OS: $OS_NAME" >&2
    exit 1
    ;;
esac

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$SCRIPTS_DIR/.." && pwd -P)"
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

INSTALL_WARNINGS=()
NODE_REQUIRED_MAJOR=20
NODE_CURRENT_VERSION=""
APT_UPDATED=0

log_info() { echo "› $1"; }
log_warn() { echo "⚠ $1" >&2; }
record_warning() {
  local msg="$1"
  INSTALL_WARNINGS+=("$msg")
  log_warn "$msg"
}

apt_get_install() {
  command -v apt-get >/dev/null 2>&1 || return 1
  if (( APT_UPDATED == 0 )); then
    if ! as_root "/" apt-get update; then
      return 1
    fi
    APT_UPDATED=1
  fi
  if as_root "/" apt-get install -y "$@"; then
    return 0
  fi
  return 1
}

dnf_install() {
  command -v dnf >/dev/null 2>&1 || return 1
  if as_root "/" dnf install -y "$@"; then
    return 0
  fi
  return 1
}

brew_install() {
  command -v brew >/dev/null 2>&1 || return 1
  if brew install "$@"; then
    return 0
  fi
  return 1
}

node_version_ok() {
  if ! need_cmd node; then
    NODE_CURRENT_VERSION=""
    return 1
  fi
  local nv major
  nv="$(node -v 2>/dev/null || true)"
  NODE_CURRENT_VERSION="$nv"
  [[ -n "$nv" ]] || return 1
  major="$(ver_major "$nv")"
  [[ -n "$major" ]] || return 1
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  if (( major >= NODE_REQUIRED_MAJOR )); then
    return 0
  fi
  return 1
}

ensure_docker() {
  if need_cmd docker; then
    if docker info >/dev/null 2>&1; then
      echo "✔ Docker CLI available."
    else
      record_warning "Docker CLI detected but daemon not reachable. Start Docker Desktop/Engine before running docker-based commands."
    fi
    return 0
  fi

  log_info "Docker CLI not found; attempting automatic install…"
  case "$INSTALL_MODE" in
    macos)
      record_warning "Docker Desktop is not installed. Install it manually from https://www.docker.com/products/docker-desktop/ before running docker-based commands."
      ;;
    linux)
      local installed=0
      if apt_get_install docker.io docker-compose-plugin; then
        installed=1
      elif dnf_install docker docker-compose; then
        installed=1
      elif dnf_install docker-ce docker-compose-plugin; then
        installed=1
      fi
      if (( installed )); then
        if need_cmd systemctl; then
          as_root "/" systemctl enable --now docker >/dev/null 2>&1 || true
        fi
        if need_cmd docker; then
          echo "✔ Docker CLI installed (ensure daemon is running)."
          return 0
        fi
      fi
      record_warning "Docker could not be installed automatically. Install Docker Engine manually via your distribution instructions."
      ;;
    *)
      record_warning "Docker installation is not supported automatically on this platform."
      ;;
  esac
}

ensure_node() {
  if node_version_ok; then
    echo "✔ Node.js ${NODE_CURRENT_VERSION} detected."
    return 0
  fi

  log_info "Node.js ${NODE_REQUIRED_MAJOR}+ not found or outdated; attempting installation…"
  local installed=0
  case "$INSTALL_MODE" in
    macos)
      if command -v brew >/dev/null 2>&1; then
        if brew_install node@20; then
          brew link --overwrite --force node@20 >/dev/null 2>&1 || true
          installed=1
        fi
      else
        record_warning "Homebrew not found; install Node.js ${NODE_REQUIRED_MAJOR}+ manually from https://nodejs.org/."
      fi
      ;;
    linux)
      if command -v apt-get >/dev/null 2>&1; then
        if command -v curl >/dev/null 2>&1; then
          if as_root "/" bash -lc 'curl -fsSL https://deb.nodesource.com/setup_20.x | bash -'; then
            if apt_get_install nodejs; then
              installed=1
            fi
          fi
        fi
        if (( installed == 0 )); then
          if apt_get_install nodejs npm; then
            installed=1
          fi
        fi
      elif command -v dnf >/dev/null 2>&1; then
        if dnf_install nodejs; then
          installed=1
        fi
      fi
      ;;
  esac

  if (( installed )); then
    hash -r
  fi
  if node_version_ok; then
    echo "✔ Node.js ${NODE_CURRENT_VERSION} ready."
    return 0
  fi

  record_warning "Node.js ${NODE_REQUIRED_MAJOR}+ is required. Install it manually (https://nodejs.org/) before running code generation commands."
}

ensure_pnpm() {
  if need_cmd pnpm; then
    echo "✔ pnpm $(pnpm --version 2>/dev/null || true) detected."
    return 0
  fi

  log_info "pnpm not found; attempting activation via corepack/npm…"
  local version="${GC_PNPM_VERSION:-latest}"
  if need_cmd corepack; then
    corepack enable >/dev/null 2>&1 || true
    if corepack prepare "pnpm@${version}" --activate >/dev/null 2>&1; then
      hash -r
      if need_cmd pnpm; then
        echo "✔ pnpm $(pnpm --version 2>/dev/null || true) activated via corepack."
        return 0
      fi
    fi
  fi
  if need_cmd npm; then
    if npm install -g "pnpm@${version}"; then
      hash -r
      if need_cmd pnpm; then
        echo "✔ pnpm $(pnpm --version 2>/dev/null || true) installed globally."
        return 0
      fi
    fi
  fi

  record_warning "pnpm could not be installed automatically. Install it manually via corepack or npm (https://pnpm.io/installation)."
}

ensure_mysql_client() {
  if need_cmd mysql; then
    echo "✔ MySQL client $(mysql --version 2>/dev/null || true) detected."
    return 0
  fi

  log_info "MySQL client (mysql) not found; attempting installation…"
  local installed=0
  case "$INSTALL_MODE" in
    macos)
      if command -v brew >/dev/null 2>&1; then
        if brew_install mysql-client; then
          local prefix
          prefix="$(brew --prefix mysql-client 2>/dev/null || true)"
          if [[ -n "$prefix" && -d "$prefix/bin" ]]; then
            if ! echo ":$PATH:" | grep -q ":$prefix/bin:"; then
              log_warn "Add ${prefix}/bin to PATH (e.g. export PATH=\"${prefix}/bin:\$PATH\") so 'mysql' is available."
            fi
          fi
          installed=1
        fi
      else
        record_warning "Homebrew not found; install the MySQL client manually (e.g. https://dev.mysql.com/downloads/mysql/)."
      fi
      ;;
    linux)
      if apt_get_install mysql-client; then
        installed=1
      elif apt_get_install mariadb-client; then
        installed=1
      elif dnf_install mysql; then
        installed=1
      elif dnf_install mariadb; then
        installed=1
      fi
      ;;
  esac

  if (( installed )); then
    hash -r
    if need_cmd mysql; then
      echo "✔ MySQL client $(mysql --version 2>/dev/null || true) installed."
      return 0
    fi
  fi

  record_warning "MySQL client not installed. Install it manually (package name: mysql-client or mariadb-client)."
}

ensure_codex() {
  if need_cmd codex; then
    echo "✔ Codex CLI detected (codex)."
    return 0
  fi
  if need_cmd codex-client; then
    echo "✔ Codex CLI detected (codex-client)."
    return 0
  fi

  record_warning "Codex CLI not found. Install the Codex CLI or point CODEX_BIN/CODEX_CMD to a compatible binary."
}

ensure_openai_api_key() {
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    echo "✔ OPENAI_API_KEY detected in environment."
    return 0
  fi
  record_warning "OPENAI_API_KEY is not set. Set it before running Codex-powered commands."
}

preflight() {
  echo "› Preflight…"
  ensure_docker
  ensure_node
  ensure_pnpm
  ensure_mysql_client
  ensure_codex
  ensure_openai_api_key
  if (( ${#INSTALL_WARNINGS[@]} > 0 )); then
    echo "⚠ Preflight completed with warnings:"
    for warn in "${INSTALL_WARNINGS[@]}"; do
      echo "   - $warn"
    done
    echo "  Related commands will prompt for the missing tooling when invoked."
  else
    echo "✔ Preflight complete. Required tooling detected."
  fi
}

install_files() {
  echo "› Installing files to $APP_DIR …"
  as_root "$PREFIX" mkdir -p "$APP_DIR"
  # Copy only what's needed (bin + templates + scripts + docs); falls back to repo if structure differs.
  local rsync_args=(
    -a
    --delete
    --omit-dir-times
    --no-perms
    --no-owner
    --no-group
    --include '/bin/' --include '/bin/*'
    --include '/templates/***'
    --include '/src/***'
    --include '/scripts/***'
    --include '/tui/***'
    --include '/docs/***'
    --include '/verify/***'
    --include '/README*'
    --exclude '*'
  )

  if ! as_root "$PREFIX" rsync "${rsync_args[@]}" "$REPO_DIR"/ "$APP_DIR"/; then
    echo "rsync minimal copy failed; copying full repo…"
    as_root "$PREFIX" cp -R "$REPO_DIR"/. "$APP_DIR"/
  fi

  # Ensure CLI entrypoint is up to date
  if [[ -f "$APP_BIN" ]] && ! grep -q "placeholder" "$APP_BIN"; then
    as_root "$PREFIX" chmod +x "$APP_BIN"
  else
    echo "› Installing CLI entrypoint to $APP_BIN"
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
  if [[ "$INSTALL_MODE" == "macos" ]] && need_cmd brew; then
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
  local bdir
  case "$INSTALL_MODE" in
    macos)
      bdir="$PREFIX/etc/bash_completion.d"
      ;;
    linux)
      bdir="$PREFIX/share/bash-completion/completions"
      ;;
  esac
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
  local fdir="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"
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
