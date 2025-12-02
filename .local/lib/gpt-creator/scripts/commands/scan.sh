#!/usr/bin/env bash
# shellcheck shell=bash

cmd_scan() {
  local root=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project) root="$(abs_path "$2")"; shift 2;;
      *) break;;
    esac
  done
  ensure_ctx "$root"
  root="${root:-$PROJECT_ROOT}"

  local scan_json="${STAGING_DIR}/scan.json"
  local catalog_dir="${STAGING_DIR}/inputs/catalog"
  mkdir -p "$catalog_dir"

  local -a default_scan_excludes=(
    ".gpt-creator/**"
    ".gpt-creator/staging/plan/work/runs/**"
    ".gpt-creator/**/prompts/**"
    ".gpt-creator/**/*.meta.json"
    ".git/**"
    "node_modules/**"
    "dist/**"
    "build/**"
    "**/__pycache__/**"
    "Library/**"
    "apps/**/dist-tests/**"
    "apps/**/{tests,test}/**"
    "apps/**/cypress/**"
    "apps/**/playwright/**"
    "apps/**/fixtures/**"
    "apps/**/public/**"
    "apps/api/prisma/migrations/**"
    "apps/api/prisma/fixtures/**"
    "apps/api/openapi/**"
    "ops/nginx/rendered/**"
    "ops/systemd/rendered/**"
    "ops/lighthouse/**"
    "qa/**"
    "docs/**/assets/**"
    "docs/**/evidence/**"
    "docs/**/screenshots/**"
    "**/*.lock"
    "apps/web/final_output.json"
  )

  local -a combined_excludes=("${default_scan_excludes[@]}")
  if declare -p GC_CONTEXT_EXCLUDES >/dev/null 2>&1; then
    combined_excludes+=("${GC_CONTEXT_EXCLUDES[@]}")
  elif [[ -n "${GC_CONTEXT_EXCLUDES:-}" ]]; then
    while IFS= read -r _scan_pattern; do
      [[ -n "$_scan_pattern" ]] && combined_excludes+=("$_scan_pattern")
    done <<<"$(printf '%s' "$GC_CONTEXT_EXCLUDES" | tr ':' '\n')"
  fi

  declare -A _scan_seen=()
  local excludes_payload=""
  local pattern
  for pattern in "${combined_excludes[@]}"; do
    [[ -z "$pattern" ]] && continue
    if [[ -n "${_scan_seen[$pattern]:-}" ]]; then
      continue
    fi
    _scan_seen[$pattern]=1
    excludes_payload+="$pattern"$'\n'
  done

  local scan_helper
  scan_helper="$(gc_clone_python_tool "scan_project.py" "${PROJECT_ROOT:-$PWD}")" || return 1

  local run_dir="${GC_RUN_DIR:-$root/.gpt-creator/staging/plan/work/runs/$(date +%Y%m%d%H%M%S)}"
  export GC_RUN_DIR="$run_dir"

  local scan_python="${PYTHON_BIN:-python3}"
  if command -v "$scan_python" >/dev/null 2>&1; then
    if GC_CONTEXT_EXCLUDES="$excludes_payload" "$scan_python" "$scan_helper" \
      --project "$root" --out "$catalog_dir" --scan-json "$scan_json"; then
      info "Catalog scan complete → ${catalog_dir}"
    else
      warn "scan_project.py failed; continuing with legacy scan pipeline outputs."
    fi
  else
    warn "Skipping catalog scan; $scan_python not available."
  fi

  local runtime_dir="$GC_DIR"
  local manifest_dir="${runtime_dir}/manifests"
  mkdir -p "$manifest_dir" "${PLAN_DIR}/tasks"
  local scan_stamp
  scan_stamp="$(date +%Y%m%d-%H%M%S)"
  local manifest="${manifest_dir}/discovery_${scan_stamp}.tsv"
  local manifest_tmp="${manifest}.tmp"
  local python_bin="${PYTHON_BIN:-python3}"
  local python_available=0
  if command -v "$python_bin" >/dev/null 2>&1; then
    python_available=1
  fi

  local -a scan_dirs=()
  if [[ -n "${GC_SCAN_ROOTS:-}" ]]; then
    local IFS=',:'
    read -ra scan_tokens <<<"${GC_SCAN_ROOTS}"
    for token in "${scan_tokens[@]}"; do
      token="${token//[[:space:]]/}"
      [[ -z "$token" ]] && continue
      if [[ -d "$PROJECT_ROOT/$token" ]]; then
        scan_dirs+=("$PROJECT_ROOT/$token")
      elif [[ -d "$token" ]]; then
        scan_dirs+=("$(abs_path "$token")")
      fi
    done
  fi
  if [[ ${#scan_dirs[@]} -eq 0 ]]; then
    local -a defaults=(apps docs db src packages qa tests ops)
    for candidate in "${defaults[@]}"; do
      if [[ -d "$PROJECT_ROOT/$candidate" ]]; then
        scan_dirs+=("$PROJECT_ROOT/$candidate")
      fi
    done
  fi

  # Always include the project root as a catch-all so top-level docs (e.g., rfp.md) are not missed.
  scan_dirs+=("$PROJECT_ROOT")

  local -a prune_dirs=(
    ".git"
    "node_modules"
    ".pnpm-store"
    "dist"
    "build"
    ".venv"
    ".gpt-creator"
    "tmp"
    "Library"
    "ansible"
    "docker.bak"
    "vendor"
    ".cache"
  )
  if [[ -n "${GC_SCAN_PRUNE_DIRS:-}" ]]; then
    local IFS=',:'
    read -ra prune_tokens <<<"${GC_SCAN_PRUNE_DIRS}"
    for token in "${prune_tokens[@]}"; do
      token="${token//[[:space:]]/}"
      [[ -n "$token" ]] && prune_dirs+=("$token")
    done
  fi

  info "Scanning project artifacts under: ${scan_dirs[*]}"
  printf "type\tconfidence\tpath\n" > "$manifest_tmp"

  local -a find_prune_expr=()
  if [[ ${#prune_dirs[@]} -gt 0 ]]; then
    find_prune_expr+=( "(" )
    for dir in "${prune_dirs[@]}"; do
      find_prune_expr+=( -name "$dir" -o )
    done
    unset 'find_prune_expr[${#find_prune_expr[@]}-1]'
    find_prune_expr+=( ")" -prune -o )
  fi

  local -a find_args=("${scan_dirs[@]}")
  find_args+=( "${find_prune_expr[@]}" -type f -print0 )

  while IFS= read -r -d '' f; do
    local hit
    hit="$(classify_file "$f")" || true
    if [[ -n "$hit" ]]; then
      local type conf
      IFS='|' read -r type conf <<<"$hit"
      printf "%s\t%.2f\t%s\n" "$type" "$conf" "$f" >> "$manifest_tmp"
    fi
  done < <(find "${find_args[@]}")

  mv "$manifest_tmp" "$manifest"
  if ! cp -f "$manifest" "${runtime_dir}/scan.tsv"; then
    warn "Unable to persist discovery manifest copy at ${runtime_dir}/scan.tsv."
  fi
  info "Discovery TSV → ${manifest}"

  if (( python_available )) && [[ ! -s "$scan_json" ]]; then
    local scan_manifest_helper
    scan_manifest_helper="$(gc_clone_python_tool "scan_manifest_to_json.py" "${PROJECT_ROOT:-$PWD}")" || return 1
    "$python_bin" "$scan_manifest_helper" "$manifest" "$PROJECT_ROOT" "$scan_json"
  else
    [[ -s "$scan_json" ]] || warn "Skipping scan.json export; ${python_bin} not available."
  fi

  if (( python_available )); then
    local doc_registry_tool="${CLI_ROOT}/src/lib/doc_registry.py"
    if [[ -f "$doc_registry_tool" ]]; then
      if "$python_bin" "$doc_registry_tool" sync-scan \
        --project-root "$PROJECT_ROOT" \
        --runtime-dir "$runtime_dir" \
        --scan-tsv "$manifest"; then
        info "Documentation registry synced."
      else
        warn "Documentation registry sync failed; inspect ${runtime_dir}/logs."
      fi
    else
      warn "Skipping documentation registry sync; tool not found at ${doc_registry_tool}."
    fi

    local doc_catalog_tool="${CLI_ROOT}/src/lib/doc_catalog.py"
    local doc_catalog_json="${STAGING_DIR}/doc-catalog.json"
    local doc_catalog_library="${STAGING_DIR}/doc-library.md"
    local doc_catalog_index="${STAGING_DIR}/doc-index.md"
    if [[ -f "$doc_catalog_tool" ]]; then
      if "$python_bin" "$doc_catalog_tool" \
        --project-root "$PROJECT_ROOT" \
        --staging-dir "$STAGING_DIR" \
        --out-json "$doc_catalog_json" \
        --out-library "$doc_catalog_library" \
        --out-index "$doc_catalog_index"; then
        info "Documentation catalog rebuilt."
      else
        warn "Documentation catalog build failed."
      fi
    else
      warn "Skipping documentation catalog build; tool not found at ${doc_catalog_tool}."
    fi

    local doc_pipeline_tool="${CLI_ROOT}/src/lib/doc_pipeline.py"
    if [[ -f "$doc_pipeline_tool" ]]; then
      if "$python_bin" "$doc_pipeline_tool" \
        --project-root "$PROJECT_ROOT" \
        --runtime-dir "$runtime_dir"; then
        info "Documentation summaries refreshed."
      else
        warn "Documentation summaries refresh failed."
      fi
    else
      warn "Skipping documentation summaries refresh; tool not found at ${doc_pipeline_tool}."
    fi

    local doc_indexer_pkg_root="${CLI_ROOT}/src"
    local doc_indexer_ready=0
    local doc_indexer_helper=""
    if doc_indexer_helper="$(gc_clone_python_tool "doc_indexer_ready.py" "${PROJECT_ROOT:-$PWD}")"; then
      if PYTHONPATH="${doc_indexer_pkg_root}${PYTHONPATH:+:$PYTHONPATH}" \
        "$python_bin" "$doc_indexer_helper" "$doc_indexer_pkg_root"; then
        doc_indexer_ready=1
      fi
    fi
    if (( doc_indexer_ready )); then
      if PYTHONPATH="${doc_indexer_pkg_root}${PYTHONPATH:+:$PYTHONPATH}" \
        "$python_bin" -m lib.doc_indexer --runtime-dir "$runtime_dir"; then
        info "Documentation indexes rebuilt."
      else
        warn "Documentation indexing failed."
      fi
    else
      info "Skipping documentation indexing; doc_indexer module not importable."
    fi
  else
    warn "Skipping documentation registry and catalog refresh; ${python_bin} not available."
  fi

  if [[ -f "$scan_json" ]]; then
    ok "Scan manifest → ${scan_json}"
  else
    warn "Scan manifest export missing (${scan_json}); rerun scan after installing ${python_bin}."
  fi
}
