# USAGE

```
gpt-creator create-project /path/to/project [--yes] [--verbose]
gpt-creator scan --root DIR
gpt-creator normalize --root DIR
gpt-creator plan --root DIR --out plan.json
gpt-creator generate {api|web|admin|db|docker} --root DIR
gpt-creator db {provision|import|seed} --root DIR
gpt-creator run {up|down|logs|open} --root DIR
gpt-creator verify --root DIR
gpt-creator create-tasks --root DIR [--jira tasks.md] [--force]
gpt-creator work-on-tasks --root DIR [--story ID|SLUG] [--fresh] [--no-verify]
gpt-creator iterate --root DIR [--jira tasks.md]  # deprecated
```
Common flow:
1) `create-project` (runs everything) or hand‑run: scan → normalize → plan → generate → db → run → verify.
2) Snapshot Jira markdown with `create-tasks`, then execute the backlog via `work-on-tasks`. The legacy `iterate` command is deprecated.
