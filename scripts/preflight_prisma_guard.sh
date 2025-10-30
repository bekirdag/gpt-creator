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
          export PATH="$(dirname "$candidate"):$PATH"
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

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

normalize_path() {
  local path="$1"
  path="${path#./}"
  printf '%s' "$path"
}

# shellcheck disable=SC2034  # out_ref provides output to caller via nameref
select_runner() {
  local -n out_ref=$1
  out_ref=()
  if command_exists pnpm && [[ -f pnpm-lock.yaml || -f pnpm-workspace.yaml ]]; then
    out_ref=(pnpm exec -- prisma)
    return 0
  fi
  if command_exists npx; then
    out_ref=(npx --yes prisma)
    return 0
  fi
  return 1
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
if ! select_runner runner; then
  printf 'preflight-prisma-guard: prisma CLI unavailable (install pnpm or ensure npx works)\n' >&2
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
  if ! "${runner[@]}" migrate diff \
    --from-migrations "$migrations_dir" \
    --to-schema-datamodel "$schema_path" \
    --exit-code >/dev/null 2>&1
  then
    status=$?
    if (( status == 2 )); then
      drift_paths+=("$(normalize_path "$schema_path")")
    else
      error_paths+=("$(normalize_path "$schema_path")")
    fi
  fi
done

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
