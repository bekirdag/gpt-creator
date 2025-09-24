#!/usr/bin/env bash
# gpt-creator requirements.sh — check for project dependencies

# Ensure all dependencies are installed
check_dependencies() {
  local missing=0

  # Docker
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required but not installed."
    missing=1
  fi

  # Node
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js is required but not installed."
    missing=1
  fi

  # pnpm
  if ! command -v pnpm >/dev/null 2>&1; then
    echo "pnpm is required but not installed."
    missing=1
  fi

  # Codex client
  if ! command -v codex >/dev/null 2>&1; then
    echo "Codex client is required but not installed."
    missing=1
  fi

  if [[ "$missing" -eq 1 ]]; then
    echo "Please install the missing dependencies."
    exit 1
  fi

  echo "All dependencies are installed."
}

check_dependencies
