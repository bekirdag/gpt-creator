#!/usr/bin/env bash
# codex.sh — helpers for Codex client interactions (using API calls)

if [[ -n "${GC_LIB_CODEX_SH:-}" ]]; then return 0; fi
GC_LIB_CODEX_SH=1

# Call Codex with a prompt
codex_call() {
  local prompt="$1"
  local output="$2"
  local model="${CODEX_MODEL:-gpt-5-high}"

  if [[ -z "${prompt}" || -z "${output}" ]]; then
    echo "Error: codex_call requires prompt and output parameters."
    return 1
  fi

  if command -v "${CODEX_BIN:-codex}" >/dev/null 2>&1; then
    codex chat --model "$model" --prompt "$prompt" --output "$output"
    echo "Codex output written to $output."
  else
    echo "Codex client not found. Please install Codex."
    return 1
  fi
}
