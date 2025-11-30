# Handling Missing Referenced Docs

`gpt-creator work-on-tasks` sometimes references documentation that has not been created yet. When that happens, add a lightweight placeholder so the automation can proceed without project-specific assumptions and the agent avoids spending thousands of tokens drafting entire files from scratch.

## Workflow

1. Determine the path mentioned in the task or checklist.
2. Run `tools/scripts/create-doc-placeholder.sh <path> --owner "Team or Role" --summary "Purpose"` (see usage below; `scripts/` symlink still works for legacy callers).
3. Patch the generated stub instead of writing the whole document inline.
4. Commit the placeholder along with the changes that referenced it.

The helper keeps everything project-agnostic: it accepts any path, creates parent directories as needed, and emits a minimal template with ownership, date, and TODO notes. Because the generated markdown already carries the required headings and metadata, Codex can focus on the few sections that truly need edits.

## Script Usage

```bash
tools/scripts/create-doc-placeholder.sh docs/placeholders/example/checklist.md \
  --owner "Release PM" \
  --summary "Guardrail release checklist"
```

Flags:

- `--owner` (required): team/role responsible for the future content.
- `--summary` (optional): short description of what belongs in the document.
- `--date YYYY-MM-DD` (optional): override the auto-generated ISO date.
- `--help`: print the inline usage copy.

The script picks sensible defaults based on file extension (Markdown, CSV, JSON, SQL, ICS, plain text). If the target already exists, it leaves it untouched and prints a reminder.

Using this approach prevents missing-doc blockers while keeping the repository portable across projects.

## Under the Hood

- `tools/scripts/create-doc-placeholder.sh` shells out to `tools/scripts/python/render_doc_placeholder.py`, copying the helper into `.gpt-creator/shims/python/` automatically if it is missing. This keeps the call fast for Codex but also means you can run the Python script yourself when building custom workflows.
- `render_doc_placeholder.py` injects the owner, summary, timestamp, and CSV-friendly metadata into template files stored under `assets/templates/doc_placeholders/`. Those templates already include TODO markers, so the agent only has to refine the relevant paragraphs later.

If you ever forget the exact flags, run `tools/scripts/create-doc-placeholder.sh --help` or open `tools/scripts/usage/create-doc-placeholder.txt` for an annotated example (the `scripts/` symlink still points here for backwards compatibility).
