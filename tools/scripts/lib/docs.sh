#!/usr/bin/env bash
# Documentation catalog helpers.

gc_bootstrap_docs_registry() {
  local db_path="${GC_DOCUMENTATION_DB_PATH:-}"
  [[ -n "$db_path" ]] || return 0

  local repo_root="${PROJECT_ROOT:-$PWD}"
  local candidate_config="${repo_root}/config/bootstrap_docs_catalog.sql"
  local candidate_legacy="${repo_root}/.gpt-creator/staging/plan/tasks/bootstrap_docs_catalog.sql"
  local sql_file_default=""
  if [[ -f "$candidate_config" ]]; then
    sql_file_default="$candidate_config"
  elif [[ -f "$candidate_legacy" ]]; then
    sql_file_default="$candidate_legacy"
  else
    sql_file_default="$candidate_config"
  fi
  local sql_file="${GC_DOCUMENTATION_BOOTSTRAP_SQL:-$sql_file_default}"
  [[ -f "$sql_file" ]] || return 0

  local sqlite_bin="${SQLITE_BIN:-sqlite3}"
  if ! command -v "$sqlite_bin" >/dev/null 2>&1; then
    return 0
  fi

  local db_dir
  db_dir="$(dirname "$db_path")"
  mkdir -p "$db_dir"

  "$sqlite_bin" "$db_path" ".read $sql_file" >/dev/null 2>&1 || true
}

gc_doc_indexer_available() {
  local python_bin="${PYTHON_BIN:-python3}"
  local pkg_root="${CLI_ROOT}/src"
  if ! command -v "$python_bin" >/dev/null 2>&1; then
    return 1
  fi
  if [[ ! -d "$pkg_root" ]]; then
    return 1
  fi
  local helper_path
  helper_path="$(gc_clone_python_tool "doc_indexer_available.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  if PYTHONPATH="${pkg_root}${PYTHONPATH:+:$PYTHONPATH}" \
    "$python_bin" "$helper_path" "$pkg_root"; then
    return 0
  fi
  return 1
}

gc_doc_catalog_ready() {
  local root="${1:-${PROJECT_ROOT:-$PWD}}"
  local runtime_dir="${root}/.gpt-creator"
  local staging_dir="${runtime_dir}/staging"
  local doc_library="${staging_dir}/doc-library.md"
  local doc_index="${staging_dir}/doc-index.md"
  local doc_catalog="${staging_dir}/doc-catalog.json"
  local tasks_db="${staging_dir}/plan/tasks/tasks.db"
  local vector_index="${staging_dir}/plan/tasks/documentation-vector-index.sqlite"

  if [[ ! -s "$doc_library" || ! -s "$doc_index" || ! -s "$doc_catalog" ]]; then
    return 1
  fi
  if [[ ! -f "$tasks_db" ]]; then
    return 1
  fi
  local vector_required=0
  if [[ "${GC_REQUIRE_VECTOR_INDEX:-0}" == "1" ]]; then
    vector_required=1
  elif gc_doc_indexer_available; then
    vector_required=1
  fi
  if (( vector_required )) && [[ ! -s "$vector_index" ]]; then
    return 1
  fi

  if command -v python3 >/dev/null 2>&1; then
    local helper_path
    helper_path="$(gc_clone_python_tool "doc_catalog_ready.py" "${PROJECT_ROOT:-$PWD}")" || return 1
    if ! python3 "$helper_path" "$tasks_db"; then
      return 1
    fi
  else
    return 1
  fi

  return 0
}

gc_setup_doc_catalog_helpers() {
  local root="${PROJECT_ROOT:-$PWD}"
  local compat_base="${root}/.gpt-creator/src/lib"
  ensure_helper_compat() {
    local helper_path="${1:?helper path required}"
    local helper_name="${2:?helper name required}"
    if [[ -z "$helper_path" || -z "$helper_name" ]]; then
      return 0
    fi
    mkdir -p "$compat_base"
    local compat_target="${compat_base}/${helper_name}"
    if [[ ! -f "$compat_target" || "$helper_path" -nt "$compat_target" ]]; then
      cp "$helper_path" "$compat_target" 2>/dev/null || true
    fi
  }

  local helper_path=""
  helper_path="$(gc_clone_python_tool "doc_catalog.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_DOC_CATALOG_PY="$helper_path"
  ensure_helper_compat "$helper_path" "doc_catalog.py"

  helper_path="$(gc_clone_python_tool "doc_registry.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_DOC_REGISTRY_PY="$helper_path"
  ensure_helper_compat "$helper_path" "doc_registry.py"

  helper_path="$(gc_clone_python_tool "doc_indexer.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_DOC_INDEXER_PY="$helper_path"
  ensure_helper_compat "$helper_path" "doc_indexer.py"

  helper_path="$(gc_clone_python_tool "docdex_client.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  ensure_helper_compat "$helper_path" "docdex_client.py"

  helper_path="$(gc_clone_python_tool "repo_outline.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_REPO_OUTLINE_PY="$helper_path"
  ensure_helper_compat "$helper_path" "repo_outline.py"

  helper_path="$(gc_clone_python_tool "targeted_search.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_TARGETED_SEARCH_PY="$helper_path"
  ensure_helper_compat "$helper_path" "targeted_search.py"

  helper_path="$(gc_clone_python_tool "rest_check_runner.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_REST_CHECK_RUNNER_PY="$helper_path"
  ensure_helper_compat "$helper_path" "rest_check_runner.py"

  helper_path="$(gc_clone_python_tool "safe_show_file.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_SAFE_SHOW_FILE_PY="$helper_path"
  ensure_helper_compat "$helper_path" "safe_show_file.py"

  helper_path="$(gc_clone_python_tool "run_snippet.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  export GC_RUN_SNIPPET_PY="$helper_path"
  ensure_helper_compat "$helper_path" "run_snippet.py"
}

