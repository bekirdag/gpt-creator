#!/usr/bin/env bash
# prompts.sh — manages prompt generation and storage for Codex

if [[ -n "${GC_LIB_CODEX_PROMPTS_SH:-}" ]]; then return 0; fi
GC_LIB_CODEX_PROMPTS_SH=1

# Create a new prompt file with basic instruction format
codex_create_prompt() {
  local prompt_id="$1"
  local content="$2"
  if [[ -z "$prompt_id" || -z "$content" ]]; then
    echo "Error: prompt_id and content are required."
    return 1
  fi
  echo "Prompt ID: $prompt_id" > "prompts/${prompt_id}.txt"
  echo "$content" >> "prompts/${prompt_id}.txt"
  echo "Prompt saved as prompts/${prompt_id}.txt."
}

# List all available prompts
codex_list_prompts() {
  echo "Available prompts:"
  ls prompts/*.txt
}
