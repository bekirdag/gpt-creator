# gpt-creator

`gpt-creator` is an opinionated, AI-assisted project bootstrapper. It ingests heterogeneous discovery artifacts such as Product Requirement Docs (PDR), System Design Specs (SDS), RFPs, OpenAPI specs, SQL dumps, Mermaid diagrams, and HTML/CSS samples, then normalizes, plans, generates, runs, and verifies a full local stack (NestJS API + Prisma + MySQL + Vue 3 web/admin + Docker) in a single workflow.

The implementation follows the Product Definition & Requirements (PDR v0.2) in `docs/PDR.md`. This README explains how the tool is structured, the dependencies you need, how to install it, and how to drive each phase end-to-end.

---

## Features at a Glance

- **Single-command bootstrap**: `gpt-creator create-project <path>` orchestrates scan → normalize → plan → generate → db → run → qa so the stack and QA (web + mobile) are exercised in one flow.
- **Fuzzy discovery**: Locates artifacts across diverse naming conventions (e.g., `*PDR*.md`, `openapi.*`, `sql_dump*.sql`, `*.mmd`, HTML/CSS samples).
- **Deterministic staging**: Copies inputs into `.gpt-creator/staging/inputs/` with canonical names and provenance tracking.
- **Progress cleanup**: Sweeps legacy Codex progress artifacts (e.g., `tmp_*`, `final_*`, `diff*`, `*_patch.jsonstr`) into `.gpt-creator/**` so the project root stays clean while runs remain resumable.
- **Planning outputs**: Produces route/entity summaries and task hints under `.gpt-creator/staging/plan/` as scaffolding for further design work.
- **Template-driven generation**: Renders baseline NestJS, Vue 3, Prisma, and Docker scaffolds into `/apps/**` and `/docker`, ready for manual extension or Codex-driven augmentation.
- **Verification toolkit**: Bundled acceptance/OpenAPI/a11y/Lighthouse/consent/program-filter/telemetry checks plus Detox/Maestro mobile hooks so `gpt-creator qa` can gate both web and React Native surfaces.
- **Doc synthesis**: `create-pdr` converts the staged RFP into a multi-level Product Requirements Document (PDR) by iteratively asking Codex to draft the table of contents, sections, and detailed subsections. `create-sds` continues the loop, transforming the staged PDR into a System Design Specification that drills from architecture overview down to low-level operational detail.
- **Database synthesis**: `create-db-dump` reads the SDS (and PDR context) to draft a full MySQL schema plus production-grade seed data, then reviews both dumps for consistency before storing them under `.gpt-creator/staging/plan/create-db-dump/sql/`.
- **Iteration helpers**: `create-jira-tasks` mines staged docs into JSON story/task bundles, `migrate-tasks` pushes those artifacts into the SQLite backlog, `refine-tasks` enriches tasks in-place from the database, `create-tasks` converts existing Jira markdown, `order-tasks` rebuilds dependency metadata and DAG priority, and `work-on-tasks` executes/resumes backlog items using that persisted order so dependencies land first. When coding is done, `review-tasks` performs LLM-based code review (ready-to-review → ready-for-qa or → pending with comments), `qa-tasks` runs Playwright smoke (ready-for-qa → completed or → pending with findings), and `qa-llm` runs an agent-driven QA verdict/issue pass over ready-for-qa items. The legacy `iterate` command is deprecated.
- **Backlog browser**: `backlog` prints non-interactive terminal summaries so you can list epics, enumerate stories, inspect children, dump task details, or preview the next DAG-prioritised tasks straight from the SQLite backlog.
- **Backlog ETA**: `estimate` aggregates remaining story points in `.gpt-creator/staging/plan/tasks/tasks.db` and translates them into a formatted duration using the throughput observed during `work-on-tasks` runs (defaults to a 10-task window at 15 story points per hour until telemetry is captured). Use `--recent-tasks COUNT|all` to widen the sample window and `--project` to point at another workspace when needed.
- **Token tracking**: `tokens` summarises Codex usage stored in `.gpt-creator/logs/codex-usage.ndjson` so you can translate model activity into spend.
- **Safety preflights**: Every CLI entry now runs through workspace/doc catalog/dependency guards so stale or unsafe paths are rejected, lockfiles are rebuilt automatically, and missing dependencies fall back to mock mode instead of crashing active runs.
- **Guarded file writes**: `gpt-creator apply-block` (or the guarded helper `tools/scripts/python/write_block.py`, also reachable via the legacy `scripts/` symlink) are the only approved writers; Husky/CI guards reject heredocs, ellipses, and curl-to-shell pipelines so every change lands through an audited, atomic workflow.
- **Schema evidence index**: A stack-neutral inspector builds an index of tables/indexes across SQL, Prisma, Knex, Rails, TypeORM, and Django sources. Commands such as `gc_assert table publish_jobs` use this cache so schema checks become tolerant hints rather than brittle `rg` probes.
- **Runtime overlays**: A Jest/Vitest decorator enforces single-process execution, injects a transpile-only TypeScript preloader, shims heavy native modules (@prisma/client, sharp, multer, prom-client, etc.), and remaps missing `dist/` imports to `src/lib/build/out`, keeping tests runnable even when installs or builds fail.

## Token-Efficient Helper Scripts

Codex agents should prefer the purpose-built helpers below instead of ad‑hoc `ls`, `sed`, or `python - <<'PY' os.walk(...)` loops. Each script ships with a short usage guide under `assets/templates/help/*.txt` to keep instructions cached locally.

| Tool | When to use it | Usage doc |
|------|----------------|-----------|
| `python3 "$GC_REPO_OUTLINE_PY"` | Get a concise directory tree (with optional focus paths) instead of running dozens of `ls` commands. (If running outside `gpt-creator`, call `tools/scripts/python/repo_outline.py` directly.) | `assets/templates/help/repo_outline_usage.txt` |
| `python3 "$GC_TARGETED_SEARCH_PY"` | Search for strings/regex within a bounded set of files (depth/extension limited) instead of walking the entire repo. Supports multiple patterns and optional context output. (Fallback: `tools/scripts/python/targeted_search.py`.) | `assets/templates/help/targeted_search_usage.txt` |
| `python3 "$GC_REST_CHECK_RUNNER_PY"` | Run declarative REST smoke tests defined in a YAML/TOML manifest (auth, payloads, predicates) instead of writing bespoke HTTP scripts each turn. (Fallback: `tools/scripts/python/rest_check_runner.py`.) | `assets/templates/help/rest_check_runner_usage.txt` |
| `python3 "$GC_SAFE_SHOW_FILE_PY"` | Preview file slices and get real path suggestions before running `sed`/`cat`, preventing token waste on missing files. (Fallback: `tools/scripts/python/safe_show_file.py`.) | `assets/templates/help/safe_show_file_usage.txt` |
| `python3 "$GC_RUN_SNIPPET_PY"` | Execute temporary Python helpers safely; refuses placeholder-only heredocs so commands stay valid. (Fallback: `tools/scripts/python/run_snippet.py`.) | `assets/templates/help/run_snippet_usage.txt` |

