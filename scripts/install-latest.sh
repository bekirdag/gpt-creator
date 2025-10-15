#!/usr/bin/env bash
# Remote installer for gpt-creator.
# Supports curl | bash one-liners that clone the repo to a temp directory and re-run the standard installer.

set -Eeuo pipefail

PREFIX="/usr/local"
SKIP_PREFLIGHT=0
FORCE=0
REPO_URL="https://github.com/bekirdag/gpt-creator.git"
REF="main"

usage() {
  cat <<EOF
gpt-creator remote installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/bekirdag/gpt-creator/main/scripts/install-latest.sh | bash -s --

Options (pass after -- when piping via curl):
  --prefix PATH         Install prefix (default: /usr/local)
  --skip-preflight      Skip dependency checks
  --force               Overwrite existing symlink if present
  --repo URL            Install from a different Git repository
  --ref REF             Checkout a specific branch / tag / commit (default: main)
  -h, --help            Show this help text
EOF
}

need_cmd() { command -v "$1" >/dev/null 2>&1; }

cleanup() {
  local status=$?
  if [[ -n "${TMP_WORKDIR:-}" && -d "${TMP_WORKDIR}" ]]; then
    rm -rf "${TMP_WORKDIR}" || true
  fi
  exit "$status"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      PREFIX="${2:-}"
      [[ -n "$PREFIX" ]] || { echo "Missing value for --prefix" >&2; exit 2; }
      shift 2
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --repo)
      REPO_URL="${2:-}"
      [[ -n "$REPO_URL" ]] || { echo "Missing value for --repo" >&2; exit 2; }
      shift 2
      ;;
    --ref)
      REF="${2:-}"
      [[ -n "$REF" ]] || { echo "Missing value for --ref" >&2; exit 2; }
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

need_cmd git || { echo "✖ git is required to install gpt-creator" >&2; exit 1; }
need_cmd mktemp || { echo "✖ mktemp is required to install gpt-creator" >&2; exit 1; }

TMP_WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/gpt-creator-install.XXXXXX")"
trap cleanup EXIT

REPO_DIR="${TMP_WORKDIR}/gpt-creator"

echo "› Cloning ${REPO_URL} (${REF}) …"
if ! git clone --depth 1 --branch "$REF" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1; then
  echo "Failed shallow clone, falling back to full clone…" >&2
  if ! git clone "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1; then
    echo "✖ Unable to clone repository from ${REPO_URL}" >&2
    exit 1
  fi
  if ! git -C "$REPO_DIR" checkout "$REF" >/dev/null 2>&1; then
    echo "✖ Unable to checkout ref '${REF}' from ${REPO_URL}" >&2
    exit 1
  fi
fi

INSTALL_SCRIPT="${REPO_DIR}/scripts/install.sh"
if [[ ! -f "$INSTALL_SCRIPT" ]]; then
  echo "✖ Install script not found at ${INSTALL_SCRIPT}" >&2
  exit 1
fi

INSTALL_CMD=("$INSTALL_SCRIPT" --prefix "$PREFIX")
(( SKIP_PREFLIGHT )) && INSTALL_CMD+=(--skip-preflight)
(( FORCE )) && INSTALL_CMD+=(--force)

echo "› Running installer (${INSTALL_CMD[*]})"
if ! bash "${INSTALL_CMD[@]}"; then
  echo "✖ Installation failed" >&2
  exit 1
fi

echo "✔ gpt-creator installed successfully"
