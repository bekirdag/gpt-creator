#!/usr/bin/env bash
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  if [[ -z "${GC_BASH_BOOTSTRAP:-}" ]]; then
    bash_candidates=()
    if [[ -n "${GC_PREFERRED_BASH:-}" ]]; then
      bash_candidates+=("${GC_PREFERRED_BASH}")
    fi
    if [[ -n "${GC_BASH:-}" ]]; then
      bash_candidates+=("${GC_BASH}")
    fi
    if command -v brew >/dev/null 2>&1; then
      brew_bash="$(brew --prefix 2>/dev/null)/bin/bash"
      if [[ -x "${brew_bash:-}" ]]; then
        bash_candidates+=("$brew_bash")
      fi
    fi
    bash_candidates+=("/opt/homebrew/bin/bash" "/usr/local/bin/bash")
    for candidate in "${bash_candidates[@]}"; do
      [[ -n "$candidate" ]] || continue
      if [[ "$candidate" != "$BASH" && -x "$candidate" ]]; then
        if "$candidate" -c '[[ ${BASH_VERSINFO[0]} -ge 4 ]]' >/dev/null 2>&1; then
          export GC_BASH_BOOTSTRAP=1
          PATH="$(dirname "$candidate"):$PATH"
          export PATH
          exec "$candidate" "$0" "$@"
        fi
      fi
    done
  fi
  printf 'preflight-prisma-guard requires Bash 4 or newer. Install via `brew install bash` and retry, or set GC_PREFERRED_BASH to a modern shell.\n' >&2
  exit 1
fi

# Guard invoked before work-on-tasks to detect Prisma schema drift.

project_root="${1:-${GC_PROJECT_ROOT:-${PROJECT_ROOT:-$PWD}}}"
if [[ ! -d "$project_root" ]]; then
  printf 'ok\n'
  exit 0
fi

cd "$project_root"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

normalize_path() {
  local path="$1"
  path="${path#./}"
  printf '%s' "$path"
}

# shellcheck disable=SC2034  # out_ref provides output to caller via nameref
build_prisma_runners() {
  local -n out_ref=$1
  out_ref=()
  if command_exists pnpm && [[ -f pnpm-lock.yaml || -f pnpm-workspace.yaml ]]; then
    out_ref+=("pnpm exec -- prisma")
  fi
  if command_exists npx; then
    out_ref+=("npx --yes prisma")
  fi
  if command_exists prisma; then
    out_ref+=("prisma")
  fi
}

is_missing_prisma_cmd() {
  local status="$1"
  local output="$2"
  if (( status == 127 )); then
    return 0
  fi
  if [[ "$output" == *"ERR_PNPM_EXEC_FIRST_FAIL"* || "$output" == *"ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL"* ]]; then
    return 0
  fi
  if [[ "$output" == *"Command \"prisma\" not found"* ]]; then
    return 0
  fi
  if [[ "$output" == *"command not found"* ]]; then
    return 0
  fi
  return 1
}

read_env_var() {
  local key="$1"
  local file="$2"
  if [[ ! -s "$file" ]]; then
    printf ''
    return 0
  fi
  while IFS='=' read -r env_key env_value; do
    env_key="${env_key%% *}"
    env_key="${env_key%%#*}"
    env_key="${env_key// /}"
    if [[ -n "$env_key" && "$env_key" == "$key" ]]; then
      env_value="${env_value%$'\r'}"
      env_value="${env_value#\"}"
      env_value="${env_value%\"}"
      printf '%s' "$env_value"
      return 0
    fi
  done <"$file"
  printf ''
}

derive_shadow_url() {
  local url="$1"
  local suffix="$2"
  if [[ -z "$url" ]]; then
    printf ''
    return 0
  fi
  local helper_path=""
  if declare -F gc_clone_python_tool >/dev/null 2>&1; then
    helper_path="$(gc_clone_python_tool "derive_shadow_url.py" "${PROJECT_ROOT:-$PWD}")" || return 1
  fi
  if [[ -z "$helper_path" ]]; then
    helper_path="${SCRIPT_DIR}/python/derive_shadow_url.py"
  fi
  python3 "$helper_path" "$url" "$suffix"
}

mapfile -t schema_paths < <(
  find . \
    \( -path '*/node_modules/*' -o -path '*/.git/*' -o -path '*/.gpt-creator/*' -o -path '*/tmp/*' -o -path '*/vendor/*' \) -prune -o \
    -name schema.prisma -type f -print 2>/dev/null | sort
)