These helpers are mandatory during `work-on-tasks` sessions: mention them in your task notes, keep token-heavy scans capped, and extend the manifest/usage templates rather than cloning new tooling.

---

## Docdex (Documentation Search) Guide

Docdex is now distributed via npm. Install the CLI (`npm i -g docdex` or `npx docdex --version`) and use the provided commands—no local Rust build or bundled binary required.

- During `work-on-tasks`, the runtime shells out to the docdex CLI for searches; it falls back to legacy SQLite/vector search only if the CLI fails. Completed coding runs stop at `ready-to-review`; run `review-tasks` next (pass/pend) then `qa-tasks` (complete/pend).
- Helpers (`doc_catalog_query.py`, `work_on_tasks_runtime.py`) already call `docdex_client.search_docs`, which now wraps the npm CLI.

### Quickstart

```bash
npm i -g docdex           # or use npx docdex --version
docdexd index --repo /path/to/project   # build index
docdexd query --repo /path/to/project --query "otp flow" --limit 5   # ad-hoc search (JSON)
```

You can override the CLI path with `GC_DOCDEX_BIN` (default: `docdexd` on PATH). For local use we set `DOCDEX_SECURE_MODE=false` when spawning the CLI; if you run the HTTP server yourself, keep secure defaults (`--secure-mode=true`, auth token).

### Rebuilding the Index

Docdex stores its index under `.docdex/index` by default (it will reuse a legacy `.gpt-creator/docdex/index` if present). To refresh snippets, run:

```bash
docdexd index --repo /path/to/project
```

Or reindex a single file:

