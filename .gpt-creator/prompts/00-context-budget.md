# Context Budget Guardrail

- Always use `gpt-creator show-file <path> --range START:END` to capture at most 120 lines at a time.
- Never paste full files, database dumps, build artifacts, or generated bundles into the prompt.
- Prefer `rg -n <term> --context 20` (or similar) to locate hits, then fetch only those ranges.
- When referencing logs, collapse them to the specific lines required to justify the change.
- Summaries should reference paths and line spans instead of copying entire files.
