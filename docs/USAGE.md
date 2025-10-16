# USAGE

```
gpt-creator create-project /path/to/project [--yes] [--verbose]
gpt-creator scan --root DIR
gpt-creator normalize --root DIR
gpt-creator plan --root DIR --out plan.json
gpt-creator generate {api|web|admin|db|docker} --root DIR
gpt-creator db {provision|import|seed} --root DIR
gpt-creator run {up|down|logs|open} --root DIR
gpt-creator verify --root DIR
gpt-creator create-tasks --root DIR [--jira tasks.md] [--force]
gpt-creator work-on-tasks --root DIR [--story ID|SLUG] [--fresh] [--no-verify]
gpt-creator iterate --root DIR [--jira tasks.md]  # deprecated
```

Global flags:
- `--reports-on` enables automatic crash/stall reports for the current invocation (files land in `.gpt-creator/logs/issue-reports/`).
- `--reports-off` disables reporting even if `GC_REPORTS_ON=1`.
- `--reports-idle-timeout <seconds>` overrides the idle/stall threshold (defaults to `1800`; also configurable via `GC_REPORTS_IDLE_TIMEOUT`).
- `reports [slug]` lists captured reports (newest first) or prints the matching entry when you provide its slug; add `--open` to edit the YAML in `EDITOR_CMD`. Use `reports backlog` to filter to open items and display their popularity score (likes + comments). `reports work <slug>` prepares a Codex prompt, marks the issue in-progress, and directs Codex to implement, commit, and (by default) push the fix; pass `--branch`, `--no-push`, or `--prompt-only` to tailor the workflow. `reports auto` sweeps matching reports (defaulting to the current reporter or an explicit `--reporter`) and resolves them sequentially with Codex.

Common flow:
1) `create-project` (runs everything) or hand‑run: scan → normalize → plan → generate → db → run → verify.
2) Snapshot Jira markdown with `create-tasks`, then execute the backlog via `work-on-tasks`. The legacy `iterate` command is deprecated.
   - Use `--batch-size` to pause after a fixed number of tasks and `--sleep-between` to insert delays if Codex runs are exhausting local resources.
   - The CLI will try to install workspace dependencies automatically (preferring pnpm) before running tasks, reporting any failure to `/tmp/gc_deps_install.log`.
   - `create-tasks` now emits `.gpt-creator/staging/plan/tasks/tasks.db` (SQLite) with epics, stories, and tasks; reruns preserve task status unless `--force` is provided.
   - `work-on-tasks` reads and updates that database so resuming after interruptions requires no extra state files.
   - Trim shared context with `--context-lines`, `--context-file-lines`, `--context-skip`, or drop it entirely with `--context-none` when Codex prompts get too large.
  - Prompts are compact by default; use `--prompt-expanded` if you need the legacy verbose instruction/schema block.
  - Sample payloads default to a compact digest; increase `--sample-lines` when you need the first N minified chunks of the raw request/response.
  - Pull scoped excerpts for referenced documents/endpoints with `--context-doc-snippets`; excerpts are summarised and hashed to minimise prompt size.
  - `.gpt-creator/staging/plan/work/context.md` now collapses CSS, SQL dumps, markup, and JSON blobs by default; export `GC_CONTEXT_INCLUDE_UI=1` if you need the legacy raw UI asset sweep.
  - `work-on-tasks` requires `.gpt-creator/staging/plan/tasks/tasks.db`; JSON fallbacks were removed, so run `create-tasks` (or `create-jira-tasks` + `migrate-tasks`) beforehand.
