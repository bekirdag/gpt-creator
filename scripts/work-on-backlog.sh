#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

MAX_STORY_SPINS="${MAX_STORY_SPINS:-1000}"
spins=0
prev_story=""
mkdir -p "${ROOT_DIR}/.gpt-creator/logs"

while (( spins < MAX_STORY_SPINS )); do
  if ! "${SCRIPT_DIR}/work-on-tasks-retry.sh" "$@"; then
    echo "[error] work-on-tasks failed; stopping." >&2
    exit 1
  fi

  log="${ROOT_DIR}/.gpt-creator/logs/last_run.log"
  if [[ ! -f "$log" ]]; then
    echo "[done] no log found; stopping."
    break
  fi

  current_story="$(grep -Eo "Preparing prompt for story '[^']+'" "$log" | tail -n1 | sed -E "s/.*'([^']+)'.*/\1/")"

  if [[ -z "$current_story" ]]; then
    echo "[done] no next story selected; stopping."
    break
  fi

  if [[ "$current_story" == "$prev_story" ]]; then
    echo "[done] story selection repeated ('$current_story'); stopping."
    break
  fi

  prev_story="$current_story"
  ((spins++))
done

echo "[ok] processed ${spins} stor(ies)."