```bash
docdexd ingest --repo /path/to/project --file docs/new.md
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| macOS (primary target) or Linux | Windows is untested. |
| [Docker](https://docs.docker.com/), `docker compose` | Needed for the `run` phase; legacy verification scripts are manual-only. |
| Node.js ≥ 20 | Required for generated NestJS / Vite projects. |
| `pnpm` | Used by generated clients; install via `corepack enable`. |
| MySQL client (`mysql`) | Used for import/health checks. |
| Codex CLI (`codex` or compatible) | AI generation/iteration driver. |
| `OPENAI_API_KEY` environment variable | Passed to Codex for model access. |
| Optional: `npx`, `jq`, `curl`, `pa11y`, `lighthouse` | Used only when running the legacy verification scripts manually. |

> **Tip:** Run `./scripts/install.sh --skip-preflight` if you simply want to copy binaries without the strict prerequisite checks. The default preflight ensures everything above is present.

---

## Installation

### Option 0 — Remote install helper (two steps)

```bash
curl -fsSL https://raw.githubusercontent.com/bekirdag/gpt-creator/main/scripts/install-latest.sh -o /tmp/gpt-creator-install.sh
bash /tmp/gpt-creator-install.sh -- --prefix /opt --force --skip-preflight
```

Download the helper script, inspect it if desired, then run it with any flags after `--`. The helper clones the repository into a temporary directory, runs the standard installer (`scripts/install.sh --prefix /usr/local` by default), then removes the temporary files. Requires `git` and `mktemp` on your `PATH`.

### Option 1 — System-wide install (macOS)

```bash
./scripts/install.sh --prefix /usr/local
```

Installs:
- Executable symlink: `/usr/local/bin/gpt-creator`
- Library assets: `/usr/local/lib/gpt-creator`
- Shell completions: zsh/bash/fish (if writable)

Use `--skip-preflight` to bypass dependency checks or `--force` to replace an existing symlink. The installer will try to provision missing tooling like Node.js, pnpm, and the MySQL client automatically; dependencies that need manual setup (Docker Desktop, Codex CLI, API keys) surface as warnings when the relevant commands run.

### Option 2 — Local clone

```bash
git clone https://github.com/bekirdag/gpt-creator.git
cd gpt-creator
./bin/gpt-creator help
```

Keep the repo on your `PATH`, or invoke `./bin/gpt-creator` directly.

### Updating an existing install

Run:

```bash
gpt-creator update [--force]
```

The updater clones the latest `gpt-creator` sources into a temporary directory, runs `scripts/install.sh --prefix /usr/local`, and removes the temporary files. Use `--force` when you need to replace an existing `/usr/local/bin/gpt-creator` symlink. Set `GC_UPDATE_REPO_URL` if you maintain an internal fork, and ensure `git` is available on your `PATH`. To install to a different prefix, re-run `scripts/install.sh` manually.

---

## Quick Start

1. **Collect artifacts** into a folder (PDR/SDS docs, `openapi.yaml`, SQL dumps, HTML samples, etc.).
2. **Run the bootstrap command**:
   ```bash
   gpt-creator create-project --template auto /path/to/project
   ```
   - A `.gpt-creator` workspace is created under the project root.
   - Generated code lands in `/apps/api`, `/apps/web`, `/apps/admin`, `/db`, `/docker`.
  - A `.env` file with random database credentials is created automatically; reuse it for local scripts and CI secrets.
  - The automated testing stage has been removed; gpt-creator now focuses exclusively on code creation.
  - Templates live under `project_templates/`. Add subdirectories (optionally with `tags.txt` or `template.json`) to seed new projects; `--template auto` attempts to match the staged RFP/PDR, or pass `--template <name>` / `--skip-template` to override.

### Testing

- Run `npm test` (alias for `npx vitest run`). The default config uses the `vmThreads` pool with a single worker for sandbox compatibility; increase workers or switch pools in `vitest.config.mts` if your environment supports it.

### Contributor Quick Reference

- **Response template:** Every assistant reply must use the `Plan`, `Focus`, `Commands`, `Notes` headings (each on its own line). Keep the sections terse—bulleted steps with `Action: … | Result: …` phrasing where possible.
- **Narration limits:** The runtime auto-warns after two narration-style notes and will block on the third. Convert prose into checklist bullets immediately; if you need to preserve detail, pipe it through `python3 tools/scripts/python/summarize_note.py "label"` and paste the generated summary pointer.
- **Command helper:** Use `python3 tools/scripts/python/command_scaffold.py "label" 'cd apps/api' 'pnpm test'` to produce a placeholder-free `bash -lc` entry instead of typing ellipses.
- **Code samples:** Instead of pasting diffs or source blobs, reference the touched paths (e.g., ``apps/api/src/foo.ts:42``). The response guard flags raw code fences and will auto-format them away.
- **Guard telemetry:** If any guard triggers, check `logs/guardrails/events.jsonl` (or the `guard-telemetry` note) to see which rule fired and how often. Run `python3 tools/scripts/python/guardrails_report.py --json` (or `--fail-on-placeholder N`) to aggregate hits or fail CI when placeholders pop up.
- **Final reminder:** The prompt banner reiterates the response-format rules before every run—use it as a checklist before submitting so guardrails never fire in the first place. See `docs/onboarding/response_format.md` for the full guide.

#### Command Writing Checklist

- No placeholders: commands must be fully formed (no `...` or `…`).
- Heredocs require matching terminators (`cat <<'EOF' ... EOF`).
- Prefer `python3 tools/scripts/python/command_scaffold.py` to generate `bash -lc` entries.
- Use `python3 tools/scripts/python/show_file_excerpt.py <path> --start 1 --end 120` for quick file views instead of `nl`/`sed` pipelines.
- Re-run the `commands-fill-placeholders` guard (apply phase) if you edit commands after tests to ensure no TODO markers remain.

#### Documentation Catalog Helper

- Query documentation via `python3 tools/scripts/python/doc_catalog_query.py list|search|show ...`; it wraps `doc_catalog.py` with supported flags and falls back to repo scanning when the SQLite DB is absent. No need to remember the raw `$GC_DOC_CATALOG_PY` command.

   To drive the entire flow (PDR → SDS → Jira tasks → stack generation) in one shot:

   ```bash
   gpt-creator bootstrap --template auto --rfp docs/rfp.md /path/to/project
   ```

  This runs `create-pdr`, `create-sds`, `create-db-dump`, `create-jira-tasks`, and the full build pipeline sequentially, producing docs, database dumps, backlog, code, and a running stack with a single command.
   - If a step fails, re-running `bootstrap` resumes from the last successful step. Use `--fresh` to restart the pipeline from scratch. Provide `--rfp` to stage the primary RFP file when launching the flow.
3. **Inspect outputs**:
   - `.gpt-creator/staging/discovery.yaml` for scan results
   - `.gpt-creator/staging/plan/` for route/entity summaries and tasks
4. **Synthesize docs** (optional):
   ```bash
   # Build a Product Requirements Document from the staged RFP
   gpt-creator create-pdr --project /path/to/project

   # Derive the System Design Specification directly from the staged PDR
   gpt-creator create-sds --project /path/to/project
   ```
   - `create-pdr` iteratively asks Codex to propose the table of contents, then fills each section/subsection with detail sourced from the normalized RFP.
   - `create-sds` consumes the staged PDR and performs the same iterative flow to produce an architecture-focused SDS (`.gpt-creator/staging/plan/sds/sds.md`).

   ```bash
   # Generate schema.sql and seed.sql derived from the SDS
   gpt-creator create-db-dump --project /path/to/project
   ```
   - `create-db-dump` synthesizes a MySQL schema and seed dump, stores them under `.gpt-creator/staging/plan/create-db-dump/sql/`, and finishes with a Codex review to ensure consistency across tables, constraints, and seed data.
   - All of the Codex-backed doc commands above accept `-m/--model <model-id>` to override the `CODEX_MODEL`/`CODEX_MODEL_NON_CODE` defaults for that single run (for example, `gpt-creator create-sds --project /path/to/project --model gpt-4.1-mini`).

5. **Work Jira backlog** (optional):
   ```bash
   # Mine the documentation and auto-create epics, stories, and task JSON
   gpt-creator create-jira-tasks --project /path/to/project

   # Rebuild the SQLite backlog from the generated JSON (fast, no Codex calls)
   gpt-creator migrate-tasks --project /path/to/project [--force]

   # Refine tasks directly from the SQLite backlog (updates each task immediately)
   gpt-creator refine-tasks --project /path/to/project

   # Or import an existing Jira markdown export
   gpt-creator create-tasks --project /path/to/project --jira docs/jira.md

   # Execute and resume tasks directly from SQLite
   gpt-creator work-on-tasks --project /path/to/project
   gpt-creator review-tasks --project /path/to/project --agent Reviewer-A
   gpt-creator qa-tasks --project /path/to/project --url https://localhost:3000

   # Populate task dependencies and recompute the global DAG order
   gpt-creator order-tasks --project /path/to/project [--force]

   # Browse epics → stories → tasks from the backlog database
   gpt-creator backlog --project /path/to/project          # defaults to epic summaries
   gpt-creator backlog --project /path/to/project --item-children epic-slug
   gpt-creator backlog --project /path/to/project --progress

   # Manage reusable agents (job + character personas)
   gpt-creator create-agent --project /path/to/project --name Fixer-A \
     --client openai --model gpt-5.1-codex \
     --job-doc agents/jobs/bug-fixer.md \
     --character-doc agents/chars/strict.md
   gpt-creator list-agents --project /path/to/project
   gpt-creator work-on-tasks --project /path/to/project --agent Fixer-A
   gpt-creator export-agents --project /path/to/project --output agents.json
   gpt-creator import-agents --project /another/project --input agents.json
   ```
- Client-specific agents (OpenAI/Anthropic/xAI) snapshot their API credentials from env vars when created. Ensure the following are populated before `create-agent`, or pass `--allow-missing-key` to stage the agent and wire credentials later (`--json` responses return `{"agent": {...}, "warnings": [...]}`):
  - **OpenAI**: `OPENAI_API_KEY` (optional `OPENAI_API_BASE`, `OPENAI_ORG_ID`)
  - **Anthropic**: `ANTHROPIC_API_KEY` (optional `ANTHROPIC_API_BASE`)
  - **xAI (Grok)**: `GROK_API_KEY` (optional `GROK_API_BASE`, `GROK_ORG_ID`)
  Run `gpt-creator keys set <service>` (`openai`, `anthropic`, `grok`) to store these securely under `~/.config/gpt-creator/api-keys.env`.
- The agent registry is LLM-agnostic. `config/agent_clients.json` accepts adapter metadata so you can wire up any CLI-based client (Codex, Gemini, custom wrappers, etc.) without code changes. Use `adapter: "command"` with a `command` array (placeholders like `{model}` substituted at runtime) and optional env overrides. Point `GC_AGENT_REGISTRY_PATH` at another file when each project needs its own catalog (see `docs/agents.md` for examples).
- Providers/models from the [Catwalk](https://catwalk.charm.sh) catalog are fetched automatically every 24 hours and merged into `list-clients` output. The cache (`~/.config/gpt-creator/cache/llm_catalog.json`) is used offline; `python3 tools/scripts/python/agents_registry.py catalog --refresh` forces an update. Set `GC_AGENT_CATALOG_DISABLE=1` to skip the sync. To persist the catalog into a workspace DB, run `python3 tools/scripts/python/llm_catalog.py --db-path /path/to/tasks.db` (add `--refresh` to bypass the TTL).
- Use `gpt-creator list-llms` to inspect the catalog (filters: `--provider`, `--adapter`, `--source`, `--model`, `--name-like`, `--status`, `--needs-key`). Output highlights API key warnings (disable with `--no-warn-keys`). `gpt-creator check-llms` records which adapters are installed locally; add `--install-missing` to run each stored installer (Claude Code, Gemini CLI, Codestral, DeepSeek, Code Llama, StarCoder2, Qwen Code, etc.) and `--health-check` for lightweight `--version` probes. `gpt-creator install-llm --provider <id> [--run --yes]` runs a single installer; `gpt-creator sync-llms` seeds all registry entries (optionally `--refresh`) and use `--require-adapters --require-keys` (or `--ci`) to fail early in CI when adapters/keys are missing.
- `create-agent --summarize` (and `edit-agent --resummarize --summarize`) call the active LLM to produce concise job/character summaries; override via `GC_AGENT_SUMMARIZER_CLIENT` / `GC_AGENT_SUMMARIZER_MODEL` or `--summarize-client` / `--summarize-model` to pick a cheaper tier.
- Backlog automation notes:
  - `create-jira-tasks` crawls staged docs (PDR, SDS, OpenAPI, SQL, UI samples) to synthesize epics → stories → task JSON under `.gpt-creator/staging/plan/create-jira-tasks/json/` and refreshes the SQLite payload. Progress is tracked in `.gpt-creator/staging/plan/create-jira-tasks/state.json` (use `--force` to restart). The extractor strips Codex code fences, normalizes smart quotes, removes stray comments/trailing commas, and coerces Python-style literals before failing.
  - `migrate-tasks` regenerates `.gpt-creator/staging/plan/tasks/tasks.db` from JSON artifacts without calling Codex; `refine-tasks` streams tasks from `tasks.db`, rehydrates context, refines with Codex, writes to `json/refined`, and updates SQLite per task (use `--force` to reset flags).
  - `create-tasks` snapshots a Jira markdown export into the same database if you maintain backlog files externally.
  - `work-on-tasks` walks tasks with Codex, updating statuses for automatic resume (finishes at `ready-to-review`; follow with `review-tasks` → `qa-tasks`). Use `--fresh` to restart from the first story without clearing progress, `--from-task TASK` (or `--fresh-from`) to rewind to a specific task, and `--force` to reset all statuses to `pending`. `--prepare-prompts` regenerates/publishes prompts when needed. The runner invokes `order-tasks`, hydrates `task_dependencies`, recomputes the cross-story DAG (`global_order` in `tasks.db`), and blocks on merge conflicts, dirty/untracked files, or Prisma schema drift (`prisma migrate diff`).
  - `order-tasks` rehydrates `task_dependencies` and rebuilds the DAG order (`--force` drops/repopulates even when dependencies exist).
  - `backlog` renders summaries: run with no flags (or `--type epics`) for epic tables; `--type stories` for all stories; `--item-children <slug>` to drill into an epic/story; `--task-details <id>` for a single task; `--progress` for an overall bar; `--dag-limit N` for the next `N` globally prioritised tasks (default 20). Use `--project` (or legacy `--root`) to target another workspace.
  - The legacy `iterate` command is deprecated.

### Approved file writers (`gpt-creator apply-block`)

All multi-line edits—manual or Codex-driven—must flow through an approved writer. Husky (`.husky/pre-commit`) and CI (`scripts/guards/no_heredoc.js`, invoked from `.github/workflows/ci.yml`) block heredocs, ellipses, and curl-to-shell pipes before they ever reach `git add`. Use one of:

- `gpt-creator apply-block` (preferred): accepts block JSON from repeated `--file <path>` arguments or stdin, validates allowed writers declared in `gpt-creator.config.json`, writes atomically, stages, optionally runs `pnpm -w fmt`, and commits with an `apply-block:` prefix.
- `tools/scripts/python/write_block.py`: a lighter-weight helper for single overwrites/appends when you do not need staging/commit automation.

A block JSON looks like this (note the explicit newline at the end of `content`):

```json
{
  "id": "admin-allow-instructor-audit",
  "writer": "gpt-creator",
  "mode": "overwrite",
  "path": "apps/server/src/config/adminModules.ts",
  "content": "export const ADMIN_MODULES = new Set<string>(['users','roles','instructor-audit'])\\n"
}
```

Apply it (and optionally batch multiple files) with:

```bash
gpt-creator apply-block \
  --file blocks/admin-allow.json \
  --file blocks/instructor-audit-router.json \
  --fmt \
  --commit
