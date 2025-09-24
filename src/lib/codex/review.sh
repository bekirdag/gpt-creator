#!/usr/bin/env bash
# review.sh — review and refine generated prompts and responses

if [[ -n "${GC_LIB_CODEX_REVIEW_SH:-}" ]]; then return 0; fi
GC_LIB_CODEX_REVIEW_SH=1

# Review generated response (Codex output) and provide feedback
codex_review_response() {
  local response_file="$1"
  local feedback_file="$2"
  if [[ -z "$response_file" || -z "$feedback_file" ]]; then
    echo "Error: response_file and feedback_file are required."
    return 1
  fi
  echo "Reviewing response in $response_file."
  cat "$response_file" >> "$feedback_file"
  echo "Feedback added to $feedback_file."
}

# Refine response using Codex
codex_refine_response() {
  local response_file="$1"
  local refinement_prompt="$2"
  if [[ -z "$response_file" || -z "$refinement_prompt" ]]; then
    echo "Error: response_file and refinement_prompt are required."
    return 1
  fi
  echo "Refining response from $response_file."
  codex_call "$refinement_prompt" "$response_file"
}
