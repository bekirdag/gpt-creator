# Release Checklist – Multi-Agent Update

Use this checklist before tagging/releases that include the multi-agent
feature. It captures the verification plan from Step 13 so we consistently
exercise the new flows and document upgrade steps.

## Automated Tests

- [ ] `pnpm test` (Vitest suite) – confirm JS/TS tooling still works.
- [ ] `python3 -m pytest test/python` – runs the agent repository/service/CLI
      tests plus existing Python utilities.
- [ ] Optional: targeted dry-run for `work-on-tasks --agent` (see Manual QA).

## Manual QA

- [ ] Create a sample project (or reuse `.gpt-creator/examples`) and run:
      - `gpt-creator create-agent ...`
      - `gpt-creator list-agents`, `show-agent --json`, `edit-agent --resummarize`,
        `delete-agent` (soft + `--force`)
- [ ] Verify `work-on-tasks --agent <name>` injects the persona header (check
      `.gpt-creator/staging/plan/work/.../prompts/*.md`) and logs the agent
      selection.
- [ ] Regression: `work-on-tasks --agent gpt-4` when the agent doesn’t exist
      → legacy “raw model override” path still works (warning emitted).
- [ ] Soft deleted agent cannot be selected (expect validation error).

## Regression Matrix

| Scenario | Expected |
| --- | --- |
| `--agent NAME` (active) | Persona applied, env vars populated, logs show agent |
| `--agent NAME` (inactive / missing) | Validation failure; raw override fallback only when no record |
| `--agent MODEL` (no record) | Legacy model override path |
| No `--agent` flag | Behavior identical to previous releases |

## Migration Notes

- Existing workspaces: run any agent command or `create-tasks` once so the new
  `agents` table is created inside `.gpt-creator/staging/plan/tasks/tasks.db`.
- Doc size limit is 512 KB per job/character doc; the CLI surfaces a validation
  error when exceeded.

## Release Notes (suggested snippet)

```
- Added multi-agent support: create/list/show/edit/delete agents stored in the
  project’s tasks.db and reuse them via `work-on-tasks --agent NAME`.
- Agents pin a client/model/job/character persona and inject a structured header
  into each Codex prompt. Legacy `--agent MODEL` overrides still work.
- Added documentation under docs/agents.md plus CLI help (`gpt-creator create-agent --help`).
```

## Post-Release Monitoring

- Watch logs for `Agent '<name>' not found` warnings.
- Monitor token usage by client; adjust registry max-context/out overrides if
  models routinely exceed caps.
- Collect feedback on additional adapters (Anthropic/xAI) and guardrail
  customization.
