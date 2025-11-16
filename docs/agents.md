# Agents

gpt-creator now supports reusable agent personas so long-running projects can
describe their preferred client, model, job role, and character voice once and
reuse it across every `work-on-tasks` run.

## Storage & migrations

- Agents live inside the same `tasks.db` SQLite database as your backlog. The
  schema is created automatically the next time `create-tasks`, `create-jira-tasks`,
  or any agent command touches the database.
- Existing workspaces: rerun `gpt-creator create-tasks --project <dir>` (or any
  agent CLI command) once to create the `agents` table.
- All documents are stored inline with SHA-256 digests; the CLI never logs raw
  bodies unless you explicitly pass `--full`.
- When you select clients such as OpenAI/Anthropic/xAI, their API credentials
  (key/base/org) are pulled from the corresponding env vars and persisted with
  the agent record so the CLI knows which endpoint to use. Ensure the required
  env vars are set before creating the agent:
  - OpenAI: `OPENAI_API_KEY` (optional `OPENAI_API_BASE`, `OPENAI_ORG_ID`)
  - Anthropic: `ANTHROPIC_API_KEY` (optional `ANTHROPIC_API_BASE`)
  - xAI: `GROK_API_KEY` (optional `GROK_API_BASE`, `GROK_ORG_ID`)
  Run `gpt-creator keys set <service>` (e.g. `openai`, `anthropic`, `grok`) to
  store these securely in `~/.config/gpt-creator/api-keys.env`.

## Client registry & adapters

- Available clients/models live in `config/agent_clients.json`. Override the
  path with `GC_AGENT_REGISTRY_PATH` when you need project-specific catalogs.
- Each client entry can now supply `adapterConfig` metadata. The built-in
  entries (OpenAI/Anthropic/xAI) keep their previous behaviour, but you can add
  new providers without touching the codebase by pointing to their CLI.
- Use the `command` adapter when a provider exposes a CLI that reads prompts
  from stdin and writes the assistant response to stdout. Example entry:

```jsonc
{
  "gemini": {
    "label": "Google Gemini CLI",
    "adapter": "command",
    "adapterConfig": {
      "command": ["gemini", "chat", "--model", "{model}"],
      "env": {
        "GEMINI_API_KEY": "${GEMINI_API_KEY}"
      },
      "promptTemplate": "{system}\n\n{messages}",
      "messageJoiner": "\n\n",
      "timeoutSeconds": 120
    },
    "apiKeyEnv": "GEMINI_API_KEY",
    "defaultModel": "gemini-1.5-pro",
    "models": ["gemini-1.5-pro", "gemini-1.5-flash"]
  }
}
```

- The `{model}` placeholder is replaced with the resolved model name. Provide
  `promptTemplate`/`messageJoiner` when the CLI expects a custom format; the
  default is `"{system}\n\n{messages}"` joined with blank lines. Any `env`
  entries can reference other environment variables via `${VAR_NAME}`; the
  factory also injects `apiKeyEnv`/`apiBaseEnv`/`orgEnv` automatically when
  those variables are set in your shell.
- Future adapters can be contributed by dropping a new entry into the registry,
  allowing agents to target bespoke CLIs or wrapper scripts for any LLM.
