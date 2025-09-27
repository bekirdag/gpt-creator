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
- **Iteration helpers**: `create-tasks` turns Jira markdown into per-story JSON (with manifest + resumable progress) and `work-on-tasks` executes story chunks via Codex. The legacy `iterate` command is deprecated.

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

---

## Quick Start

1. **Collect artifacts** into a folder (PDR/SDS docs, `openapi.yaml`, SQL dumps, HTML samples, etc.).
2. **Run the bootstrap command**:
   ```bash
   gpt-creator create-project /path/to/project
   ```
   - A `.gpt-creator` workspace is created under the project root.
   - Generated code lands in `/apps/api`, `/apps/web`, `/apps/admin`, `/db`, `/docker`.
   - A `.env` file with random database credentials is created automatically; reuse it for local scripts and CI secrets.
   - The command finishes after acceptance checks (`verify acceptance`); run `verify all` to execute the extended NFR suite.
3. **Inspect outputs**:
   - `.gpt-creator/staging/discovery.yaml` for scan results
   - `.gpt-creator/staging/plan/` for route/entity summaries and tasks
4. **Work Jira backlog** (optional):
   ```bash
   gpt-creator create-tasks --project /path/to/project --jira docs/jira.md
   gpt-creator work-on-tasks --project /path/to/project
   ```
   - `create-tasks` snapshots the Jira markdown into per-story JSON under `.gpt-creator/staging/plan/tasks/`.
   - `work-on-tasks` walks those stories with Codex, resuming from prior runs as needed.
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

### 8. Create Tasks (Jira snapshot)
```
gpt-creator create-tasks --project /path/to/project --jira docs/jira.md
```
- Parses Jira markdown once and writes per-story JSON files under `.gpt-creator/staging/plan/tasks/stories/`.
- Produces a manifest (`manifest.json`) capturing story order, hashes, and relative paths. Existing story files are skipped unless the content hash changes (or `--force` is supplied).
- Progress is durable: if conversion is interrupted, rerunning the command resumes from the manifest and only rebuilds changed stories.

### 9. Work on Tasks (resumable Codex loop)
```
gpt-creator work-on-tasks --project /path/to/project
```
- Reads the manifest from `create-tasks` and generates Codex prompts per story/task, storing run artifacts in `.gpt-creator/staging/plan/work/runs/<timestamp>/`.
- Expects Codex responses in JSON (plan + `changes` array); diffs and file payloads are applied automatically via `git apply`/direct writes before moving to the next task.
- Saves progress to `.gpt-creator/staging/plan/work/state.json`; on restart it resumes at the first incomplete story unless `--fresh` is provided.
- Use `--story ST-123` (or slug) to jump to a specific story and `--no-verify` to skip the automatic `verify all` invocation after a successful run.
- Cleans prompt/output artifacts after each successful task to keep memory usage low; pass `--keep-artifacts` if you need to retain the raw Codex exchange for auditing.
- Control resource usage with batching/pacing flags: `--batch-size 10` pauses after 10 tasks (resume with the same command) and `--sleep-between 2` inserts a short delay between tasks.
- When memory pressure is a concern, `--memory-cycle` processes one task per run, prunes caches (Codex artifacts + Docker leftovers), and automatically restarts to continue from the next pending task while keeping peak RSS low.
- Automatically installs Node.js dependencies before the first task when a pnpm workspace or package manifest is present; inspect `/tmp/gc_deps_install.log` if installation fails.
- Review the generated commits/diffs afterwards and run project tests as needed.

### 10. Iterate (deprecated legacy Jira loop)
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
