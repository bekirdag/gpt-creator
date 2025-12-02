#!/usr/bin/env bash
# shellcheck shell=bash

cmd_update() {
  local force=0
  local repo_url="${GC_UPDATE_REPO_URL:-https://github.com/bekirdag/gpt-creator.git}"
  local prefix="/usr/local"
  local tmpdir=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force)
        force=1
        shift
        ;;
      -h|--help)
        if tmpl="$(gc_help_template_for_cmd update)"; then
          gc_render_template "${tmpl}"
        else
          gc_render_template "help/update_usage.txt"
        fi
        return 0
        ;;
      *)
        die "Unknown argument for update: $1"
        ;;
    esac
  done

  if ! command -v git >/dev/null 2>&1; then
    die "'git' is required for ${APP_NAME} update"
  fi

  tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/gpt-creator-update.XXXXXX")" || die "Unable to create temporary directory"

  info "Cloning repository: $repo_url"
  if ! git clone "$repo_url" "$tmpdir"; then
    rm -rf "$tmpdir"
    die "Failed to clone repository from ${repo_url}"
  fi

  info "Fetching latest changes"
  if ! git -C "$tmpdir" pull --ff-only; then
    rm -rf "$tmpdir"
    die "Failed to update repository in $tmpdir"
  fi

  local install_script="$tmpdir/scripts/install.sh"
  if [[ ! -x "$install_script" ]]; then
    rm -rf "$tmpdir"
    die "Installer not found at $install_script"
  fi

  local -a install_cmd=("$install_script" --prefix "$prefix")
  if (( force )); then
    install_cmd+=("--force")
  fi

  info "Running installer: ${install_cmd[*]}"
  if ! "${install_cmd[@]}"; then
    rm -rf "$tmpdir"
    die "Install script failed"
  fi

  rm -rf "$tmpdir"
  ok "gpt-creator updated successfully"
}
