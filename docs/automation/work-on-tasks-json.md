# Work-on-Tasks Response Format

Codex responses for `gpt-creator work-on-tasks` now use a lightweight textual contract instead of the legacy JSON envelope. Structure each reply as four short sections:

- **Plan** — bullet the concrete steps you will take. Keep each item tight so downstream logs remain scannable.
- **Focus** — list the files or symbols you are touching. This keeps reviewers aware of the blast radius without relying on machine-parsed JSON.
- **Commands** — enumerate the shell commands you will execute. Use `bash` when you need to write files; keep commands idempotent so retries are safe.
- **Notes** — capture blockers, follow-ups, and verification results. Mention any tests or linters you run here.

Everything else is optional. You may include a small ```diff``` fence when it helps explain an edit, but the automation no longer requires diffs or strict JSON. The runner parses these sections directly and executes the listed commands, prioritising successful task completion over bookkeeping.