```

Useful flags:

- `--dry-run`, `--json` → validate blocks and print the action plan without touching the working tree.
- `--no-commit` → leave staged changes for a later manual commit.
- `--allow-dirty` → bypass the clean-tree check when you intentionally have local edits.
- `--message "apply-block: custom summary"` → override the default commit message.

When crafting prompts/instructions for Codex or other agents, explicitly require them to (1) emit the block JSON for each file and (2) run `gpt-creator apply-block` instead of heredocs. The guardrails will reject non-compliant commands, so giving the model the sanctioned workflow up front avoids blocked/no-op runs. Agent-specific guardrails can be captured via `create-agent --guardrails` / `edit-agent --guardrails` when you need additional persona-specific instructions.

### Backlog Browser

`gpt-creator backlog` emits structured summaries straight to the console, backed by `.gpt-creator/staging/plan/tasks/tasks.db`. Task listings now surface the persisted DAG order so you can see both per-story positions and the global execution queue.

```bash
$ gpt-creator backlog --project ~/projects/sample-app
Epic ID  Slug        Title                 Stories                                Tasks                                  Progress
-------  ----------  --------------------  -------------------------------------  -------------------------------------  --------
GC-01    gc-api      API Platform          12 stories (6 complete, 3 in-progress)  98 tasks (54 complete, 12 in-progress)  55.1%
GC-02    gc-admin    Admin Console         8 stories (2 complete, 4 in-progress)   74 tasks (28 complete, 20 in-progress)  37.8%
-        (none)      Unassigned backlog    5 stories                               23 tasks                                0.0%
```

- `--type stories` lists every story with its epic, status, and task progress:

  ```bash
  $ gpt-creator backlog --project ~/projects/sample-app --type stories
  Story Slug     Story ID  Title                     Epic               Status       Tasks                                 Progress
  -------------  --------  ------------------------  ------------------ ------------ ------------------------------------ --------
  user-onboard   GC-201    User onboarding flow      API Platform       in-progress  3/8 complete, 2 in-progress, 3 pending 37.5%
  reporting-api  GC-305    Reporting endpoints       API Platform       pending      0/5 complete, 0 in-progress, 5 pending  0.0%
  ```

- `--item-children <id>` accepts an epic slug/key/ID (or a story slug/ID) and prints its immediate children:

  ```bash
  $ gpt-creator backlog --project ~/projects/sample-app --item-children gc-api
  Stories for epic: API Platform [GC-01] (gc-api)
  Story Slug     Title                           Status       Epic            Tasks                                 Progress
  -------------  ------------------------------  -----------  --------------  ------------------------------------  --------
  user-onboard   User onboarding flow            in-progress  API Platform    3/8 complete, 2 in-progress, 3 pending 37.5%
  reporting-api  Reporting endpoints             pending      API Platform    0/5 complete, 0 in-progress, 5 pending 0.0%
  ```

  ```bash
  $ gpt-creator backlog --project ~/projects/sample-app --item-children user-onboard
  Tasks for story: User onboarding flow (user-onboard)
