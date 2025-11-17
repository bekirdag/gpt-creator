# Rendering Infra/App Templates

Use `scripts/python/render_template_file.py` whenever a task needs an environment-specific config file or manifest derived from a reusable template. The helper replaces placeholder tokens with the values you provide, so Codex never has to hand-edit secrets or long boilerplate blocks.

## Workflow

1. Locate the source template (for example `assets/templates/docker/.env.tmpl`).
2. Choose the destination path inside the repo or staging directory.
3. Run the script with the required arguments in the order shown below.
4. Review the rendered file and commit or stage it alongside the task’s other changes.

## Arguments

```
python3 scripts/python/render_template_file.py \
  <source-template> <destination-path> \
  <DB_NAME> <DB_USER> <DB_PASSWORD> <DB_HOST_PORT> <DB_ROOT_PASSWORD> \
  <PROJECT_SLUG> <API_HOST_PORT> <WEB_HOST_PORT> <ADMIN_HOST_PORT> <PROXY_HOST_PORT>
```

- `source-template`: path to the `.tmpl` file with `{{TOKEN}}` placeholders.
- `destination-path`: file that will receive the rendered content (directories are created on demand).
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST_PORT`, `DB_ROOT_PASSWORD`: replace the database connection placeholders.
- `PROJECT_SLUG`: slug used in compose networks, container names, etc. (`gptcreator` if omitted).
- `API_HOST_PORT`, `WEB_HOST_PORT`, `ADMIN_HOST_PORT`, `PROXY_HOST_PORT`: expose the services on host ports; defaults mirror local dev values if you pass empty strings.

The script reads the template, performs simple `str.replace` calls for each token, and writes the rendered text to the destination. There is no additional logic or side effects, which makes it safe to re-run.

## Example

```bash
python3 scripts/python/render_template_file.py \
  assets/templates/docker/.env.tmpl .gpt-creator/staging/docker/.env \
  yoga_db yoga_app yoga_pass 3306 root_pass adm-06 4000 5173 5174 8080
```

Run this before spinning up Docker services so Codex can reference the generated `.env` file without inlining secrets or ports in a prompt.

## Why this saves tokens

- Pre-rendered configs prevent Codex from generating large JSON/YAML/ENV blobs inline, which easily burns thousands of tokens per attempt.
- Deterministic templates also keep diffs tight—reruns only touch arguments that change, letting `work-on-tasks` skip redundant context.
