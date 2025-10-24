# Handling Missing Referenced Docs

`gpt-creator work-on-tasks` sometimes references documentation that has not been created yet. When that happens, add a lightweight placeholder so the automation can proceed without project-specific assumptions.

## Workflow

1. Determine the path mentioned in the task or checklist.
2. Run `scripts/create-doc-placeholder.sh <path> --owner "Team or Role" --summary "Purpose"` (see usage below).
3. Commit the generated placeholder along with the changes that referenced it.

The helper keeps everything project-agnostic: it accepts any path, creates parent directories as needed, and emits a minimal template with ownership, date, and TODO notes.

## Script Usage

```bash
scripts/create-doc-placeholder.sh docs/delivery/example/checklist.md \
  --owner "Release PM" \
  --summary "Guardrail release checklist"
```

Flags:

- `--owner` (required): team/role responsible for the future content.
- `--summary` (optional): short description of what belongs in the document.
- `--date YYYY-MM-DD` (optional): override the auto-generated ISO date.

The script picks sensible defaults based on file extension (Markdown, CSV, JSON, SQL, ICS, plain text). If the target already exists, it leaves it untouched and prints a reminder.

Using this approach prevents missing-doc blockers while keeping the repository portable across projects.
