#!/usr/bin/env bash
# Environment and credential helpers for gpt-creator.

gc_env_file() { echo "${PROJECT_ROOT:-$PWD}/.env"; }

gc_write_env_var() {
  local target="$1" key="$2" value="$3"
  local helper_path
  helper_path="$(gc_clone_python_tool "write_env_var.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$target" "$key" "$value"
}

gc_set_env_var() {
  local key="$1" value="$2"
  local env_file
  env_file="$(gc_env_file)"
  gc_write_env_var "$env_file" "$key" "$value"
}

gc_remove_env_var() {
  local target="$1" key="$2"
  [[ -f "$target" ]] || return 0
  local helper_path
  helper_path="$(gc_clone_python_tool "remove_env_var.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$target" "$key"
}

gc_decode_base64() {
  local value="${1:-}"
  local helper_path
  helper_path="$(gc_clone_python_tool "decode_base64.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$value"
}

: "${GC_PORT_RESERVATIONS:=}"

gc_port_for_service() {
  local service="$1"
  local entry
  for entry in $GC_PORT_RESERVATIONS; do
    local svc="${entry%%:*}"
    if [[ "$svc" == "$service" ]]; then
      printf '%s\n' "${entry#*:}"
      return 0
    fi
  done
  return 1
}

gc_unreserve_port() {
  local service="$1"
  [[ -n "$service" ]] || return 0
  local entry new_list=""
  for entry in $GC_PORT_RESERVATIONS; do
    local svc="${entry%%:*}"
    if [[ "$svc" == "$service" ]]; then
      continue
    fi
    if [[ -z "$new_list" ]]; then
      new_list="$entry"
    else
      new_list+=" $entry"
    fi
  done
  GC_PORT_RESERVATIONS="$new_list"
}

gc_reserve_port() {
  local service="$1" port="$2"
  [[ -n "$service" && -n "$port" ]] || return 0
  gc_unreserve_port "$service"
  if [[ -z "${GC_PORT_RESERVATIONS:-}" ]]; then
    GC_PORT_RESERVATIONS="${service}:${port}"
  else
    GC_PORT_RESERVATIONS+=" ${service}:${port}"
  fi
}

gc_port_is_reserved() {
  local port="$1"
  local entry
  for entry in $GC_PORT_RESERVATIONS; do
    if [[ "${entry#*:}" == "$port" ]]; then
      return 0
    fi
  done
  return 1
}

gc_port_reserved_by_other() {
  local port="$1" service="$2"
  local entry
  for entry in $GC_PORT_RESERVATIONS; do
    local svc="${entry%%:*}"
    local val="${entry#*:}"
    if [[ "$val" == "$port" && "$svc" != "$service" ]]; then
      return 0
    fi
  done
  return 1
}

gc_env_sync_ports() {
  GC_PORT_RESERVATIONS=""
  GC_DB_HOST_PORT="${GC_DB_HOST_PORT:-${DB_HOST_PORT:-${DB_PORT:-3306}}}"
  DB_NAME="${DB_NAME:-$GC_DB_NAME}"
  DB_USER="${DB_USER:-$GC_DB_USER}"
  DB_PASSWORD="${DB_PASSWORD:-$GC_DB_PASSWORD}"
  DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-$GC_DB_ROOT_PASSWORD}"
  DB_HOST_PORT="${DB_HOST_PORT:-$GC_DB_HOST_PORT}"
  GC_API_HOST_PORT="${GC_API_HOST_PORT:-${API_HOST_PORT:-3000}}"
  GC_WEB_HOST_PORT="${GC_WEB_HOST_PORT:-${WEB_HOST_PORT:-5173}}"
  GC_ADMIN_HOST_PORT="${GC_ADMIN_HOST_PORT:-${ADMIN_HOST_PORT:-5174}}"
  GC_PROXY_HOST_PORT="${GC_PROXY_HOST_PORT:-${PROXY_HOST_PORT:-8080}}"
  API_HOST_PORT="${API_HOST_PORT:-$GC_API_HOST_PORT}"
  WEB_HOST_PORT="${WEB_HOST_PORT:-$GC_WEB_HOST_PORT}"
  ADMIN_HOST_PORT="${ADMIN_HOST_PORT:-$GC_ADMIN_HOST_PORT}"
  PROXY_HOST_PORT="${PROXY_HOST_PORT:-$GC_PROXY_HOST_PORT}"
  local api_base_default="http://localhost:${GC_API_HOST_PORT}/api/v1"
  GC_API_BASE_URL="${GC_API_BASE_URL:-$api_base_default}"
  VITE_API_BASE="${VITE_API_BASE:-$GC_API_BASE_URL}"
  local expected_health="${GC_API_BASE_URL%/}/health"
  if [[ -z "${GC_API_HEALTH_URL:-}" ]]; then
    GC_API_HEALTH_URL="$expected_health"
    gc_set_env_var GC_API_HEALTH_URL "$GC_API_HEALTH_URL"
  elif [[ "$GC_API_HEALTH_URL" == "http://localhost:${GC_API_HOST_PORT}/health" && "$expected_health" != "$GC_API_HEALTH_URL" ]]; then
    GC_API_HEALTH_URL="$expected_health"
    gc_set_env_var GC_API_HEALTH_URL "$GC_API_HEALTH_URL"
  fi
  local proxy_origin="http://localhost:${GC_PROXY_HOST_PORT}"
  GC_WEB_URL="${GC_WEB_URL:-${proxy_origin}/}"
  GC_ADMIN_URL="${GC_ADMIN_URL:-${proxy_origin}/admin/}"
  gc_reserve_port db "$GC_DB_HOST_PORT"
  gc_reserve_port api "$GC_API_HOST_PORT"
  gc_reserve_port web "$GC_WEB_HOST_PORT"
  gc_reserve_port admin "$GC_ADMIN_HOST_PORT"
  gc_reserve_port proxy "$GC_PROXY_HOST_PORT"

  if gc_reports_enabled; then
    gc_reports_initialize
    gc_reports_touch_activity "$(date +%s)"
  fi
}

