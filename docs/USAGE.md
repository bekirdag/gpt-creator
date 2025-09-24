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
gpt-creator iterate --root DIR [--jira tasks.md]
```
Common flow:
1) `create-project` (runs everything) or hand‑run: scan → normalize → plan → generate → db → run → verify.
2) Use `iterate` to loop Codex over Jira tasks until acceptance is green.
