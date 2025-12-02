#!/usr/bin/env bash
# Misc utility helpers.

gc_parse_int() {
  local value="$1"
  local fallback="$2"
  if [[ "$value" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "$value"
  else
    printf '%s\n' "$fallback"
  fi
}

gc_estimate_tokens_from_bytes() {
  local prompt_file="${1:?prompt path required}"
  if [[ ! -f "$prompt_file" ]]; then
    printf '0\n'
    return 0
  fi
  local bytes
  if ! bytes="$(wc -c <"$prompt_file" 2>/dev/null)"; then
    printf '0\n'
    return 0
  fi
  if ! [[ "$bytes" =~ ^[0-9]+$ ]]; then
    printf '0\n'
    return 0
  fi
  local approx=$(( (bytes + 3) / 4 ))
  printf '%s\n' "$approx"
}

gc_trim_prompt_file() {
  local prompt_file="$1"
  local max_tokens_raw="${GC_MAX_PROMPT_TOKENS:-8000}"
  [[ -f "$prompt_file" ]] || return 0
  if ! [[ "$max_tokens_raw" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  local max_tokens=$((max_tokens_raw))
  if (( max_tokens <= 0 )); then
    return 0
  fi
  local helper_path
  helper_path="$(gc_clone_python_tool "trim_prompt_file.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$prompt_file" "$max_tokens"
}

gc_trim_prompt_file_lean() {
  local prompt_file="$1"
  [[ -f "$prompt_file" ]] || return 0
  local helper_path
  helper_path="$(gc_clone_python_tool "trim_prompt_file_lean.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$prompt_file"
}
