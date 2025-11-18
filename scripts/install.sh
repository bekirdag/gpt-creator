#!/usr/bin/env bash
# Unix installer for gpt-creator (macOS / Linux)
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
HELP_DIR="${REPO_DIR}/assets/templates/help"

INSTALL_PREFIX="${PREFIX:-/usr/local}"
unset PREFIX 2>/dev/null || true
SKIP_PREFLIGHT=0
FORCE=0

usage() {
  local usage_file="${HELP_DIR}/install_usage.txt"
  if [[ -f "$usage_file" ]]; then
    cat "$usage_file"
  else
    printf '%s\n' \
      "gpt-creator installer (macOS / Linux)" \
      "" \
      "Usage:" \
      "  ./install.sh [--prefix /usr/local] [--skip-preflight] [--force]" \
      "" \
      "Installs:" \
      "  • CLI symlink → \$PREFIX/bin/gpt-creator" \
      "  • App files   → \$PREFIX/lib/gpt-creator" \
      "  • Shell completions (zsh/bash/fish)" \
      "" \
      "Preflight checks: Docker, Node 20+, pnpm, mysql client, Codex client, OPENAI_API_KEY"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) INSTALL_PREFIX="${2:-/usr/local}"; shift 2 ;;
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

APP_DIR="$INSTALL_PREFIX/lib/gpt-creator"
BIN_DIR="$INSTALL_PREFIX/bin"
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

run_as_user() {
  local user="$1"
  shift
  if [[ "$(id -u)" -eq 0 && "$user" != "root" ]]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo -u "$user" -- "$@"
    else
      su - "$user" -c "$(printf '%q ' "$@")"
    fi
  else
    "$@"
  fi
}

ver_major() { echo "${1#v}" | awk -F. '{print $1}'; }

INSTALL_WARNINGS=()
NODE_REQUIRED_MAJOR=20
NODE_CURRENT_VERSION=""
APT_UPDATED=0
NVM_INSTALL_URL="${GC_NVM_INSTALL_URL:-https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh}"
RUSTUP_INSTALL_URL="${GC_RUSTUP_INSTALL_URL:-https://sh.rustup.rs}"

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

