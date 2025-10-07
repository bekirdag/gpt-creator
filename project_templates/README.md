# Project Templates

Add subdirectories here to seed new projects. Each directory should contain the
files you want copied into freshly created project roots before the standard
`gpt-creator` pipeline runs. Optional hints:

- Include a `tags.txt` (newline or comma separated) to improve automatic
  template selection when `--template auto` is used.
- Alternatively, provide a `template.json` with fields like `tags`, `keywords`,
  or `stack` for richer metadata.
- Files named `template.tags` or similar can also be referenced from `tags.txt`.
- `.git` directories are ignored automatically; `.gitignore` files are copied.

If no templates are present, `create-project` simply scaffolds the project from
scratch based on the documentation.
