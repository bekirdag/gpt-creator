#!/usr/bin/env bash
set -euo pipefail

# Synthesize minimal review artefacts when the agent omitted them so
# auto-retry/auto-apply can proceed without blocking on "review (missing)".

ROOT="${1:-$(git rev-parse --show-toplevel)}"
RUNS_DIR="$ROOT/.gpt-creator/staging/plan/work/runs"
TEMPLATE_ROOT="$ROOT/assets/templates"

render_template() {
  local template_name="${1:?template name required}"
  local template_path="${TEMPLATE_ROOT}/${template_name}"
  if [[ ! -f "$template_path" ]]; then
    echo "[ensure_followups] template not found: ${template_path}" >&2
    return 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "[ensure_followups] python3 is required to render templates." >&2
    return 1
  fi
  python3 -c 'import os, sys
from string import Template

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = fh.read()
tmpl = Template(data)
sys.stdout.write(tmpl.safe_substitute(os.environ))' "$template_path"
}

json_escape() {
  local value="${1:-}"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "[ensure_followups] python3 is required to render templates." >&2
    return 1
  fi
  python3 -c 'import json, sys
print(json.dumps(sys.argv[1]))' "$value"
}

if [[ ! -d "$RUNS_DIR" ]]; then
  echo "[ensure_followups] runs directory missing; nothing to do"
  exit 0
fi

LAST_RUN="$(ls -1dt "$RUNS_DIR"/* 2>/dev/null | head -n1 || true)"
if [[ -z "${LAST_RUN:-}" || ! -d "$LAST_RUN" ]]; then
  echo "[ensure_followups] no runs found"
  exit 0
fi

REVIEW_DIR="$LAST_RUN/review"
mkdir -p "$REVIEW_DIR"

if [[ -s "$REVIEW_DIR/review.md" ]]; then
  echo "[ensure_followups] review already exists; skipping"
  exit 0
fi

LOG="$ROOT/.gpt-creator/logs/last-run.log"
if [[ ! -f "$LOG" ]]; then
  LOG="$LAST_RUN/console.log"
fi

task_id="unknown"
status="unknown"
tokens="unknown"

if [[ -f "$LOG" ]]; then
  task_id="$(grep -m1 -E '\|\s+START TASK ID\s+\|' -A2 "$LOG" | tail -n1 | tr -d ' |' || echo "unknown")"
  status="$(grep -m1 -E 'STATUS:' "$LOG" | sed -E 's/.*STATUS:\s+//' || echo "unknown")"
  tokens="$(grep -m1 -E 'TOKENS USED:' "$LOG" | sed -E 's/.*TOKENS USED:\s+//' || echo "unknown")"
fi

run_id="$(basename "$LAST_RUN")"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

review_log_path="$LOG"
if [[ "$review_log_path" == "$ROOT/"* ]]; then
  review_log_path="${review_log_path#"$ROOT"/}"
fi

(
  export EF_REVIEW_TASK_ID="${task_id:-unknown}"
  export EF_REVIEW_STATUS="${status:-unknown}"
  export EF_REVIEW_TOKENS="${tokens:-unknown}"
  export EF_REVIEW_RUN_ID="$run_id"
  export EF_REVIEW_TIMESTAMP="$timestamp"
  export EF_REVIEW_LOG_PATH="$review_log_path"
  render_template "review/stub_followup_review.md.tmpl"
) >"$REVIEW_DIR/review.md"

summary_task_id_json="$(json_escape "${task_id:-null}")"
summary_status_json="$(json_escape "${status:-unknown}")"
summary_tokens_json="$(json_escape "${tokens:-unknown}")"
summary_run_json="$(json_escape "$run_id")"
summary_timestamp_json="$(json_escape "$timestamp")"

(
  export EF_SUMMARY_TASK_ID="$summary_task_id_json"
  export EF_SUMMARY_STATUS="$summary_status_json"
  export EF_SUMMARY_TOKENS="$summary_tokens_json"
  export EF_SUMMARY_RUN_ID="$summary_run_json"
  export EF_SUMMARY_TIMESTAMP="$summary_timestamp_json"
  render_template "review/stub_followup_summary.json.tmpl"
) >"$REVIEW_DIR/summary.json"

echo "[ensure_followups] created stub review at $REVIEW_DIR"
