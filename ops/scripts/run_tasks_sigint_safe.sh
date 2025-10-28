#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=${PROJECT_ROOT:-$(pwd)}
CMD=(gpt-creator work-on-tasks --project "$PROJECT_ROOT")

run_pid=

mark_interrupted() {
  local signal="$1"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  local work_root="$PROJECT_ROOT/.gpt-creator/staging/plan/work"

  mkdir -p "$work_root"
  printf '{"apply_status":"aborted","interrupted_by_signal":true,"signal":"%s","marked_at":"%s"}\n' \
    "$signal" "$ts" > "$work_root/INTERRUPTED.meta.json"

  # Patch state.json -> apply_status=aborted (safe to retry)
  if [[ -f "$work_root/state.json" ]]; then
    python3 - "$work_root/state.json" <<'PY'
import json, sys, os
p=sys.argv[1]
try:
    with open(p) as f: s=json.load(f)
except Exception:
    s={}
s.setdefault('last_run',{})['apply_status']='aborted'
s['interrupted_by_signal']=True
s.setdefault('notes',[]).append('aborted due to SIGINT/SIGTERM; safe to retry')
tmp=p+'.tmp'
with open(tmp,'w') as f: json.dump(s,f,indent=2,ensure_ascii=False)
os.replace(tmp,p)
PY
  fi

  # Snapshot WIP so the run is traceable
  git add -A || true
  git commit -m "chore(gpt-creator): WIP snapshot after signal; mark apply_status=aborted" || true

  # Ask child to exit gracefully
  if [[ -n "${run_pid:-}" ]]; then
    kill -TERM "$run_pid" 2>/dev/null || true
    wait "$run_pid" 2>/dev/null || true
  fi
  exit 130
}

trap 'mark_interrupted INT' INT
trap 'mark_interrupted TERM' TERM

"${CMD[@]}" "$@" &
run_pid=$!
wait "$run_pid"
exit $?
