#!/usr/bin/env bash
# session.sh — manage Codex sessions for contextual persistence

if [[ -n "${GC_LIB_CODEX_SESSION_SH:-}" ]]; then return 0; fi
GC_LIB_CODEX_SESSION_SH=1

# Start a Codex session (initialize with context)
codex_start_session() {
  local session_id="$1"
  if [[ -z "$session_id" ]]; then
    echo "Error: session_id is required."
    return 1
  fi
  echo "Starting Codex session with ID: $session_id."
}

# Save context to a session file (used for subsequent calls)
codex_save_session() {
  local session_id="$1"
  local context_file="$2"
  if [[ -z "$session_id" || -z "$context_file" ]]; then
    echo "Error: session_id and context_file are required."
    return 1
  fi
  echo "Saving context to session $session_id."
  cp "$context_file" "./session_${session_id}.json"
}

# End Codex session
codex_end_session() {
  local session_id="$1"
  if [[ -z "$session_id" ]]; then
    echo "Error: session_id is required."
    return 1
  fi
  echo "Ending Codex session with ID: $session_id."
}