gc_populate_doc_catalog_shims() {
  local root="${1:-${PROJECT_ROOT:-$PWD}}"
  local runtime_dir="${root}/.gpt-creator"
  local staging_dir="${runtime_dir}/staging"
  local doc_library="${staging_dir}/doc-library.md"
  local doc_index="${staging_dir}/doc-index.md"
  local doc_catalog="${staging_dir}/doc-catalog.json"
  local plan_docs_dir="${staging_dir}/plan/docs"
  local plan_work_dir="${staging_dir}/plan/work"
  local plan_doc_library="${plan_docs_dir}/doc-library.md"
  local plan_doc_index="${plan_docs_dir}/doc-index.md"
  local plan_doc_catalog="${plan_work_dir}/doc-catalog.json"
  local fallback_library="${root}/docs/doc-library.md"
  local fallback_index="${root}/docs/doc-index.md"

  if [[ -z "$root" ]]; then
    return 0
  fi

  mkdir -p "$(dirname "$doc_library")" "$(dirname "$doc_index")" "$plan_docs_dir" "$plan_work_dir"

  if [[ ! -s "$doc_library" && -s "$fallback_library" ]]; then
    cp -f "$fallback_library" "$doc_library" 2>/dev/null || true
    info "Seeded doc-library.md from docs directory."
  fi
  if [[ ! -s "$doc_index" && -s "$fallback_index" ]]; then
    cp -f "$fallback_index" "$doc_index" 2>/dev/null || true
    info "Seeded doc-index.md from docs directory."
  fi

  if [[ -s "$doc_library" ]]; then
    if [[ ! -f "$plan_doc_library" || "$doc_library" -nt "$plan_doc_library" ]]; then
      cp -f "$doc_library" "$plan_doc_library" 2>/dev/null || true
    fi
  fi

  if [[ -s "$doc_index" ]]; then
    if [[ ! -f "$plan_doc_index" || "$doc_index" -nt "$plan_doc_index" ]]; then
      cp -f "$doc_index" "$plan_doc_index" 2>/dev/null || true
    fi
  fi

  if [[ -s "$doc_catalog" ]]; then
    if [[ ! -f "$plan_doc_catalog" || "$doc_catalog" -nt "$plan_doc_catalog" ]]; then
      cp -f "$doc_catalog" "$plan_doc_catalog" 2>/dev/null || true
    fi
  fi
}

gc_require_documentation_catalog() {
  local root="${1:-${PROJECT_ROOT:-$PWD}}"
  ensure_ctx "$root"

  if gc_doc_catalog_ready "$root"; then
    gc_populate_doc_catalog_shims "$root"
    return 0
  fi

  info "Documentation catalog missing or stale; running 'gpt-creator scan'."
  if ! cmd_scan --project "$root"; then
    warn "Documentation scan failed."
    return 1
  fi

  gc_populate_doc_catalog_shims "$root"

  if ! gc_doc_catalog_ready "$root"; then
    warn "Documentation catalog still incomplete after scan; inspect ${root}/.gpt-creator/staging."
    return 1
  fi

  if ! cmd_sweep_artifacts --project "$root"; then
    warn "Artifact sweep encountered issues; run 'gpt-creator sweep-artifacts --project \"$root\"' manually."
  fi

  return 0
}

gc_refresh_documentation_if_needed() {
  local root="${1:-${PROJECT_ROOT:-$PWD}}"
  if [[ "${GC_SKIP_AUTO_DOC_REFRESH:-0}" == "1" ]]; then
    info "Skipping automatic documentation refresh (GC_SKIP_AUTO_DOC_REFRESH=1)."
    return 0
  fi

  if gc_require_documentation_catalog "$root"; then
    ok "Documentation catalog refreshed."
    return 0
  fi

  warn "Automatic scan failed; rerun 'gpt-creator scan' manually."
  return 1
}
