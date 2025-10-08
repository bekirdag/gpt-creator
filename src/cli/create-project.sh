# shellcheck shell=bash
# Subcommand: create-project
# Provides: cmd::create_project

cmd::create_project() {
  local target="${1:-}"
  [[ -z "$target" ]] && gc::die "Usage: gpt-creator create-project /path/to/project"

  # Resolve and check target
  target="$(gc::abs_path "$target")"
  [[ -d "$target" ]] || gc::die "Project folder not found: $target"

  gc::banner
  gc::log "Project root: $target"
  gc::require_cmds_soft

  gc::hr
  gc::log "Scanning for inputs (docs, OpenAPI, SQL, Mermaid, samples)…"
  gc::discover "$target" | sed 's/^/  /'
  gc::ok "Discovery complete"

  gc::hr
  gc::log "Normalizing inputs into staging workspace…"
  local work_dir; work_dir="$(gc::normalize_to_staging "$target")"
  gc::ok "Staged at: $work_dir/staging"

  # Seed plan scaffold
  mkdir -p "$work_dir/staging/plan"
  cat > "$work_dir/staging/plan/PLAN_TODO.md" <<'EOF'
# Build Plan (Scaffold)

This file will be populated by Codex based on the staged inputs:
- docs/pdr.md, docs/sds.md, docs/rfp.md, docs/jira.md, docs/ui-pages.md
- openapi/openapi.(yaml|json|src)
- sql/dump.sql
- diagrams/*.mmd
- samples/**

Next steps (automated in future steps):
1. Generate an execution plan with acceptance criteria.
2. Synthesize API scaffolds from OpenAPI (NestJS).
3. Generate schema & migrations (MySQL 8).
4. Generate Vue 3 website & admin shells from UI pages and CSS tokens.
5. Wire Docker Compose for local dev (API, MySQL, Admin, Web, Proxy).
6. Run acceptance checks, then drive Jira via create-tasks/work-on-tasks.

EOF

  gc::ok "Plan scaffold created: $work_dir/staging/plan/PLAN_TODO.md"

  gc::hr
  gc::ok "Done. You can now run:"
  printf "  %s%s cd %q && tree -L 3 %s\n" "${GC_CLR_BOLD}" "$" "$work_dir" "${GC_CLR_RESET}"
  printf "  %s%s cat %q/staging/discovery.yaml%s\n" "${GC_CLR_BOLD}" "$" "$work_dir" "${GC_CLR_RESET}"
}
