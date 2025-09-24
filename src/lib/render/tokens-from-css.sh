#!/usr/bin/env bash
# tokens-from-css.sh — generate design tokens from CSS files (e.g., colors, spacing)
# Converts CSS values (e.g., hex, px) into design tokens.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${ROOT_DIR}/src/constants.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/src/constants.sh"
else
  die "constants.sh not found"
fi

generate_tokens_from_css() {
  local css_file="$1"
  local output_file="$2"
  [[ -f "$css_file" ]] || die "CSS file not found: $css_file"
  mkdir -p "$(dirname "$output_file")"
  # Convert CSS values to tokens
  echo "Generating design tokens from CSS: $css_file → $output_file"
  codex_call "generate-tokens-from-css" "$css_file" "$output_file"
}

# Usage: generate_tokens_from_css <css-file> <output-file>