#  Order  Task ID    Title                                                Status      Story Points
  1  12     GC-101     Implement signup API                                 in-progress 3d
  2  15     GC-102     Persist marketing opt-in                             pending     1d
  ```

- `--task-details <id>` prints a single task in detail:

  ```bash
  $ gpt-creator backlog --project ~/projects/sample-app --task-details GC-101
  Task details
  ------------
  Task ID: GC-101
  Story Slug: user-onboard
  Story Title: User onboarding flow
  Epic: API Platform [GC-01]
  Status: in-progress
  Estimate: 3d
  [output truncated for brevity]
  ```

- `--progress` summarises global task progress with a percentage bar:

  ```bash
  $ gpt-creator backlog --project ~/projects/sample-app --progress
  Overall backlog progress
  Tasks complete: 210/300 (70.0%)
  In-progress: 45, Pending: 45
  [######################--------]
  ```

- `--dag-limit N` prints the next `N` tasks using the persisted DAG priority (defaults to 20 when omitted):

  ```bash
  $ gpt-creator backlog --project ~/projects/sample-app --dag-limit 10
  Next tasks by DAG priority
  Order  Story Slug     Task ID    Title                                       Status
  -----  -------------  ---------  ------------------------------------------  ----------
  12     user-onboard   GC-101     Implement signup API                        in-progress
  15     user-onboard   GC-102     Persist marketing opt-in                    pending
  18     reporting-api  GC-305     Expose GET /reports summary endpoint        pending
  [additional backlog rows truncated]
  ```

- Run `gpt-creator create-tasks` or the `create-jira-tasks` + `migrate-tasks` pipeline first; the backlog commands require a populated tasks database. Use `--project` (or backward-compatible `--root`) to target an alternate workspace.

---

### Ordering the DAG queue manually

`work-on-tasks` calls `order-tasks` automatically, but you can rebuild the dependency table and global order without kicking off a Codex run:

```bash
$ gpt-creator order-tasks --project ~/projects/sample-app
[order] Populated 42 dependency row(s).
Task ordering refreshed for /Users/me/projects/sample-app/.gpt-creator/staging/plan/tasks/tasks.db.
```

Use `--force` to clear and repopulate `task_dependencies` before recomputing the order.

---

## Detailed Workflow

Each CLI subcommand is idempotent and can be run independently.

### 1. Scan
```
gpt-creator scan --project /path/to/project
```
- Finds relevant files via fuzzy patterns and writes `.gpt-creator/staging/scan.json` (type, confidence, absolute path).

### 2. Normalize
```
gpt-creator normalize --project /path/to/project
```
- Copies highest-confidence artifacts into canonical locations under `.gpt-creator/staging/inputs/` (`pdr.md`, `sds.md`, `openapi.yaml`, directories like `sql/<artifact>` and `page_samples/<artifact>`).
- Records provenance in `.gpt-creator/staging/plan/provenance.json`.

### 3. Plan
```
gpt-creator plan --project /path/to/project
```
- Parses OpenAPI and SQL to emit:
  - `routes.md`
  - `entities.md`
  - `tasks.json`
  - `PLAN_TODO.md`

### 4. Generate
```
gpt-creator generate all --project /path/to/project
```
- Renders templates into:
  - `apps/api` (NestJS + Prisma stubs)
  - `apps/web` and `apps/admin` (Vue 3 + Vite)
  - `db/` (MySQL init + seed scripts)
  - `docker/` (Dockerfiles, Compose, nginx)
- `.tmpl` files receive `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and an auto-selected MySQL host port (first free port ≥ 3306).
- Outputs are scaffolds; wire business logic, DTOs, and UI flows manually or via Codex responses.
- Add `-m/--model <model-id>` when running `gpt-creator generate ...` to override the `CODEX_MODEL` default for that single invocation; the flag propagates down to `generate api|web|admin` when you target an individual surface.

### 5. Database Helpers
```
gpt-creator db provision   # docker compose up db
gpt-creator db import      # mysql < staging/inputs/sql/*.sql
gpt-creator db seed        # placeholder for custom seeds
```
- The `.env` file already holds the DB host/user/password (including the mapped host port), so these commands work without extra setup.
- `gpt-creator generate-db --sql dump.sql [--model gpt-4.1-mini]` introspects a live MySQL instance when `DATABASE_URL` is reachable and falls back to a Codex-assisted Prisma/TypeORM schema when offline; `--model` controls the Codex tier used during that fallback synthesis.

### 6. Run Stack
```
gpt-creator run up --project /path/to/project
```
- Launches Docker Compose and waits on `/health`, web `/`, admin `/admin/` before returning. Use `run logs`, `run down`, or `run open` for troubleshooting. If port 3306 is taken, the generator already mapped the database to the next free host port and recorded it in `docker/docker-compose.yml`. The web/admin/API services run in watch mode and each container executes `npm install` on startup, mounting node_modules onto named volumes for host editing. The proxy can return a 404 until the Vite servers finish booting; re-run the readiness helper once a minute or hit the direct Vite port (`5173`/`5174`) to confirm it is live.
- The generated `docker/docker-compose.yml` applies conservative `mem_limit`/`mem_reservation` values for each service so runaway containers cannot starve the host. Tweak those limits if your stack needs more RAM.
- Use `gpt-creator refresh-stack --project /path/to/project` when you want to tear everything down, rebuild containers, re-import the SQL dump, and apply seeds in one shot (handy after large migrations or corrupted volumes).

### 7. Testing
`gpt-creator qa` runs the bundled QA checks (web + mobile):
- Web: acceptance (API/web/admin), OpenAPI, Lighthouse, a11y, consent, program-filters, telemetry.
- Mobile: Detox (iOS/Android) and Maestro flows; missing CLIs/configs fail the run unless you pass `--mobile-optional`.
- Configure mobile with `--mobile-dir`, `--detox-config-ios|--detox-config-android`, `--maestro-flows`, `--maestro-device[-ios|-android]` (env: `GC_MOBILE_APP_DIR`, `GC_DETOX_CONFIG_*`, `GC_MAESTRO_*`, `GC_MOBILE_OPTIONAL`).
- Scope to a specific suite with `gpt-creator qa acceptance|openapi|a11y|lighthouse|consent|program-filters|telemetry|mobile|mobile-detox|mobile-maestro`.

`gpt-creator qa-llm` runs an agent-driven QA pass over ready-for-qa tasks:
- Uses the active agent (Codex by default, or `--agent/--model/--client` overrides) to read the latest task summary/notes/outputs and emit a JSON verdict plus issues.
- Scope to a specific task with `--task STORY:POSITION` and point to a custom DB with `--db`.

### Codex Token Usage
```
gpt-creator tokens --project /path/to/project --details
```
- Aggregates Codex token metrics from `.gpt-creator/logs/codex-usage.ndjson`, reporting prompt/completion/total counts and optional per-call breakdowns.
- Add `--json` for machine-readable output or drop `--details` to print only the summary totals.

### 8. Create Tasks (Jira snapshot)
```
gpt-creator create-tasks --project /path/to/project --jira docs/jira.md
```
 - Builds (or refreshes) a project-scoped SQLite database at `.gpt-creator/staging/plan/tasks/tasks.db` with `epics`, `stories`, and `tasks` tables.
 - Preserves story slugs, task ordering, and prior status data unless `--force` is supplied (which regenerates the DB without reusing saved progress).
 - All task attributes (description, assignees, tags, acceptance criteria, dependencies, estimates) are persisted as columns within the `tasks` table for downstream tooling.
 - Captures additional delivery metadata per task (story points, document links, idempotency notes, rate limits, RBAC, messaging/workflows, performance targets, observability, endpoints, sample payloads, and story/epic reference IDs) to support richer automation.
 - Override the Codex tier for this extractor with `-m/--model <model-id>` (defaults to `CODEX_MODEL_NON_CODE` from your environment or config).

### 9. Generate Database Dumps
```
gpt-creator create-db-dump --project /path/to/project
```
- Produces `schema.sql` and `seed.sql` under `.gpt-creator/staging/plan/create-db-dump/sql/`, derived from the SDS (plus optional PDR context).
- Concludes with a Codex review that rewrites both files to ensure data types, keys, and seed rows align; the initial drafts are preserved as `schema.initial.sql` / `seed.initial.sql` backups.
- Use `--dry-run` to preview prompts without calling Codex or `--force` to regenerate dumps after SDS changes.
- Pass `--model <model-id>` when you need this stage to call a different Codex tier than the default non-code model.

### 10. Work on Tasks (resumable Codex loop)
```
export PNPM_HOME="$HOME/.local/share/pnpm"  # keep pnpm toolchain outside the workspace
gpt-creator work-on-tasks --project /path/to/project
```
- Reads pending work directly from the SQLite tasks database and generates Codex prompts per story/task, storing run artifacts in `.gpt-creator/staging/plan/work/runs/<timestamp>/`.
- Expects Codex responses in JSON (plan + `changes` array); diffs and file payloads are applied automatically via `git apply`/direct writes before moving to the next task.
- Saves progress back into the SQLite database (task status + story-level counters); on restart it resumes at the first incomplete story unless `--fresh` is provided, or `--from-task` is used to jump to a specific task.
- Use `--story ST-123` (or slug) to jump to a specific story. The deprecated `--verify` / `--soft-verify` flags are accepted as no-ops for compatibility.
- Cleans prompt/output artifacts after each successful task to keep memory usage low; pass `--keep-artifacts` if you need to retain the raw Codex exchange for auditing.
- Control resource usage with batching/pacing flags: `--batch-size 10` pauses after 10 tasks (resume with the same command) and `--sleep-between 2` inserts a short delay between tasks.
- Tame prompt size with `--context-lines N` (defaults to 400) to include only the tail of the shared context, `--context-file-lines 120` to clip each staged document, or `--context-skip "*.css"` / `--context-none` to drop noisy artifacts altogether; the CLI automatically falls back to a literal tail when the digest cannot be generated.
- Prompts default to the compact instruction/schema block; use `--prompt-expanded` to restore the legacy verbose guidance.
- Sample payloads now default to a short digest; raise `--sample-lines N` to stream the first N minified chunks when you truly need the raw body.
- Surface targeted excerpts from referenced docs/endpoints with `--context-doc-snippets`; the CLI now condenses matches into short summaries with hashes so prompts stay lean.
- Guard prompt budgets up front with `--max-tokens <int>` (hard cap), `--soft-limit <ratio>` (soft budget), `--reserve-output <int>` (completion reservation), and `--stop-on-overbudget[=true|false]` (whether to abort the run when pruning cannot meet the hard cap).
- Tune Codex response sizes by step with `--plan-max-out`, `--status-max-out`, `--patch-max-out`, and the global `--out-hard-cap`; defaults come from `llm.output_limits` in `.gpt-creator/config.yml` (the legacy `--verify-max-out` flag is ignored).
- Large apply diffs are written to `.gpt-creator/artifacts/patches/<task>.patch` and summarised with an `ARTIFACT` line (hunks + lines) so the terminal never truncates critical context.
- Use `--max-tokens-per-stage stage=NUM` together with `--auto-abandon-top-offenders` / `--no-auto-abandon-top-offenders` to carry stage budgets forward from previous runs or opt-out when experimenting.
- Migrations are now two-phased and idempotent: plans land in `.gpt-creator/logs/progress-migration.plan.json`, mappings append to `.gpt-creator/logs/progress-migration.map.ndjson`, and terminal task states are preserved via deterministic `uid` hashes.
- If the migration epoch changes mid-run, the runner records a `blocked-migration-transition` status and halts so you can resume cleanly once the backlog stabilises.
- Empty or invalid agent output during migration is surfaced as `apply-failed-migration-context` (instead of a silent skip) so follow-ups are obvious.
- Historical `verify_status` telemetry is no longer emitted; dashboards should treat verification fields as deprecated.
- `.gpt-creator/staging` context files collapse tables, SQL spam, JSON blobs, and markup dumps automatically; set `GC_CONTEXT_INCLUDE_UI=1` if you need the raw UI assets restored.
- Stray Codex progress files from older runs (e.g., `tmp_*`, `final_*`, `diff*`, `qaDoc.json`) are swept into `.gpt-creator/artifacts/**`; inspect `.gpt-creator/logs/progress-migration.log` for the relocation manifest.
- Use `gpt-creator sweep-artifacts --project /path/to/project` (or pass multiple paths) to run the sweep manually for legacy workspaces or after external scripts deposit artifacts in the repo root.
- Ensure `.gpt-creator/staging/plan/tasks/tasks.db` exists before running `work-on-tasks`; automatic imports from legacy JSON are removed, so run `create-tasks` (or `create-jira-tasks` followed by `migrate-tasks`) to populate the database.
- Run `gpt-creator order-tasks --project /path/to/project` whenever you want to repopulate `task_dependencies` and recompute the DAG order without starting a Codex run (use `--force` to rebuild from scratch).
- When memory pressure is a concern, `--memory-cycle` processes one task per run, prunes caches (Codex artifacts + Docker leftovers), and automatically restarts to continue from the next pending task while keeping peak RSS low.
- Automatically installs Node.js dependencies before the first task when a pnpm workspace or package manifest is present; inspect `/tmp/gc_deps_install.log` if installation fails.
- Review the generated commits/diffs afterwards and run any project-specific checks as needed.

Prompt budgeting defaults live alongside your workspace at `.gpt-creator/config.yml`; set the per-task budgets and runner behaviour once and share them with collaborators:

```yaml
perTask:
  hardLimit: 1000000       # model context (tokens) minus reserved output
  softLimitRatio: 0.85     # percentage of the hard limit to trigger pruning
  minOutputTokens: 1024    # reserved completion tokens
runner:
  stopOnOverbudget: true   # stop the run when pruning still exceeds the hard cap
```

Codex response caps live alongside the prompt budgets:

```yaml
llm:
  output_limits:
    plan: 450     # planning / status turns
    status: 350   # per-task summary line
    patch: 7000   # unified diff/code generation
    hard_cap: 12000
```

Pass any of the `--*-max-out` overrides (or `--out-hard-cap`) when you need temporary headroom; the CLI clamps every call to the lower of the step limit and the hard cap. Legacy `verify`-related keys are ignored.

Stage budgets and offender handling are also declarative:

```yaml
budget:
  per_stage_limits:
    retrieve: 1000000
    plan: 1000000
    patch: 1000000
  offenders:
    window_runs: 10
    top_k: 3
    dominance_threshold: 0.5
    auto_abandon: true
    actions:
      show-file: range-only
      rg: narrow
```

Every Codex phase logs telemetry to `.gpt-creator/logs/codex-usage.ndjson`; the runner aggregates the latest run into `.gpt-creator/logs/budget-report.md`, highlights over-budget stages, and records which remedial actions (`range-only`, `narrow`, `summary`, etc.) were enforced next time.

Temporary overrides are also available via environment variables:

- `GC_PER_TASK_HARD_LIMIT_OVERRIDE`, `GC_PER_TASK_SOFT_RATIO_OVERRIDE`, `GC_PER_TASK_MIN_OUTPUT_OVERRIDE`
- `GC_STOP_ON_OVERBUDGET_OVERRIDE`

Use these when running ad-hoc experiments or tightening budgets in CI without editing the shared config.

### Backlog ETA
```
gpt-creator estimate --project /path/to/project
```
- Add `--recent-tasks COUNT|all` to widen the throughput sample window (defaults to the last 10 tasks). Example: `gpt-creator estimate --project /path/to/project --recent-tasks 25`.
- Aggregates story points for every non-complete task in `.gpt-creator/staging/plan/tasks/tasks.db`.
- Converts the remaining total into a formatted duration using the latest measured throughput from `work-on-tasks` (defaults to the last 10 tasks and falls back to 15 story points per hour, for example `1d 2h 30m`).
- Defaults to the current directory; point `--project` at another workspace when estimating elsewhere.
- Accepts `--recent-tasks COUNT|all` when you need a larger (or full-history) sample window for throughput and token telemetry.
- Exits early with a friendly message if all tasks are already complete.

### 10. Migrate & Refine Tasks
```
gpt-creator migrate-tasks --project /path/to/project [--force]
gpt-creator refine-tasks --project /path/to/project [--force]
```
- `migrate-tasks` rebuilds `.gpt-creator/staging/plan/tasks/tasks.db` from the JSON artifacts generated by `create-jira-tasks`. Use `--force` when you want to discard preserved task status metadata.
- `refine-tasks` streams tasks from `tasks.db` in sequence, rehydrates the story/task JSON, prompts Codex to enrich the task against the staged documentation, writes the refined story JSON to `json/refined`, and synchronizes the updated fields back into SQLite immediately after each successful refinement. Pass `--force` to clear the stored refinement flags and process every task from scratch.

### 11. Iterate (deprecated legacy Jira loop)
```
gpt-creator iterate --project /path/to/project --jira docs/jira.md
```
- The command emits a deprecation warning but still runs the legacy Codex loop. Prefer `create-tasks` + `work-on-tasks` for resumable execution.
- Support for `--model <model-id>` remains; use it to override the legacy loop’s Codex model without mutating global settings.

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `GC_API_BASE_URL` | API base URL used by `run` and manual verification scripts. | `http://localhost:3000/api/v1` |
| `GC_API_HEALTH_URL` | Explicit health endpoint; else derived from base. | `unset` |
| `GC_WEB_URL`, `GC_ADMIN_URL` | Web/Admin URLs surfaced to manual verification scripts. | `http://localhost:8080/`, `http://localhost:8080/admin/` |
| `GC_DB_NAME`, `GC_DB_USER`, `GC_DB_PASSWORD` | Injected into rendered DB templates. | `app`, `app`, `app_pass` |
| `GC_SKIP_PROGRESS_MIGRATION` | Set to `1` to opt out of the automatic sweep that relocates legacy Codex artifacts into `.gpt-creator/`. | `0` |
| `GC_AUTO_REVIEW` | Leave unset (default) or set to `1`/`true`/`on` to let `work-on-tasks` synthesize review artifacts automatically and clear review-required flags; set to `0`/`false` to disable. | `1` |
| `CODEX_BIN`, `CODEX_MODEL` | Override Codex executable/model. | `codex`, `gpt-4.1` (high) |
| `CODEX_MODEL_CODE`, `CODEX_MODEL_NON_CODE` | Stage-specific Codex models (code-writing vs. planning/doc tasks). | `CODEX_MODEL`, `CODEX_MODEL` |
| `CODEX_REASONING_EFFORT_CODE`, `CODEX_REASONING_EFFORT_NON_CODE` | Reasoning effort per stage (both default to `medium`). | `medium`, `medium` |
| `DOCKER_BIN`, `MYSQL_BIN`, `EDITOR_CMD` | Command overrides used within scripts. | `docker`, `mysql`, `code` |
| `GC_REPORTS_ON` | Enable automatic crash/stall issue reporting by default. | `0` |
| `GC_REPORTS_IDLE_TIMEOUT` | Idle detection threshold (seconds) when reporting is enabled. | `1800` |
| `GC_GITHUB_REPO` | GitHub repository (`owner/name`) for automated crash issues. | `unset` |
| `GC_GITHUB_TOKEN` | Personal access token with `repo` scope used to create issues. | `unset` |
| `GC_REPORTER` | Override reporter name recorded in new issue reports. | Git `user.name`/`$USER` |
| `GC_REPORT_ASSIGNEE` | Name recorded when Codex takes ownership of a report. | `GC_REPORTER` |

Run `gpt-creator keys` to see the supported third-party integrations (OpenAI, Jira, GitHub) and store their API keys in `~/.config/gpt-creator/api-keys.env`. Use `gpt-creator keys set <service>` (for example, `openai`, `jira`, or `github`) to add or update credentials without editing files manually.

You can also create `~/.config/gpt-creator/config.sh` to export persistent overrides.

By default `GC_AUTO_REVIEW` is active; the CLI drops automated review stubs under `.gpt-creator/staging/plan/work/runs/<run>/story_*/review/` so long-running automated loops can mark tasks complete without waiting for manual sign-off. Export `GC_AUTO_REVIEW=0` (or `false`) to skip generating these files.

---

## Repository Structure

```
├── bin/gpt-creator           # CLI entrypoint
├── scripts/                  # install/uninstall helpers
├── src/                      # bash libraries used by the CLI
├── templates/                # generator templates (api/web/admin/db/docker)
├── verify/                   # verification scripts (web + mobile)
├── docs/                     # PDR, usage guides, roadmap
└── examples/sample-project/  # Sample artifacts for testing
```

---

## Automatic Issue Reporting

- Pass `--reports-on` to any `gpt-creator` command to capture crashes or long-running stalls as structured issues under `.gpt-creator/logs/issue-reports/`. Each report records a summary, observed behaviour notes, and a priority tag for later triage.
- Stalls are detected when the CLI sees no shell activity for `GC_REPORTS_IDLE_TIMEOUT` seconds (default `1800`). Adjust the threshold with `--reports-idle-timeout <seconds>` or by exporting the environment variable before invoking the CLI.
- Disable reporting for a specific run with `--reports-off`, or enable it globally by exporting `GC_REPORTS_ON=1`.
- Use `gpt-creator reports [--project PATH]` to list captured reports (newest first); pass the slug shown in the list to view the full YAML or add `--open` to launch the entry in `EDITOR_CMD` for further notes. `gpt-creator reports backlog` filters to open issues and shows a popularity score (likes + comments) so maintainers can prioritise high-signal bugs quickly.
- Use `gpt-creator reports work <slug>` to hand an issue to Codex: the CLI prepares a focused prompt, records the assignee, and directs Codex to create a branch, implement the fix, commit, and push (unless `--no-push` is provided).
- Export `GC_GITHUB_REPO` (`owner/name`) and `GC_GITHUB_TOKEN` (PAT with `repo` scope) to have gpt-creator raise GitHub issues automatically whenever a crash/stall report is captured; the local YAML is still written for offline reference. GitHub issues now include the CLI version plus a SHA-256 watermark so maintainers can confirm the report originated from an unmodified gpt-creator binary.
- Maintainers can run `gpt-creator reports audit` to list GitHub issues created by `--reports-on`, verify their watermark/signature against the trusted digest manifest, and optionally close suspicious entries with an "Authenticity failed" comment. Trusted digests default to `config/release-digests.json`; pass `--digests FILE` or inline overrides like `--allow 0.2.0=<sha256>` for bespoke builds.
- Use `gpt-creator reports auto` to sweep every open issue reported by your account (or a specified `--reporter`) and let Codex resolve them sequentially, respecting `--no-push`/`--prompt-only` flags.
- Crash details continue to collect in `.gpt-creator/logs/crash.log`; enabling reports mirrors those failures into per-run issue files so the repo owner can follow up asynchronously.

## Troubleshooting

| Symptom | Suggested Action |
|---------|------------------|
| `codex` binary not found | Install Codex CLI or set `CODEX_BIN` to a compatible wrapper. |
| `create-jira-tasks` stops with “Failed to parse Codex JSON output” | Check `.gpt-creator/staging/plan/create-jira-tasks/output/*.raw.txt` for the offending response. The CLI auto-cleans common issues (code fences, smart quotes, comments, trailing commas, Python-style literals); if it still fails, rerun with `--force` after pruning the bad snippet or adjust the prompts/docs. |
| Legacy verification script exits with status 3 | Install the missing dependency (`npx`, `pa11y`, `lighthouse`, `docker`) if you maintain those legacy checks. |
| Docker stack fails health check | Run `gpt-creator run logs`, inspect `docker/docker-compose.yml`, confirm environment variables. |
| Normalization misses a file | Place the artifact under a clearer name or rerun `gpt-creator scan` with the file already present. |

---

## Contributing

1. Fork and clone the repository.
2. Create a topic branch: `git checkout -b feature/my-change`.
3. Make changes focusing on the requested code updates.
4. Coordinate QA using your team's processes; gpt-creator does not run tests.
5. Submit a pull request referencing relevant PDR goals/requirements.

See `docs/ROADMAP.md` for upcoming milestones.

---

## License

MIT — see [`LICENSE`](LICENSE).
