#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CRATE_DIR="${REPO_ROOT}/docdexd"
TARGET="${CRATE_DIR}/target/release/docdexd"
INSTALL_DIR="${REPO_ROOT}/.gpt-creator/bin"

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo toolchain missing; install Rust before building docdexd." >&2
  exit 1
fi

echo "Building docdexd (release)..."
(
  cd "${CRATE_DIR}"
  export CARGO_NET_OFFLINE=true
  if [[ -f "Cargo.lock" ]]; then
    cargo build --release --locked
  else
    cargo build --release
  fi
)

if [[ ! -f "${TARGET}" ]]; then
  echo "docdexd binary not found at ${TARGET}" >&2
  exit 1
fi

mkdir -p "${INSTALL_DIR}"
cp "${TARGET}" "${INSTALL_DIR}/docdexd"
chmod +x "${INSTALL_DIR}/docdexd"
echo "docdexd installed to ${INSTALL_DIR}/docdexd"