gc_sanitize_env_file() {
  local env_file="$1"
  local helper_path
  helper_path="$(gc_clone_python_tool "sanitize_env_file.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$env_file"
}

gc_load_env() {
  local env_file
  env_file="$(gc_env_file)"
  if [[ -f "$env_file" ]]; then
    gc_sanitize_env_file "$env_file"
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
  GC_DB_NAME="${GC_DB_NAME:-${DB_NAME:-app}}"
  GC_DB_USER="${GC_DB_USER:-${DB_USER:-app}}"
  GC_DB_PASSWORD="${GC_DB_PASSWORD:-${DB_PASSWORD:-app_pass}}"
  GC_DB_ROOT_PASSWORD="${GC_DB_ROOT_PASSWORD:-${DB_ROOT_PASSWORD:-root}}"
  gc_env_sync_ports
}

gc_user_config_root() {
  local helper_path
  helper_path="$(gc_clone_python_tool "user_config_root.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path"
}

gc_config_dir() {
  local root
  root="$(gc_user_config_root)"
  [[ -n "$root" ]] || root="."
  printf '%s\n' "${root%/}/gpt-creator"
}

gc_keys_file() {
  printf '%s/api-keys.env\n' "$(gc_config_dir)"
}

gc_ensure_config_dir() {
  local dir
  dir="$(gc_config_dir)"
  mkdir -p "$dir"
}

GC_API_KEYS_METADATA=(
  "openai|OpenAI Codex|OPENAI_API_KEY|AI automation commands (plan, generate, work-on-tasks)|GC_OPENAI_API_KEY,GC_OPENAI_KEY"
  "anthropic|Anthropic Claude|ANTHROPIC_API_KEY|Claude HTTP adapter (--client anthropic)|"
  "grok|xAI Grok|GROK_API_KEY|Grok HTTP adapter (--client xai)|GROK_KEY"
  "gemini|Google Gemini CLI|GEMINI_API_KEY|Gemini CLI adapter (--client gemini)|"
  "jira|Jira Automation|JIRA_API_TOKEN|Backlog integrations that sync with Jira (create-jira-tasks)|GC_JIRA_API_TOKEN"
  "github|GitHub Auto Reports|GC_GITHUB_TOKEN|Crash/stall reports published as GitHub issues|"
)

gc_find_api_key_entry() {
  local query input lower entry key_id label primary desc alias_csv
  query="${1:-}"
  [[ -n "$query" ]] || return 1
  lower="$(to_lower "$query")"
  for entry in "${GC_API_KEYS_METADATA[@]}"; do
    IFS='|' read -r key_id label primary desc alias_csv <<<"$entry"
    if [[ "$lower" == "$(to_lower "$key_id")" || "$lower" == "$(to_lower "$primary")" ]]; then
      printf '%s\n' "$entry"
      return 0
    fi
    if [[ -n "$alias_csv" ]]; then
      IFS=',' read -ra input <<<"$alias_csv"
      for alias in "${input[@]}"; do
        alias="${alias//[[:space:]]/}"
        [[ -n "$alias" ]] || continue
        if [[ "$lower" == "$(to_lower "$alias")" ]]; then
          printf '%s\n' "$entry"
          return 0
        fi
      done
    fi
  done
  return 1
}

gc_apply_api_key_aliases() {
  local entry key_id label primary desc alias_csv value alias
  local alias_arr
  for entry in "${GC_API_KEYS_METADATA[@]}"; do
    IFS='|' read -r key_id label primary desc alias_csv <<<"$entry"
    value="${!primary:-}"
    if [[ -z "$value" && -n "$alias_csv" ]]; then
      IFS=',' read -ra alias_arr <<<"$alias_csv"
      for alias in "${alias_arr[@]}"; do
        alias="${alias//[[:space:]]/}"
        [[ -n "$alias" ]] || continue
        if [[ -n "${!alias:-}" ]]; then
          value="${!alias}"
          break
        fi
      done
    fi
    [[ -n "$value" ]] || continue
    export "$primary"="$value"
    if [[ -n "$alias_csv" ]]; then
      IFS=',' read -ra alias_arr <<<"$alias_csv"
      for alias in "${alias_arr[@]}"; do
        alias="${alias//[[:space:]]/}"
        [[ -n "$alias" && "$alias" != "$primary" ]] || continue
        if [[ -z "${!alias:-}" ]]; then
          export "$alias"="$value"
        fi
      done
    fi
  done
}

