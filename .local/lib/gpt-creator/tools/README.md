# Tools layout

- `tools/scripts/` is the canonical home for CLI and helper scripts (bash, node, python). Subfolders mirror the old `scripts/` tree: `commands/`, `lib/`, `python/`, `runtime-hooks/`, `verify/`, `ops/`, `guards/`, `usage/`.
- Compatibility shims remain at the repo root: `scripts -> tools/scripts` and `ops/scripts -> ../tools/scripts/ops` so existing invocations keep working while consumers switch to the new path.
- `bin/gpt-creator` now resolves scripts from `tools/scripts` first via `GC_SCRIPTS_ROOT`; prefer referencing that path going forward.