list_conflicting_node_packages() {
  command -v dpkg >/dev/null 2>&1 || return 1

  local conflicts=(libnode-dev npm)
  local conflicts_found=()
  local pkg

  for pkg in "${conflicts[@]}"; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
      conflicts_found+=("$pkg")
    fi
  done

  if (( ${#conflicts_found[@]} == 0 )); then
    return 1
  fi

  printf '%s\n' "${conflicts_found[@]}"
  return 0
}

nvm_dir_path() {
  local dir="${NVM_DIR:-}"
  if [[ -z "$dir" ]]; then
    dir="${HOME}/.nvm"
  fi
  printf '%s' "$dir"
}

ensure_nvm() {
  local dir
  dir="$(nvm_dir_path)"
  if [[ -s "$dir/nvm.sh" ]]; then
    export NVM_DIR="$dir"
    return 0
  fi

  if ! need_cmd curl; then
    record_warning "curl is required to install nvm automatically. Install Node.js ${NODE_REQUIRED_MAJOR}+ manually (https://nodejs.org/)."
    return 1
  fi

  local install_script
  install_script="$(mktemp)" || {
    record_warning "Failed to create temporary file for nvm installer."
    return 1
  }

  log_info "nvm not found; installing from ${NVM_INSTALL_URL}…"
  if ! curl -fsSL "$NVM_INSTALL_URL" -o "$install_script"; then
    rm -f "$install_script"
    record_warning "Unable to download nvm installer."
    return 1
  fi

  if ! bash "$install_script"; then
    rm -f "$install_script"
    record_warning "nvm installer exited with an error."
    return 1
  fi
  rm -f "$install_script"

  if [[ -s "$dir/nvm.sh" ]]; then
    export NVM_DIR="$dir"
    return 0
  fi

  record_warning "nvm installation completed but ${dir}/nvm.sh was not found. Install Node.js ${NODE_REQUIRED_MAJOR}+ manually (https://nodejs.org/)."
  return 1
}

load_nvm() {
  local dir
  dir="$(nvm_dir_path)"
  if [[ -s "$dir/nvm.sh" ]]; then
    export NVM_DIR="$dir"
    # shellcheck disable=SC1090
    source "$dir/nvm.sh"
    return 0
  fi
  return 1
}

install_node_via_nvm() {
  local saved_prefix="" had_prefix=0
  if [[ "${PREFIX+x}" == x ]]; then
    saved_prefix="$PREFIX"
    had_prefix=1
    unset PREFIX
  fi

  local rc=0
  if ! ensure_nvm; then
    rc=1
  elif ! load_nvm; then
    record_warning "nvm installed but could not be loaded from $(nvm_dir_path)/nvm.sh."
    rc=1
  else
    local target="${GC_NODE_VERSION:-${NODE_REQUIRED_MAJOR}}"
    log_info "Installing Node.js ${target} via nvm…"
    if nvm install "$target"; then
      nvm alias default "$target" >/dev/null 2>&1 || true
      nvm use "$target" >/dev/null 2>&1 || true
      hash -r
    else
      record_warning "Failed to install Node.js ${target} via nvm."
      rc=1
    fi
  fi

  if (( had_prefix )); then
    PREFIX="$saved_prefix"
    export PREFIX
  fi

  return $rc
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
  if install_node_via_nvm; then
    installed=1
  else
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
          local node_conflicts=""
          node_conflicts="$(list_conflicting_node_packages 2>/dev/null || true)"
          if [[ -n "$node_conflicts" ]]; then
            node_conflicts="${node_conflicts//$'\n'/ }"
            record_warning "System Node.js packages (${node_conflicts}) block automatic installation. Remove them manually (e.g. sudo apt remove ...) or install Node.js ${NODE_REQUIRED_MAJOR}+ via https://nodejs.org/."
          else
            if command -v curl >/dev/null 2>&1; then
              local nodesource_script
              nodesource_script="$(mktemp)"
              if curl -fsSL https://deb.nodesource.com/setup_20.x -o "$nodesource_script"; then
                if as_root "/" bash "$nodesource_script"; then
                  if apt_get_install nodejs; then
                    installed=1
                  fi
                fi
              else
                record_warning "Failed to download NodeSource setup script."
              fi
              rm -f "$nodesource_script"
            fi
            if (( installed == 0 )); then
              if apt_get_install nodejs npm; then
                installed=1
              fi
            fi
          fi
        elif command -v dnf >/dev/null 2>&1; then
          if dnf_install nodejs; then
            installed=1
          fi
        fi
        ;;
    esac
  fi

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

ensure_rust() {
  if need_cmd cargo; then
    echo "✔ Rust toolchain $(cargo --version 2>/dev/null || true) detected."
    return 0
  fi

  log_info "Rust toolchain not found; attempting installation via rustup…"
  if ! need_cmd curl; then
    record_warning "Rust toolchain missing and curl unavailable to download rustup. Install Rust manually via https://rustup.rs/."
    return 1
  fi
  local installer
  if ! installer="$(mktemp)"; then
    record_warning "Failed to create temporary file for rustup installer."
    return 1
  fi
  if ! curl -fsSL "$RUSTUP_INSTALL_URL" -o "$installer"; then
    rm -f "$installer"
    record_warning "Unable to download rustup installer."
    return 1
  fi
  local target_user="${SUDO_USER:-$USER}"
  local target_home
  target_home="$(eval "echo ~${target_user}" 2>/dev/null || echo "$HOME")"
  local -a install_cmd=(bash "$installer" -y --no-modify-path)
  if ! run_as_user "$target_user" "${install_cmd[@]}"; then
    rm -f "$installer"
    record_warning "rustup installer exited with an error."
    return 1
  fi
  rm -f "$installer"
  local cargo_env="${target_home}/.cargo/env"
  if [[ -f "$cargo_env" ]]; then
    # shellcheck disable=SC1090
    source "$cargo_env"
  fi
  local cargo_bin="${target_home}/.cargo/bin"
  if [[ -d "$cargo_bin" ]]; then
    PATH="$cargo_bin:$PATH"
    export PATH
  fi
  hash -r
  if need_cmd cargo; then
    echo "✔ Rust toolchain $(cargo --version 2>/dev/null || true) installed."
    return 0
  fi
  record_warning "Rust installation completed but cargo is still unavailable. Ensure ${target_home}/.cargo/bin is on PATH."
  return 1
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
  ensure_rust
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
  as_root "$INSTALL_PREFIX" mkdir -p "$APP_DIR"
  # Copy only what's needed (bin + templates + scripts + docs); falls back to repo if structure differs.
  local rsync_args=(
    -a
    --delete
    --omit-dir-times
    --no-perms
    --no-owner
    --no-group
    --include '/Cargo.toml'
    --include '/Cargo.lock'
    --include '/bin/' --include '/bin/*'
    --include '/render_gpt_creator.sh'
    --include '/templates/***'
    --include '/assets/' --include '/assets/***'
    --include '/config/' --include '/config/***'
    --include '/src/***'
    --include '/scripts/***'
    --include '/docdexd/***'
    --include '/.gpt-creator/'
    --include '/.gpt-creator/***'
    --include '/tui/***'
    --include '/docs/***'
    --include '/verify/***'
    --include '/README*'
    --exclude '*'
  )

  if ! as_root "$INSTALL_PREFIX" rsync "${rsync_args[@]}" "$REPO_DIR"/ "$APP_DIR"/; then
    echo "rsync minimal copy failed; copying full repo…"
    as_root "$INSTALL_PREFIX" cp -R "$REPO_DIR"/. "$APP_DIR"/
  fi

  # Ensure shim binaries remain executable (fallback tools like rg live here)
  if [[ -d "$APP_DIR/.gpt-creator/shims/bin" ]]; then
    as_root "$INSTALL_PREFIX" find "$APP_DIR/.gpt-creator/shims/bin" -type f -exec chmod +x {} \;
  fi

  echo "› Installing CLI entrypoint to $APP_BIN"
  as_root "$INSTALL_PREFIX" mkdir -p "$(dirname "$APP_BIN")"
  as_root "$INSTALL_PREFIX" install -m 0755 "$REPO_DIR/bin/gpt-creator" "$APP_BIN"
}

install_docdexd() {
  local builder_script="$APP_DIR/scripts/docdex/build.sh"
  if [[ ! -f "$builder_script" ]]; then
    return
  fi
  if ! need_cmd cargo; then
    record_warning "Rust toolchain (cargo) not found; skipping docdexd build. Install Rust and run '$builder_script' later to enable doc indexing."
    return
  fi
  echo "› Building docdex daemon (docdexd)…"
  local env_path="$PATH"
  local env_home="$HOME"
  if as_root "$INSTALL_PREFIX" env PATH="$env_path" HOME="$env_home" bash -c "cd \"$APP_DIR\" && bash \"$builder_script\""; then
    echo "✔ docdexd built and installed under $APP_DIR/.gpt-creator/bin/docdexd"
  else
    record_warning "docdexd build failed; rerun '$builder_script' inside $APP_DIR after installing Rust."
  fi
}

ensure_runtime_permissions() {
  local target_user="${SUDO_USER:-$USER}"
  local target_home
  if ! target_home="$(eval "echo ~${target_user}")"; then
    return
  fi

  local prisma_cache="${target_home}/.cache/prisma"
  as_root "/" mkdir -p "$prisma_cache"
  as_root "/" chown -R "${target_user}:${target_user}" "$prisma_cache" 2>/dev/null || true

  if command -v pnpm >/dev/null 2>&1; then
    local pnpm_store_path
    pnpm_store_path="$(sudo -u "$target_user" pnpm store path 2>/dev/null || true)"
    if [[ -n "$pnpm_store_path" && -d "$pnpm_store_path" ]]; then
      as_root "/" chown -R "${target_user}:${target_user}" "$pnpm_store_path" 2>/dev/null || true
    fi
  fi
}

install_link() {
  echo "› Linking $LINK_PATH → $APP_BIN"
  as_root "$INSTALL_PREFIX" mkdir -p "$BIN_DIR"
  if [[ -L "$LINK_PATH" || -e "$LINK_PATH" ]]; then
    if [[ $FORCE -eq 1 ]]; then as_root "$INSTALL_PREFIX" rm -f "$LINK_PATH"; else
      echo "✖ $LINK_PATH exists. Re-run with --force to replace." >&2; exit 1; fi
  fi
  as_root "$INSTALL_PREFIX" ln -s "$APP_BIN" "$LINK_PATH"
  if [[ -f "$APP_DIR/.gpt-creator/shims/bin/rg" ]]; then
    as_root "$INSTALL_PREFIX" ln -sf "$APP_DIR/.gpt-creator/shims/bin/rg" "$BIN_DIR/rg"
  fi
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
    zcomp="$INSTALL_PREFIX/share/zsh/site-functions"
  fi
  as_root "$INSTALL_PREFIX" mkdir -p "$zcomp"
  local zsh_src="${REPO_DIR}/completions/gpt-creator.zsh"
  if [[ -f "$zsh_src" ]]; then
    as_root "$INSTALL_PREFIX" install -m 0644 "$zsh_src" "$zcomp/_gpt-creator"
  else
    echo "⚠ Missing zsh completion template at ${zsh_src}" >&2
  fi

  # bash
  local bdir
  case "$INSTALL_MODE" in
    macos)
      bdir="$INSTALL_PREFIX/etc/bash_completion.d"
      ;;
    linux)
      bdir="$INSTALL_PREFIX/share/bash-completion/completions"
      ;;
  esac
  as_root "$INSTALL_PREFIX" mkdir -p "$bdir"
  local bash_src="${REPO_DIR}/completions/gpt-creator.bash"
  if [[ -f "$bash_src" ]]; then
    as_root "$INSTALL_PREFIX" install -m 0644 "$bash_src" "$bdir/gpt-creator"
  else
    echo "⚠ Missing bash completion template at ${bash_src}" >&2
  fi

  # fish
  local fdir="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"
  mkdir -p "$fdir"
  local fish_src="${REPO_DIR}/completions/gpt-creator.fish"
  if [[ -f "$fish_src" ]]; then
    install -m 0644 "$fish_src" "$fdir/gpt-creator.fish"
  else
    echo "⚠ Missing fish completion template at ${fish_src}" >&2
  fi
}

main() {
  [[ $SKIP_PREFLIGHT -eq 1 ]] || preflight
install_files
install_docdexd
ensure_runtime_permissions
install_link
install_completions
  echo "✔ Installed. Try:"
  echo "    gpt-creator create-project /path/to/project"
}

main "$@"