gc_api_keys_loaded=0

gc_load_api_keys() {
  if (( gc_api_keys_loaded )); then
    gc_apply_api_key_aliases
    return
  fi
  gc_ensure_config_dir
  local keys_file
  keys_file="$(gc_keys_file)"
  if [[ -f "$keys_file" ]]; then
    gc_sanitize_env_file "$keys_file"
    set -a
    # shellcheck disable=SC1090
    source "$keys_file"
    set +a
  fi
  gc_apply_api_key_aliases
  gc_api_keys_loaded=1
}

gc_read_env_file_var() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  local helper_path
  helper_path="$(gc_clone_python_tool "read_env_file_var.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  python3 "$helper_path" "$file" "$key"
}

gc_api_keys_list() {
  gc_load_api_keys
  gc_ensure_config_dir
  local keys_file status_header="Status"
  keys_file="$(gc_keys_file)"
  printf "API keys status (storage file: %s)\n\n" "$keys_file"
  printf "%-22s %-20s %-24s %s\n" "Service" "Environment" "$status_header" "Used for"
  printf "%-22s %-20s %-24s %s\n" "-------" "-----------" "------" "-------"
  local entry key_id label primary desc alias_csv value stored_value status alias
  local alias_arr
  for entry in "${GC_API_KEYS_METADATA[@]}"; do
    IFS='|' read -r key_id label primary desc alias_csv <<<"$entry"
    value="${!primary:-}"
    if [[ -z "$value" && -n "$alias_csv" ]]; then
      IFS=',' read -ra alias_arr <<<"$alias_csv"
      for alias in "${alias_arr[@]}"; do
        alias="${alias//[[:space:]]/}"
        [[ -n "$alias" ]] || continue
        if [[ -n "${!alias:-}" ]]; then
          value="${!alias}"
          break
        fi
      done
    fi
    stored_value="$(gc_read_env_file_var "$keys_file" "$primary")"
    if [[ -n "$value" ]]; then
      if [[ -n "$stored_value" ]]; then
        status="configured (stored)"
      else
        status="configured (env)"
      fi
    else
      status="missing"
    fi
    printf "%-22s %-20s %-24s %s\n" "$label" "$primary" "$status" "$desc"
  done
  if [[ -n "${GC_GITHUB_TOKEN:-}" && -z "${GC_GITHUB_REPO:-}" ]]; then
    printf "\nHint: set GC_GITHUB_REPO (owner/name) so GitHub Auto Reports knows where to file issues.\n"
  fi
  printf "\nSet a value with: gpt-creator keys set <service>\n"
}

gc_api_keys_set() {
  local query="${1:-}"
  [[ -n "$query" ]] || die "keys set requires a service name or environment variable"
  local entry
  if ! entry="$(gc_find_api_key_entry "$query")"; then
    die "Unknown API key: ${query}"
  fi
  IFS='|' read -r key_id label primary desc alias_csv <<<"$entry"
  gc_load_api_keys
  gc_ensure_config_dir
  local keys_file value alias
  local alias_arr
  keys_file="$(gc_keys_file)"
  printf "Updating %s (%s)\n" "$label" "$primary"
  printf "Press ENTER without a value to remove the stored credential.\n"
  if [[ -n "$alias_csv" ]]; then
    printf "Aliases: %s\n" "${alias_csv//,/ }"
  fi
  if [[ -t 0 ]]; then
    read -rsp "Enter value: " value
    printf '\n'
  else
    info "Reading ${primary} from stdin (input will be visible)."
    if ! read -r value; then
      die "Failed to read value from stdin"
    fi
  fi
  value="${value//$'\\r'/}"
  value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [[ -z "$value" ]]; then
    gc_remove_env_var "$keys_file" "$primary"
    unset "$primary"
    if [[ -n "$alias_csv" ]]; then
      IFS=',' read -ra alias_arr <<<"$alias_csv"
      for alias in "${alias_arr[@]}"; do
        alias="${alias//[[:space:]]/}"
        [[ -n "$alias" ]] || continue
        unset "$alias"
      done
    fi
    ok "Removed stored value for ${label}"
    return 0
  fi
  gc_write_env_var "$keys_file" "$primary" "$value"
  chmod 600 "$keys_file" 2>/dev/null || true
  export "$primary"="$value"
  if [[ -n "$alias_csv" ]]; then
    IFS=',' read -ra alias_arr <<<"$alias_csv"
    for alias in "${alias_arr[@]}"; do
      alias="${alias//[[:space:]]/}"
      [[ -n "$alias" && "$alias" != "$primary" ]] || continue
      export "$alias"="$value"
    done
  fi
  ok "Updated ${label}"
}
