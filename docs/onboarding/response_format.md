# Response-Format Guard Reference

This note summarizes the workflows contributors should follow to stay within the
Plan/Focus/Commands/Notes guardrails and to verify the automation locally.

## Required Reply Template

- Every work-on-tasks response must contain the headings `Plan`, `Focus`,
  `Commands`, and `Notes` (each on its own line with no Markdown adornments).
- Keep bullets terse and prefer `Action: … | Result: …` phrasing. The runtime
  automatically warns after two narration-only notes and blocks on the third.

## Handling Long-Form Notes

- Pipe narration through the helper and paste the emitted summary pointer:

  ```bash
  python3 scripts/python/summarize_note.py "db-analysis" <<'EOF'
  <detailed narration>
  EOF
  ```

- The script archives the narration under `logs/notes/` and prints a ready-made
  `Action: summarize-note | Result: …` line that satisfies the guard.

## Guard Telemetry & Evidence

- Any guard event (auto-format, lint warning, code-sample warning, etc.) is
  recorded in `logs/guardrails/events.jsonl` with the task metadata. Inspect
  this file whenever a run is retryable to see which guard fired.
- The `Notes` section will include `Action: guard-telemetry | Result: …` with a
  per-code count so you can triage quickly without opening the JSONL file.
- CI / dashboards: run `python3 scripts/python/guardrails_report.py --json` (and
  optionally `--fail-on-placeholder N`) to aggregate guard hits or fail the
  build when placeholder usage spikes.

## Dry “work-on-tasks” Rehearsal

Use the runtime directly to validate formatting logic without touching a real
project backlog:

```bash
cat <<'EOF' >/tmp/response.json
{"plan": ["Demo"], "focus": [], "changes": [], "commands": [], "notes": ["Narration"]}
EOF
python3 src/lib/work_on_tasks_runtime.py apply /tmp/response.json .
```

The apply stage will auto-format the narration, record guard telemetry, and
write a report under `.gpt-creator/reports/task/<timestamp>/`. Review
`logs/guardrails/events.jsonl` afterwards to confirm the guard counts.

## Command Writing Checklist

- Generate commands with `python3 scripts/python/command_scaffold.py "label" 'cd apps/api' 'pnpm test'` to avoid placeholder ellipses.
- Close every heredoc: `cat <<'EOF' > file … EOF` (use matching labels).
- Use `python3 scripts/python/show_file_excerpt.py <path> --start 1 --end 200` for quick line views instead of `nl`/`sed` pipelines.
- Double-check the `Commands` section before submission—if the apply guard inserts `# TODO – replace placeholder`, fix those entries immediately.

## Documentation Catalog Helper

- Query SDS/PDR context via `python3 scripts/python/doc_catalog_query.py`:
  - `python3 scripts/python/doc_catalog_query.py list --limit 10`
  - `python3 scripts/python/doc_catalog_query.py search --query "lockout" --limit 15`
  - `python3 scripts/python/doc_catalog_query.py show DOC-1234ABCD --start 500 --end 540`
- The helper wraps `doc_catalog.py` with the supported flags and falls back to scanning the repo (or docdex) when the SQLite catalog is unavailable, so you no longer need to memorize `$GC_DOC_CATALOG_PY` invocations.