if ((${#schema_paths[@]} == 0)); then
  printf 'ok\n'
  exit 0
fi

runner=()
build_prisma_runners runner
if ((${#runner[@]} == 0)); then
  printf 'preflight-prisma-guard: prisma CLI unavailable (install pnpm, npm, or prisma) — skipping guard.\n' >&2
  printf 'ok\n'
  exit 0
fi

export PRISMA_HIDE_UPDATE_MESSAGE=1
export NO_COLOR=1

drift_paths=()
error_paths=()

for schema_path in "${schema_paths[@]}"; do
  schema_dir="$(dirname "$schema_path")"
  migrations_dir="${schema_dir}/migrations"
  if [[ ! -d "$migrations_dir" ]]; then
    continue
  fi
  if ! find "$migrations_dir" -mindepth 1 -maxdepth 1 -type d -print -quit >/dev/null 2>&1; then
    continue
  fi
  schema_ok=0
  shadow_url="${PRISMA_MIGRATE_SHADOW_DATABASE_URL:-}"
  if [[ -z "$shadow_url" ]]; then
    if [[ -z "${ENV_FILE_ABS_HELPER:-}" ]]; then
      if declare -F gc_clone_python_tool >/dev/null 2>&1; then
        ENV_FILE_ABS_HELPER="$(gc_clone_python_tool "resolve_env_file_path.py" "${PROJECT_ROOT:-$PWD}")" || return 1
      fi
      if [[ -z "${ENV_FILE_ABS_HELPER:-}" ]]; then
        ENV_FILE_ABS_HELPER="${SCRIPT_DIR}/python/resolve_env_file_path.py"
      fi
    fi
    for env_file in "$schema_dir/.env" "$schema_dir/../.env" "$schema_dir/../../.env" "$schema_dir/.env.local" "$schema_dir/../.env.local" "$schema_dir/../../.env.local"; do
      env_file="$(cd "$schema_dir" && python3 "$ENV_FILE_ABS_HELPER" "$env_file")"
      db_url="$(read_env_var "DATABASE_URL" "$env_file")"
      if [[ -n "$db_url" ]]; then
        shadow_derived="$(derive_shadow_url "$db_url" "_shadow")"
        if [[ -n "$shadow_derived" ]]; then
          shadow_url="$shadow_derived"
          break
        fi
      fi
    done
  fi
  export PRISMA_MIGRATE_SHADOW_DATABASE_URL="$shadow_url"
  for runner_cmd in "${runner[@]}"; do
    if [[ -z "$runner_cmd" ]]; then
      continue
    fi
    read -r -a runner_parts <<< "$runner_cmd"
    set +e
    prisma_output=""
    prisma_output="$("${runner_parts[@]}" migrate diff \
      --from-migrations "$migrations_dir" \
      --to-schema-datamodel "$schema_path" \
      --exit-code 2>&1)"
    status=$?
    set -e
    if (( status == 0 )); then
      schema_ok=1
      break
    fi
    if (( status == 2 )); then
      drift_paths+=("$(normalize_path "$schema_path")")
      schema_ok=1
      break
    fi
    if [[ "$prisma_output" == *"shadow-database-url"* ]]; then
      printf 'preflight-prisma-guard: %s requires PRISMA_MIGRATE_SHADOW_DATABASE_URL (e.g. mysql://user:pass@host:3306/db_shadow); skipping guard.\n' "$(normalize_path "$schema_path")" >&2
      schema_ok=1
      break
    fi
    if is_missing_prisma_cmd "$status" "$prisma_output"; then
      continue
    fi
    if [[ -n "$prisma_output" ]]; then
      printf '%s\n' "$prisma_output" >&2
    fi
    error_paths+=("$(normalize_path "$schema_path")")
    schema_ok=1
    break
  done
  if (( schema_ok == 0 )); then
    printf 'preflight-prisma-guard: prisma CLI unavailable for %s; skipping.\n' "$(normalize_path "$schema_path")" >&2
  fi
done

index_guard_failures=()
if command_exists python3; then
  index_guard="${SCRIPT_DIR}/python/prisma_index_guard.py"
  if [[ -f "$index_guard" ]]; then
    for schema_path in "${schema_paths[@]}"; do
      migrations_dir="$(dirname "$schema_path")/migrations"
      if [[ ! -d "$migrations_dir" ]]; then
        continue
      fi
      set +e
      guard_output="$(python3 "$index_guard" --schema "$schema_path" --migrations "$migrations_dir" 2>&1)"
      status=$?
      set -e
      if (( status != 0 )); then
        if [[ -n "$guard_output" ]]; then
          printf '%s\n' "$guard_output" >&2
        fi
        index_guard_failures+=("$(normalize_path "$schema_path")")
      fi
    done
  fi
fi

if ((${#index_guard_failures[@]} > 0)); then
  printf 'preflight-prisma-guard: missing required indexes detected for: %s\n' "${index_guard_failures[*]}" >&2
  printf 'blocked-missing-indexes\n'
  exit 6
fi

if ((${#drift_paths[@]} > 0)); then
  printf 'Prisma schema drift detected for: %s\n' "${drift_paths[*]}" >&2
  printf 'blocked-schema-drift\n'
  exit 4
fi

if ((${#error_paths[@]} > 0)); then
  printf 'preflight-prisma-guard: prisma migrate diff failed for: %s\n' "${error_paths[*]}" >&2
  printf 'blocked-schema-guard-error\n'
  exit 5
fi

printf 'ok\n'
exit 0
