#!/usr/bin/env bash
# shellcheck shell=bash

cmd_db() {
  local action="${1:-}"; shift || true
  [[ -n "$action" ]] || die "db requires: provision|import|seed"
  local root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      *) break;;
    esac
  done
  ensure_ctx "$root"
  local compose_file="$PROJECT_ROOT/docker/docker-compose.yml"

  case "$action" in
    provision)
      [[ -f "$compose_file" ]] || die "Compose file not found at ${compose_file}; run 'gpt-creator generate docker'."
      info "Starting database service via docker compose"
      docker_compose -f "$compose_file" up -d db
      ok "MySQL container provisioned"
      ;;
    import)
      local sql_file
      sql_file="$(find "$INPUT_DIR/sql" -maxdepth 2 -type f -name '*.sql' | head -n1 || true)"
      [[ -n "$sql_file" ]] || die "No staged SQL found under ${INPUT_DIR}/sql"
      info "Importing SQL from ${sql_file}"
      local database="${DB_NAME:-$GC_DB_NAME}"
      local root_user="${DB_ROOT_USER:-root}"
      local root_pass="${DB_ROOT_PASSWORD:-${GC_DB_ROOT_PASSWORD:-}}"
      local app_user="${DB_USER:-$GC_DB_USER}"
      local app_pass="${DB_PASSWORD:-$GC_DB_PASSWORD}"
      local cleanup_files=()
      trap 'for f in "${cleanup_files[@]}"; do [[ -n "$f" && -f "$f" ]] && rm -f "$f"; done; trap - RETURN' RETURN
      local rendered_sql
      rendered_sql="$(gc_temp_file "$STAGING_DIR" "import-" ".sql")"
      cleanup_files+=("$rendered_sql")
      gc_render_sql "$sql_file" "$rendered_sql" "$database" "$app_user" "$app_pass"
      local init_sql="${INPUT_DIR}/sql/db/init.sql"
      if gc_execute_sql "$compose_file" "$rendered_sql" "$database" "$root_user" "$root_pass" "$app_user" "$app_pass" "$init_sql" "import"; then
        ok "Database import finished"
      else
        die "Database import failed"
      fi
      ;;
    seed)
      local seed_file="${PROJECT_ROOT}/db/seed.sql"
      [[ -f "$seed_file" ]] || die "Seed file not found: ${seed_file}"
      info "Seeding database from ${seed_file}"
      local database="${DB_NAME:-$GC_DB_NAME}"
      local root_user="${DB_ROOT_USER:-root}"
      local root_pass="${DB_ROOT_PASSWORD:-${GC_DB_ROOT_PASSWORD:-}}"
      local app_user="${DB_USER:-$GC_DB_USER}"
      local app_pass="${DB_PASSWORD:-$GC_DB_PASSWORD}"
      local cleanup_files=()
      trap 'for f in "${cleanup_files[@]}"; do [[ -n "$f" && -f "$f" ]] && rm -f "$f"; done; trap - RETURN' RETURN
      local rendered_seed
      rendered_seed="$(gc_temp_file "$STAGING_DIR" "seed-" ".sql")"
      cleanup_files+=("$rendered_seed")
      gc_render_sql "$seed_file" "$rendered_seed" "$database" "$app_user" "$app_pass"
      local fallback_init="${PROJECT_ROOT}/db/init.sql"
      if [[ ! -f "$fallback_init" ]]; then
        fallback_init="${INPUT_DIR}/sql/db/init.sql"
      fi
      if gc_execute_sql "$compose_file" "$rendered_seed" "$database" "$root_user" "$root_pass" "$app_user" "$app_pass" "$fallback_init" "seed"; then
        ok "Database seed applied"
      else
        die "Database seed failed"
      fi
      ;;
    *) die "Unknown db action: ${action}";;
  esac
}

