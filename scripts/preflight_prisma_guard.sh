#!/usr/bin/env bash
set -euo pipefail

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
