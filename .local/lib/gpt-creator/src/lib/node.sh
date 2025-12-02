#!/usr/bin/env bash
# shellcheck shell=bash
# node.sh — helpers for Node.js operations (version check, global installs, etc.)

if [[ -n "${GC_LIB_NODE_SH:-}" ]]; then return 0; fi
GC_LIB_NODE_SH=1

# Ensure Node.js is installed and the correct version
node_check_version() {
  local min_version="$1"
  local current_version; current_version=$(node -v | sed 's/^v//')
  if [[ "$(printf '%s
' "$min_version" "$current_version" | sort -V | head -n1)" != "$min_version" ]]; then
    echo "Node.js version $current_version found, but $min_version is required."
    return 1
  fi
  echo "Node.js version is correct: $current_version."
}

# Install a global NPM package
node_install_global() {
  local pkg="$1"
  npm install -g "$pkg"
  echo "Global npm package '$pkg' installed."
}

# Run an NPM script
node_run_script() {
  local script="$1"
  npm run "$script" || die "Failed to run npm script: $script"
  echo "NPM script '$script' completed."
}
