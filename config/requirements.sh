#!/usr/bin/env bash
# gpt-creator requirements.sh — summarize workspace dependency status
set -Eeuo pipefail

missing=()

check_cmd() {
  local name="$1" cmd="$2" note="$3"
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '[OK] %s found (%s)\n' "$name" "$cmd"
  else
    printf '[WARN] %s missing. %s\n' "$name" "$note"
    missing+=("$name")
  fi
}

check_env() {
  local name="$1" var="$2" note="$3"
  if [[ -n "${!var:-}" ]]; then
    printf '[OK] %s configured (env: %s)\n' "$name" "$var"
  else
    printf '[WARN] %s missing. %s\n' "$name" "$note"
    missing+=("$name")
  fi
}

check_cmd "Docker CLI" docker "Docker-powered commands will prompt you to install Docker Desktop/Engine when required."
check_cmd "Node.js" node "Install Node.js 20+ before running code generation."
check_cmd "pnpm" pnpm "Enable via corepack or npm when JavaScript tooling is needed."
if command -v codex >/dev/null 2>&1 || command -v codex-client >/dev/null 2>&1; then
  printf '[OK] Codex CLI found.\n'
else
  printf '[WARN] Codex CLI missing. Install the Codex CLI or set CODEX_BIN to a compatible wrapper.\n'
  missing+=("Codex CLI")
fi
check_cmd "MySQL client" mysql "Install the mysql (or mariadb) client before running database import/export helpers."
check_env "OPENAI_API_KEY" OPENAI_API_KEY "Export OPENAI_API_KEY to enable Codex-powered commands."

if ((${#missing[@]} == 0)); then
  echo "All dependencies detected."
else
  echo "Dependencies listed above are missing; related commands will remind you when invoked."
fi
