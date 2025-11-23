# shellcheck shell=bash
# Subcommand: create-project
# Provides: cmd::create_project

CLI_MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${GC_TEMPLATE_ROOT:=$(cd "${CLI_MODULE_DIR}/../.." && pwd)/assets/templates}"
# shellcheck disable=SC1091
source "${CLI_MODULE_DIR}/../lib/templates.sh"

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
  gc_cli_render_template "plan/PLAN_TODO.md" > "$work_dir/staging/plan/PLAN_TODO.md"

  gc::ok "Plan scaffold created: $work_dir/staging/plan/PLAN_TODO.md"

  # Seed .gitignore if missing
  local gitignore_path="$target/.gitignore"
  if [[ ! -f "$gitignore_path" ]]; then
    gc_cli_render_template "project/gitignore.tmpl" > "$gitignore_path"
    gc::ok "Added .gitignore to project root"
  else
    gc::log ".gitignore already present; leaving as-is"
  fi

  gc::hr
  gc::ok "Done. You can now run:"
  printf "  %s%s cd %q && tree -L 3 %s\n" "${GC_CLR_BOLD}" "$" "$work_dir" "${GC_CLR_RESET}"
  printf "  %s%s cat %q/staging/discovery.yaml%s\n" "${GC_CLR_BOLD}" "$" "$work_dir" "${GC_CLR_RESET}"
}
