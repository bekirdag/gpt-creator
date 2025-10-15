# gpt-creator

`gpt-creator` is an opinionated, AI-assisted project bootstrapper. It ingests heterogeneous discovery artifacts such as Product Requirement Docs (PDR), System Design Specs (SDS), RFPs, OpenAPI specs, SQL dumps, Mermaid diagrams, and HTML/CSS samples, then normalizes, plans, generates, runs, and verifies a full local stack (NestJS API + Prisma + MySQL + Vue 3 web/admin + Docker) in a single workflow.

The implementation follows the Product Definition & Requirements (PDR v0.2) in `docs/PDR.md`. This README explains how the tool is structured, the dependencies you need, how to install it, and how to drive each phase end-to-end.

---

## Features at a Glance

- **Single-command bootstrap**: `gpt-creator create-project <path>` orchestrates scan → normalize → plan → generate → db → run, then runs acceptance verification. Additional NFR checks remain available via `verify all`.
- **Fuzzy discovery**: Locates artifacts across diverse naming conventions (e.g., `*PDR*.md`, `openapi.*`, `sql_dump*.sql`, `*.mmd`, HTML/CSS samples).
- **Deterministic staging**: Copies inputs into `.gpt-creator/staging/inputs/` with canonical names and provenance tracking.
- **Planning outputs**: Produces route/entity summaries and task hints under `.gpt-creator/staging/plan/` as scaffolding for further design work.
- **Template-driven generation**: Renders baseline NestJS, Vue 3, Prisma, and Docker scaffolds into `/apps/**` and `/docker`, ready for manual extension or Codex-driven augmentation.
- **Verification toolkit**: Ships scripts for acceptance, OpenAPI validation, accessibility, Lighthouse, consent, and program-filter checks that you can run on demand.
- **Doc synthesis**: `create-pdr` converts the staged RFP into a multi-level Product Requirements Document (PDR) by iteratively asking Codex to draft the table of contents, sections, and detailed subsections. `create-sds` continues the loop, transforming the staged PDR into a System Design Specification that drills from architecture overview down to low-level operational detail.
- **Database synthesis**: `create-db-dump` reads the SDS (and PDR context) to draft a full MySQL schema plus production-grade seed data, then reviews both dumps for consistency before storing them under `.gpt-creator/staging/plan/create-db-dump/sql/`.
- **Iteration helpers**: `create-jira-tasks` mines staged docs into JSON story/task bundles, `migrate-tasks` pushes those artifacts into the SQLite backlog, `refine-tasks` enriches tasks in-place from the database, `create-tasks` converts existing Jira markdown, and `work-on-tasks` executes/resumes backlog items. The legacy `iterate` command is deprecated.
- **Token tracking**: `tokens` summarises Codex usage stored in `.gpt-creator/logs/codex-usage.ndjson` so you can translate model activity into spend.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| macOS (primary target) or Linux | Windows is untested. |
| [Docker](https://docs.docker.com/), `docker compose` | Needed for the `run` and verification phases. |
| Node.js ≥ 20 | Required for generated NestJS / Vite projects. |
| `pnpm` | Used by generated clients; install via `corepack enable`. |
| MySQL client (`mysql`) | Used for import/health checks. |
| Codex CLI (`codex` or compatible) | AI generation/iteration driver. |
| `OPENAI_API_KEY` environment variable | Passed to Codex for model access. |
| Optional: `npx`, `jq`, `curl`, `pa11y`, `lighthouse` | Automatically invoked by verification scripts when available. |

> **Tip:** Run `./scripts/install.sh --skip-preflight` if you simply want to copy binaries without the strict prerequisite checks. The default preflight ensures everything above is present.

---

## Installation

### Option 0 — One-liner install (curl)

```bash
curl -fsSL https://raw.githubusercontent.com/bekirdag/gpt-creator/main/scripts/install-latest.sh | bash
```

Add extra flags after `--`, e.g. `... | bash -s -- --prefix /opt --force --skip-preflight`. The script clones the repository into a temporary directory, runs the standard installer (`scripts/install.sh --prefix /usr/local` by default), then removes the temporary files. Requires `git` and `mktemp` on your `PATH`.

### Option 1 — System-wide install (macOS)

```bash
./scripts/install.sh --prefix /usr/local
```

Installs:
- Executable symlink: `/usr/local/bin/gpt-creator`
- Library assets: `/usr/local/lib/gpt-creator`
- Shell completions: zsh/bash/fish (if writable)

Use `--skip-preflight` to bypass dependency checks or `--force` to replace an existing symlink.

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
   - The command finishes after acceptance checks (`verify acceptance`); run `verify all` to execute the extended NFR suite.
   - Templates live under `project_templates/`. Add subdirectories (optionally with `tags.txt` or `template.json`) to seed new projects; `--template auto` attempts to match the staged RFP/PDR, or pass `--template <name>` / `--skip-template` to override.

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
   ```
  - `create-jira-tasks` crawls the staged docs (PDR, SDS, OpenAPI, SQL, UI samples) to synthesize epics → user stories → detailed task JSON under `.gpt-creator/staging/plan/create-jira-tasks/json/` and refreshes the consolidated payload/SQLite database. Progress is recorded in `.gpt-creator/staging/plan/create-jira-tasks/state.json` (use `--force` to restart).
  - `migrate-tasks` regenerates `.gpt-creator/staging/plan/tasks/tasks.db` directly from the JSON artifacts — ideal when you want to sync the DB without re-running Codex.
  - `refine-tasks` streams tasks from `tasks.db` one at a time, rehydrates the original story context, runs Codex against the staged docs, writes the refined JSON to `json/refined`, and updates the task row in SQLite immediately after each successful response. Use `--force` to reset refinement flags and reprocess every task.
  - `create-tasks` snapshots a Jira markdown export into the same database if you already maintain backlog files.
  - `work-on-tasks` walks tasks from the database with Codex, updating statuses so reruns resume automatically.
  - The legacy `iterate` command is deprecated.

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
- Copies highest-confidence artifacts into canonical locations under `.gpt-creator/staging/inputs/` (`pdr.md`, `sds.md`, `openapi.yaml`, `sql/…`, `page_samples/…`).
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

### 5. Database Helpers
```
gpt-creator db provision   # docker compose up db
@gpt-creator db import      # mysql < staging/inputs/sql/*.sql
@gpt-creator db seed        # placeholder for custom seeds
```
- The `.env` file already holds the DB host/user/password (including the mapped host port), so these commands work without extra setup.

### 6. Run Stack
```
gpt-creator run up --project /path/to/project
```
- Launches Docker Compose and waits on `/health`, web `/`, admin `/admin/` before returning. Use `run logs`, `run down`, or `run open` for troubleshooting. If port 3306 is taken, the generator already mapped the database to the next free host port and recorded it in `docker/docker-compose.yml`. The web/admin/API services run in watch mode and each container executes `npm install` on startup, mounting node_modules onto named volumes for host editing. The proxy can return a 404 until the Vite servers finish booting; re-run the readiness helper once a minute or hit the direct Vite port (`5173`/`5174`) to confirm it is live.
- The generated `docker/docker-compose.yml` applies conservative `mem_limit`/`mem_reservation` values for each service so runaway containers cannot starve the host. Tweak those limits if your stack needs more RAM.
- Use `gpt-creator refresh-stack --project /path/to/project` when you want to tear everything down, rebuild containers, re-import the SQL dump, and apply seeds in one shot (handy after large migrations or corrupted volumes).

### 7. Verify
```
gpt-creator verify all --project /path/to/project
```
Runs:
- `verify/acceptance.sh` (HTTP health)
- `verify/check-openapi.sh` (swagger-cli or docker fallback)
- `verify/check-a11y.sh` (pa11y)
- `verify/check-lighthouse.sh`
- `verify/check-consent.sh`
- `verify/check-program-filters.sh`

Scripts exit with `0` on success, `3` when a dependency is missing, or non-zero on failure.

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

### 9. Generate Database Dumps
```
gpt-creator create-db-dump --project /path/to/project
```
- Produces `schema.sql` and `seed.sql` under `.gpt-creator/staging/plan/create-db-dump/sql/`, derived from the SDS (plus optional PDR context).
- Concludes with a Codex review that rewrites both files to ensure data types, keys, and seed rows align; the initial drafts are preserved as `schema.initial.sql` / `seed.initial.sql` backups.
- Use `--dry-run` to preview prompts without calling Codex or `--force` to regenerate dumps after SDS changes.

### 10. Work on Tasks (resumable Codex loop)
```
export PNPM_HOME="$HOME/.local/share/pnpm"  # keep pnpm toolchain outside the workspace
gpt-creator work-on-tasks --project /path/to/project
```
- Reads pending work directly from the SQLite tasks database and generates Codex prompts per story/task, storing run artifacts in `.gpt-creator/staging/plan/work/runs/<timestamp>/`.
- Expects Codex responses in JSON (plan + `changes` array); diffs and file payloads are applied automatically via `git apply`/direct writes before moving to the next task.
- Saves progress back into the SQLite database (task status + story-level counters); on restart it resumes at the first incomplete story unless `--fresh` is provided.
- Use `--story ST-123` (or slug) to jump to a specific story and `--no-verify` to skip the automatic `verify all` invocation after a successful run.
- Cleans prompt/output artifacts after each successful task to keep memory usage low; pass `--keep-artifacts` if you need to retain the raw Codex exchange for auditing.
- Control resource usage with batching/pacing flags: `--batch-size 10` pauses after 10 tasks (resume with the same command) and `--sleep-between 2` inserts a short delay between tasks.
- When memory pressure is a concern, `--memory-cycle` processes one task per run, prunes caches (Codex artifacts + Docker leftovers), and automatically restarts to continue from the next pending task while keeping peak RSS low.
- Automatically installs Node.js dependencies before the first task when a pnpm workspace or package manifest is present; inspect `/tmp/gc_deps_install.log` if installation fails.
- Review the generated commits/diffs afterwards and run project tests as needed.

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

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `GC_API_BASE_URL` | API base URL used by `run`/`verify`. | `http://localhost:3000/api/v1` |
| `GC_API_HEALTH_URL` | Explicit health endpoint; else derived from base. | `unset` |
| `GC_WEB_URL`, `GC_ADMIN_URL` | Web/Admin URLs used during verification. | `http://localhost:8080/`, `http://localhost:8080/admin/` |
| `GC_DB_NAME`, `GC_DB_USER`, `GC_DB_PASSWORD` | Injected into rendered DB templates. | `app`, `app`, `app_pass` |
| `CODEX_BIN`, `CODEX_MODEL` | Override Codex executable/model. | `codex`, `gpt-5-high` |
| `DOCKER_BIN`, `MYSQL_BIN`, `EDITOR_CMD` | Command overrides used within scripts. | `docker`, `mysql`, `code` |

You can also create `~/.config/gpt-creator/config.sh` to export persistent overrides.

---

## Repository Structure

```
├── bin/gpt-creator           # CLI entrypoint
├── scripts/                  # install/uninstall helpers
├── src/                      # bash libraries used by the CLI
├── templates/                # generator templates (api/web/admin/db/docker)
├── verify/                   # verification scripts
├── docs/                     # PDR, usage guides, roadmap
└── examples/sample-project/  # Sample artifacts for testing
```

---

## Troubleshooting

| Symptom | Suggested Action |
|---------|------------------|
| `codex` binary not found | Install Codex CLI or set `CODEX_BIN` to a compatible wrapper. |
| Verification scripts skip with exit 3 | Install the missing dependency (`npx`, `pa11y`, `lighthouse`, `docker`). |
| Docker stack fails health check | Run `gpt-creator run logs`, inspect `docker/docker-compose.yml`, confirm environment variables. |
| Normalization misses a file | Place the artifact under a clearer name or rerun `gpt-creator scan` with the file already present. |

---

## Contributing

1. Fork and clone the repository.
2. Create a topic branch: `git checkout -b feature/my-change`.
3. Make changes and add tests if applicable.
4. Run the verification suite against the sample project.
5. Submit a pull request referencing relevant PDR goals/requirements.

See `docs/ROADMAP.md` for upcoming milestones.

---

## License

MIT — see [`LICENSE`](LICENSE).
