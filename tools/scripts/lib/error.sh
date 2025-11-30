#!/usr/bin/env bash
# Error handling, redaction, and preflight helpers.

gc_flush_logs_hooks() {
  if [[ -n "${GC_LOG_FLUSH_CMD:-}" ]]; then
    eval "${GC_LOG_FLUSH_CMD}" || true
  fi
  local root="${PROJECT_ROOT:-$PWD}"
  if [[ -x "${root}/scripts/gc-flush-logs.sh" ]]; then
    "${root}/scripts/gc-flush-logs.sh" || true
  fi
  if command -v node >/dev/null 2>&1 && [[ -f "${root}/scripts/gc-flush-logs.js" ]]; then
    node "${root}/scripts/gc-flush-logs.js" || true
  fi
  if command -v python3 >/dev/null 2>&1 && [[ -f "${root}/scripts/gc-flush-logs.py" ]]; then
    python3 "${root}/scripts/gc-flush-logs.py" || true
  fi
}

gc_load_required_vars() {
  local -a required=()
  if [[ -n "${GC_REQUIRED_VARS:-}" ]]; then
    read -r -a required <<<"${GC_REQUIRED_VARS}"
  fi
  local req_file
  req_file="$(gc_from_root ".gpt-creator/required.env")"
  if [[ -f "$req_file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%%#*}"
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line%"${line##*[![:space:]]}"}"
      [[ -n "$line" ]] || continue
      required+=("$line")
    done <"$req_file"
  fi
  printf '%s\n' "${required[@]}"
}

gc_preflight_config() {
  local -a required_vars=()
  if ! mapfile -t required_vars < <(gc_load_required_vars); then
    required_vars=()
  fi
  (( ${#required_vars[@]} )) || return 0
  local -a missing=()
  local -a empty=()
  local var value trimmed
  for var in "${required_vars[@]}"; do
    [[ -n "$var" ]] || continue
    if [[ -z "${!var+x}" ]]; then
      missing+=("$var")
      continue
    fi
    value="${!var}"
    trimmed="${value#"${value%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
    if [[ -z "$trimmed" ]]; then
      empty+=("$var")
    fi
  done
  if (( ${#missing[@]} || ${#empty[@]} )); then
    local reason="ConfigurationError"
    if (( ${#missing[@]} )); then
      reason+=" missing:${missing[*]}"
    fi
    if (( ${#empty[@]} )); then
      reason+=" empty:${empty[*]}"
    fi
    GC_LAST_ERROR_CLASS="PERMANENT"
    GC_LAST_ERROR_REASON="$reason"
    GC_LAST_ERROR_STATUS=78
    gc_flush_logs_hooks || true
    gc_finalize_and_report "failure" "$reason"
    exit 78
  fi
}

declare -ag GC_ERROR_SUMMARY_ARR=()

gc_redact() {
  local s="$*"
  s="${s//sk-[A-Za-z0-9_-]*/sk-REDACTED}"
  local k _
  while IFS='=' read -r k _; do
    if [[ "$k" =~ (KEY|TOKEN|SECRET|PASSWORD|AUTH|ACCESS|PRIVATE) ]] && [[ -n "${!k:-}" ]]; then
      s="${s//"${!k}"/"[REDACTED:${k}]"}"
    fi
  done < <(env)
  printf '%s' "$s" | sed -E 's/[A-Fa-f0-9]{32,}/[REDACTED]/g; s/[A-Za-z0-9_\\-]{24,}/[REDACTED]/g'
}

gc_error_summary_add() {
  local msg
  msg="$(gc_redact "$*")"
  [[ -n "$msg" ]] && GC_ERROR_SUMMARY_ARR+=("$msg")
}

gc_error_summary_json() {
  printf '['
  local first=1 entry sanitized
  for entry in "${GC_ERROR_SUMMARY_ARR[@]}"; do
    sanitized="$(gc_redact "$entry")"
    if [[ $first -eq 0 ]]; then
      printf ','
    fi
    first=0
    if declare -F gc_json_escape >/dev/null 2>&1; then
      printf '\"%s\"' "$(gc_json_escape "$sanitized")"
    else
      printf '\"%s\"' "$sanitized"
    fi
  done
  printf ']'
}
