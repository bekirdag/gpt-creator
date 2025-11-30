#!/usr/bin/env bash
# Docdex helpers for gpt-creator.

gc_docdex_bin() {
  local preferred="${GC_DOCDEX_BIN:-}"
  # Separate the command check to satisfy shells that reject command invocations inside [[ ... && ... ]].
  if [[ -n "$preferred" ]] && command -v "$preferred" >/dev/null 2>&1; then
    printf '%s' "$preferred"
    return 0
  fi
  local candidate
  for candidate in docdexd docdex; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  printf '%s' "${preferred:-docdexd}"
}

gc_docdex_usage() {
  cat <<'EOF'
Usage: gpt-creator docdex <index|serve> [options]

  gpt-creator docdex index --project /path/to/repo
      Rebuild the documentation index for the project (uses npm-installed docdex CLI).

  gpt-creator docdex serve --project /path/to/repo [--host 127.0.0.1] [--port 46137]
      Serve the docdex HTTP API (includes filesystem watcher for incremental updates).
EOF
}

cmd_docdex_index() {
  local root=""
  local docdex_bin
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|-p|--repo)
        root="$(abs_path "$2")"
        shift 2
        ;;
      -h|--help)
        gc_docdex_usage
        return 0
        ;;
      *)
        die "Unknown argument for docdex index: $1"
        ;;
    esac
  done
  if [[ -z "$root" ]]; then
    if [[ -n "${PROJECT_ROOT:-}" ]]; then
      root="$PROJECT_ROOT"
    else
      die "--project is required for docdex index"
    fi
  fi
  docdex_bin="$(gc_docdex_bin)"
  need_cmd "$docdex_bin" || die "docdex CLI not found; install via 'npm i -g docdex' or set GC_DOCDEX_BIN."
  "$docdex_bin" index --repo "$root"
}

cmd_docdex_serve() {
  local root=""
  local host="${GC_DOCDEX_HOST:-127.0.0.1}"
  local port="${GC_DOCDEX_PORT:-46137}"
  local docdex_bin
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project|-p|--repo)
        root="$(abs_path "$2")"
        shift 2
        ;;
      --host)
        host="$2"
        shift 2
        ;;
      --port)
        port="$2"
        shift 2
        ;;
      -h|--help)
        gc_docdex_usage
        return 0
        ;;
      *)
        die "Unknown argument for docdex serve: $1"
        ;;
    esac
  done
  if [[ -z "$root" ]]; then
    if [[ -n "${PROJECT_ROOT:-}" ]]; then
      root="$PROJECT_ROOT"
    else
      die "--project is required for docdex serve"
    fi
  fi
  docdex_bin="$(gc_docdex_bin)"
  need_cmd "$docdex_bin" || die "docdex CLI not found; install via 'npm i -g docdex' or set GC_DOCDEX_BIN."
  info "Starting ${docdex_bin} for ${root} on ${host}:${port}…"
  exec "$docdex_bin" serve --repo "$root" --host "$host" --port "$port"
}

cmd_docdex() {
  local action="${1:-help}"
  shift || true
  case "$action" in
    index)
      cmd_docdex_index "$@"
      ;;
    serve)
      cmd_docdex_serve "$@"
      ;;
    help|-h|--help|"")
      gc_docdex_usage
      ;;
    *)
      die "Unknown docdex action: $action"
      ;;
  esac
}
