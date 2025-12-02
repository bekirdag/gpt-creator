# Appending Trimmed Context Snippets

`tools/scripts/python/append_file_with_line_limit.py` copies a bounded slice of a source file into a destination file, respecting both line and character limits. Use it whenever you need to provide Codex with a glimpse of logs, seeds, or generated artifacts without pasting the entire file into the prompt.

## Workflow

1. Identify the source file that is too large to paste directly (for example, a seed SQL dump or long log).
2. Decide how many lines/characters you want to include.
3. Run the script pointing to the source file and the destination snippet file inside `.gpt-creator/staging/...`.
4. Reference the destination snippet in your prompt or documentation.

If the snippet hits either limit, the script automatically appends `... (truncated; see consolidated context for more)` so reviewers know they are only seeing part of the file.

## Command

```
python3 tools/scripts/python/append_file_with_line_limit.py <src-file> <dest-file> <max-lines> <max-chars>
```

- `<src-file>`: path to the large file (missing files are treated as empty).
- `<dest-file>`: file that will receive the snippet via append mode (`mkdir -p` before running if needed).
- `<max-lines>` / `<max-chars>`: numerical limits; use `0` to ignore a limit.

Example:

```bash
python3 tools/scripts/python/append_file_with_line_limit.py \
  logs/create-jira-tasks.txt \
  .gpt-creator/staging/context/cjt-snippet.txt \
  120 4000
```

This writes up to 120 lines (but no more than 4,000 characters) from the Jira log into the staging snippet file.

## Why this saves tokens

- Limits keep prompts short, so Codex only processes the relevant slice instead of entire dumps.
- The script automatically adds spacing/newlines, so you can concatenate multiple snippets without manual formatting.
