# Rendering Safe SQL Migrations

`tools/scripts/python/render_sql.py` converts ALTER TABLE statements that use `ADD COLUMN IF NOT EXISTS`, `ADD KEY`, and `ADD CONSTRAINT` into idempotent SQL blocks backed by INFORMATION_SCHEMA checks. Use it before committing ADM-06 (and similar) migrations so Codex no longer has to reason about guard clauses or manual `IF NOT EXISTS` branching.

## Workflow

1. Author or update the raw template (for example `sql/migrations/adm-06/events_template.sql`) using the more ergonomic `ADD COLUMN IF NOT EXISTS` syntax.
2. Run `render_sql.py` to turn that template into a deployment-ready script.
3. Review the generated SQL to make sure the dynamic blocks capture all additions.
4. Commit the rendered file alongside the template so future runs can diff safely.

## Command

```
python3 tools/scripts/python/render_sql.py <src-template.sql> <dest.sql> <DB_NAME> <DB_USER> <DB_PASSWORD>
```

- `<src-template.sql>`: file containing the non-idempotent ALTER statements.
- `<dest.sql>`: output path for the rewritten SQL (directories are created automatically).
- `<DB_NAME>` / `<DB_USER>` / `<DB_PASSWORD>`: substitution tokens for `{{DB_NAME}}`, `{{DB_USER}}`, and `{{DB_PASSWORD}}` that appear in most seed/migration templates.

The script performs three key tasks:

1. Replaces the `{{DB_*}}` placeholders with the provided arguments.
2. Rewrites every compound `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` clause into a prepared-statement block guarded by queries against `INFORMATION_SCHEMA.COLUMNS`, `STATISTICS`, or `TABLE_CONSTRAINTS`.
3. Preserves any leftover clauses (renames, drops, etc.) as-is at the end of the statement so they still execute when appropriate.

## Example (ADM-06 events migration)

```bash
python3 tools/scripts/python/render_sql.py \
  sql/migrations/adm06/events_template.sql \
  sql/migrations/adm06/events.sql \
  yoga_db yoga_app yoga_pass
```

Use this output in the Prisma migration step, ensuring the deployment can be re-run in staging/UAT without failing when a column already exists.

## Why this saves tokens

- The ADM-06 tasks often ask Codex to “make the migration idempotent.” Instead of reasoning about `IF EXISTS` queries each run, the script guarantees consistency, reducing the amount of SQL the agent needs to generate.
- Because the output is deterministic, prompts can reference the rendered SQL directly, avoiding long in-prompt SQL rewrites that consume thousands of tokens.
