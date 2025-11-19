# Response-Format Guard Enhancements

The latest GPT-Creator runs (see `logs/20.txt:351-355`, `logs/20.txt:3763-3771`,
`logs/20.txt:4085-4090`, `logs/20.txt:4924-4929`, `logs/20.txt:67139-67144`) keep
failing because the assistant output violates the Plan/Focus/Commands/Notes
format guard. To prevent these failures from recurring—and to keep single-run
task completion rates high—we should implement the following improvements.

## 1. Preflight Template Injection
- Add a runtime hook that injects a prefilled Plan/Focus/Commands/Notes template
  into the assistant’s scratchpad after the plan is generated. The template
  would be updated incrementally (instead of narrating free-form notes), keeping
  every note in the “Action → Result” shape the guard expects.
- Provide helper commands (`gpt-creator add-note --action "notes-stop-and-plan"`)
  that automatically format each note so accidental narration is impossible.
- ✅ Runtime now auto-injects the Plan/Focus/Commands/Notes block when the final
  response omits those headings (implemented in `src/lib/work_on_tasks_runtime.py`),
  so downstream guards still receive a compliant template even if the assistant
  forgets.

## 2. Real-Time Linting for Notes and Responses
- Extend `work_on_tasks_runtime.py` to lint the pending response buffer before
  the assistant submits it. If the linter detects more than two consecutive
  narration lines or raw code fences, it should rewrite them into terse bullets
  or block submission with a clear remediation hint.
- Surface a running counter (e.g., “Notes remaining before guard trips: 1”) so
  the agent knows exactly when it must switch back to action-item format.
- ✅ Consecutive narration notes now trigger a live countdown warning via the
  `notes-lint-warning` status in `src/lib/work_on_tasks_runtime.py`, telling the
  agent how many narration entries remain before the guard fires.

## 3. Auto-Trimming and Summarization Helpers
- When long explanations are unavoidable, provide a `gpt-creator summarize` helper
  that takes the narration chunk, archives the verbose text under
  `logs/notes/` automatically, and replaces it with the required
  “Action: … | Result: …” pointer so the guard never fires.
- Bundle a `notes-to-plan` command that converts prose into the required
  templated bullets in place, minimizing manual editing.
- ✅ Added `scripts/python/summarize_note.py`, which reads piped narration, archives
  it under `logs/notes/`, and prints the ready-to-paste
  `Action: summarize-note | Result: …` pointer so assistants can quickly replace
  long-form explanations with compliant notes.

## 4. Final-Message Formatter
- Add a `gpt-creator format-response` step at the end of every run. The formatter
  ensures the final message contains **exactly** the Plan/Focus/Commands/Notes
  headings (with no extra prose) and shaves code samples down to file references
  so the `code-sample-detected` warning never appears.
- The formatter can infer touched files from `git status` and pre-populate the
  Focus section, reducing the temptation to paste code snippets to “show” the
  reviewer changes.
- ✅ The apply runtime now re-renders the final agent reply into the canonical
  Plan/Focus/Commands/Notes template before archiving it, replacing ad-hoc prose
  with the standardized block automatically.

## 5. Guardrail Telemetry & Alerting
- Emit structured metrics when `notes-stop-and-plan`,
  `notes-trim-longform`, or `code-sample-detected` is triggered so we can spot
  regressions early. A Grafana or CLI dashboard could alert when any guard trips
  twice within one run, prompting immediate remediation instead of letting the
  task reach RETRYABLE state.
- ✅ Guard events now register via `_record_guard_event` in
  `src/lib/work_on_tasks_runtime.py`, persist as JSONL under
  `logs/guardrails/events.jsonl`, and emit a `guard-telemetry` summary note per
  run (with counts) for quick alerting.

## 6. Training & Quick Reference Updates
- Update the contributor quick-start guide with explicit Plan/Focus/Commands/Notes
  examples, clarifying acceptable phrasing and the maximum allowed narration.
- Provide a one-line reminder in the prompt banner (“Keep notes in
  Action/Result format; use `gpt-creator summarize` for long text”) so agents
  remember the constraints before they type.
- ✅ The README “Contributor Quick Start” section now explains the
  Plan/Focus/Commands/Notes template, the narration guard limits, and tips for
  using `scripts/python/summarize_note.py`. We also added a response-format
  reminder banner to the prompt instructions, highlighting the Action/Result
  requirement.

Implementing the set above will streamline runs, eliminate format guard
violations, and keep expensive tasks from repeating solely due to reporting
errors.