- The CLI automatically syncs the [Catwalk](https://catwalk.charm.sh) provider
  catalog once every 24 hours (cached at
  `~/.config/gpt-creator/cache/llm_catalog.json`). `python3 scripts/python/agents_registry.py
  catalog --refresh` forces an immediate refresh, while setting
  `GC_AGENT_CATALOG_DISABLE=1` skips the sync entirely (useful for air-gapped
  hosts). Offline runs fall back to the cached JSON so `list-clients` continues
  to show available providers/models even when Catwalk is unreachable. When you
  want the synced catalog written straight into `tasks.db`, run
  `python3 scripts/python/llm_catalog.py --refresh --db-path /path/to/tasks.db`
  (the same helper accepts `--json` if you want to inspect the full payload).

## CLI commands

```bash
# Create an agent
gpt-creator create-agent \
  --name Fixer-A \
  --client openai \
  --model gpt-5.1-codex \
  --job-doc ./agents/jobs/bug-fixer.md \
  --character-doc ./agents/chars/strict.md \
  --tags "fixer,strict"

# List (table output)
gpt-creator list-agents --client openai

# Show JSON (without doc bodies)
gpt-creator show-agent --name Fixer-A --json

# Edit partial fields (resummarize derives new summaries from stored docs)
gpt-creator edit-agent --name Fixer-A --model gpt-5-codex --resummarize

# Soft delete (can be reinstated via edit --active true)
gpt-creator delete-agent --name Fixer-A

# Hard delete
gpt-creator delete-agent --name Fixer-A --force
```

- `--json` now returns `{"agent": {...}, "warnings": [...]}` so automation can
  reuse the payload while still surfacing credential reminders. Older scripts
  that expect the bare agent payload should read `payload["agent"]` when the
  top-level keys include `warnings`.
- `--verbose` prints file paths and progress without showing doc bodies.
- `gpt-creator list-agents --tag bugfix` filters by tag; repeat `--tag` for AND
  semantics.
- `--summarize` lets the active LLM generate concise job/character summaries
  when creating/editing agents (falls back to deterministic truncation if the
  LLM call fails). Override the summarizer target via `--summarize-client` /
  `--summarize-model` or the environment variables
  `GC_AGENT_SUMMARIZER_CLIENT` / `GC_AGENT_SUMMARIZER_MODEL` when needed.
- When you need to create an agent before API keys are available, pass
  `--allow-missing-key`; the CLI records the agent while warning that
  credentials are still required. Pair this with
  `gpt-creator list-llms --needs-key` or `check-llms` to track which providers
  still lack configured secrets.
- Pass `--guardrails` (plain text), `--guardrails-file`, and `--guardrails-dir`
  to capture persona-specific guardrails (e.g., compliance reminders). The CLI
  concatenates text + file contents (directories are scanned recursively) before
  storing the guardrails. Use `edit-agent --guardrails ""` with no files/dirs to
  clear them entirely.
- Use `gpt-creator export-agents` / `import-agents` to move personas between
  projects. Exports produce JSON (include doc bodies/guardrails by default); the
  import command handles collisions (`--on-collision skip|overwrite|rename`) and
  skips API keys unless `--include-keys` is passed.
- Deactivate/reactivate via `edit-agent --active false|true`. Soft-deleted agents
  remain in the database until you run `delete-agent --force`.
- Inspect the synced LLM catalog via `gpt-creator list-llms` (filters: `--provider`,
  `--adapter`, `--source`, `--model`, `--name-like`, `--status`, `--needs-key`,
  plus `--json` for scripting). The table highlights missing API keys so you
  know when to run
  `gpt-creator keys set <provider>`; hide this column via `--no-warn-keys`. Run
  `gpt-creator check-llms` whenever you want to verify that any CLI adapters
  (Codex, Gemini, custom `command` entries) are installed on the current machine.
  The command records the `installed/missing` status and hint in `tasks.db`, so
  subsequent `list-llms` runs surface which personas are runnable without extra
  setup. Pass `--install-missing` to `check-llms` and it will run the stored
  install command (per OS) for each missing adapter, so teams can codify their
  preferred setup instructions for Claude Code, Codestral, DeeSeek, Gemini CLI,
  Qwen Code, StarCoder2, Code Llama, etc. Combine with `--health-check` to run
  a lightweight `--version` probe for installed CLIs (when credentials are set)
  before launching a long run.
- Use `gpt-creator install-llm --provider <id>` when you want to inspect the
  stored install script for a single provider (commands are shown for each OS).
  Add `--run --yes` to execute it immediately once you trust the steps, or
  `--os macos|windows` when you need to install tooling for another environment.
- Run `gpt-creator sync-llms` in a fresh repository or CI task to pre-populate
  `.gpt-creator/staging/plan/tasks/tasks.db` with every provider/model defined
  in `config/agent_clients.json` so `list-llms`/`check-llms` work before any
  agents exist. Add `--refresh` to fetch the latest Catwalk catalog at the same
  time.

## Using agents

- Run `gpt-creator work-on-tasks --agent Fixer-A` to reuse the stored persona.
- The CLI selects the agent’s client/model and injects the job + character docs
  at the top of each Codex prompt (plus guardrails). Logs only mention the agent
  name/client/model, not the raw documents.
- If you pass `--agent <model-id>` and no matching agent exists, legacy behaviour
  remains: the CLI treats it as a direct Codex model override.

## Logging & safeguards

- Creation/edit/delete commands never log doc bodies; only file paths and hashed
  summaries are printed (add `--verbose` for extra context).
- `work-on-tasks` logs the agent name/client/model when active, allowing you to
  audit which persona was used for each run.

For more context, see README’s “Agents” section or run `gpt-creator <command> --help`.
