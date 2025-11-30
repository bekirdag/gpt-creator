#!/usr/bin/env sh
# POSIX dependency preflight + mock-mode fallback

set -eu

warn() {
  printf >&2 "gpt-creator: %s\n" "$*"
}

MODE="${GC_DEPS_MODE:-auto}"
WORK="${GC_WORKSPACE_DIR:-$PWD}"
[ -d "$WORK" ] || WORK="$PWD"

case "$MODE" in
  auto|install|cache-only|skip) ;;
  *) MODE="auto" ;;
esac

WORK_LOCK_DIR="$WORK/.gpt-creator"
CACHE="$WORK_LOCK_DIR/cache"
STATE_DIR="$WORK_LOCK_DIR/state"
mkdir -p "$CACHE" "$STATE_DIR"

MOCK_FLAG="$STATE_DIR/mock-deps.flag"
WARN_SKIP_FLAG="$STATE_DIR/warn-mock-skip.flag"
WARN_PERM_FLAG="$STATE_DIR/warn-node-perms.flag"

: "${PNPM_IGNORE_NODE_VERSION:=1}"
: "${NPM_CONFIG_ENGINE_STRICT:=false}"
: "${YARN_IGNORE_NODE:=1}"
export PNPM_IGNORE_NODE_VERSION NPM_CONFIG_ENGINE_STRICT YARN_IGNORE_NODE

cd "$WORK" || exit 1

# Detect package managers (Node preferred order pnpm → npm → yarn)
NODE_PM=""
if [ -f "$WORK/pnpm-lock.yaml" ]; then
  NODE_PM="pnpm"
elif [ -f "$WORK/package-lock.json" ]; then
  NODE_PM="npm"
elif [ -f "$WORK/yarn.lock" ]; then
  NODE_PM="yarn"
fi

HAS_PY_DEPS=0
if [ -f "$WORK/pyproject.toml" ] || [ -f "$WORK/requirements.txt" ]; then
  HAS_PY_DEPS=1
fi

# Cache envs (safe no-ops if unused)
export PNPM_HOME="$CACHE/pnpm-home"
export PNPM_STORE_DIR="$CACHE/pnpm-store"
export NPM_CONFIG_CACHE="$CACHE/npm"
export YARN_CACHE_FOLDER="$CACHE/yarn"
export PIP_CACHE_DIR="$CACHE/pip"
mkdir -p "$PNPM_HOME" "$PNPM_STORE_DIR" "$NPM_CONFIG_CACHE" "$YARN_CACHE_FOLDER" "$PIP_CACHE_DIR"

do_node_install() {
  [ -n "$NODE_PM" ] || return 0
  [ "$MODE" = "skip" ] && return 0

  NET_FLAG=""
  if [ "$MODE" = "cache-only" ]; then
    NET_FLAG="--prefer-offline"
  fi

  case "$NODE_PM" in
    pnpm)
      command -v pnpm >/dev/null 2>&1 || return 1
      pnpm install --frozen-lockfile --ignore-scripts --no-optional $NET_FLAG
      ;;
    npm)
      command -v npm >/dev/null 2>&1 || return 1
      if [ "$MODE" = "cache-only" ]; then
        npm ci --ignore-scripts --no-optional --prefer-offline
      else
        npm ci --ignore-scripts --no-optional
      fi
      ;;
    yarn)
      command -v yarn >/dev/null 2>&1 || return 1
      yarn install --ignore-scripts --no-optional ${NET_FLAG}
      ;;
  esac
}

do_python_install() {
  [ "$HAS_PY_DEPS" -eq 1 ] || return 0
  [ "$MODE" = "skip" ] && return 0
  command -v python3 >/dev/null 2>&1 || return 1
  if [ -f "$WORK/requirements.txt" ]; then
    python3 -m pip install --disable-pip-version-check -r requirements.txt
  elif [ -f "$WORK/pyproject.toml" ]; then
    python3 -m pip install --disable-pip-version-check .
  else
    return 0
  fi
}

GC_MOCK_DEPS="${GC_MOCK_DEPS:-0}"

if [ "${GC_DEPS_RESET_MOCK:-0}" = "1" ] && [ -f "$MOCK_FLAG" ]; then
  rm -f "$MOCK_FLAG" 2>/dev/null || true
fi

PREVIOUS_MOCK=0
if [ -f "$MOCK_FLAG" ]; then
  if [ "$(cat "$MOCK_FLAG" 2>/dev/null || echo 0)" = "1" ]; then
    PREVIOUS_MOCK=1
    GC_MOCK_DEPS=1
  fi
fi

NODE_DIR="$WORK/node_modules"
NODE_STATE_FILE="${NODE_DIR}/.modules.yaml"
NODE_INSTALL_BLOCKED=0
NODE_INSTALL_REASON=""
if [ -d "$NODE_DIR" ]; then
  if [ ! -w "$NODE_DIR" ]; then
    NODE_INSTALL_BLOCKED=1
    NODE_INSTALL_REASON="node_modules is not writable (likely owned by another user)"
  elif [ -e "$NODE_STATE_FILE" ] && [ ! -w "$NODE_STATE_FILE" ]; then
    NODE_INSTALL_BLOCKED=1
    NODE_INSTALL_REASON="node_modules/.modules.yaml is not writable"
  fi
fi

INSTALL_SKIP=0
if [ "$PREVIOUS_MOCK" -eq 1 ]; then
  INSTALL_SKIP=1
fi
if [ "$NODE_INSTALL_BLOCKED" -eq 1 ]; then
  INSTALL_SKIP=1
fi

if [ "$INSTALL_SKIP" -eq 1 ]; then
  if [ "$PREVIOUS_MOCK" -eq 1 ]; then
    if [ ! -f "$WARN_SKIP_FLAG" ]; then
      warn "Skipping dependency install; previous mock-mode flag detected at ${MOCK_FLAG}. Delete it or set GC_DEPS_RESET_MOCK=1 to retry."
      printf '1\n' >"$WARN_SKIP_FLAG" 2>/dev/null || true
    fi
  fi
  if [ "$NODE_INSTALL_BLOCKED" -eq 1 ]; then
    if [ ! -f "$WARN_PERM_FLAG" ]; then
      warn "Skipping pnpm install because ${NODE_INSTALL_REASON}; fix permissions (e.g. chown -R ${USER:-$LOGNAME} node_modules) or reinstall dependencies manually."
      printf '1\n' >"$WARN_PERM_FLAG" 2>/dev/null || true
    fi
  fi
  GC_MOCK_DEPS=1
  export GC_DEPS_AUTO_INSTALL_DISABLED=1
else
  if ! do_node_install; then
    GC_MOCK_DEPS=1
  fi
fi

if ! do_python_install; then
  GC_MOCK_DEPS=1
fi

export GC_MOCK_DEPS

printf '%s\n' "$GC_MOCK_DEPS" > "$MOCK_FLAG" 2>/dev/null || true

if [ "$GC_MOCK_DEPS" = "1" ]; then
  RUNTIME_DIR="$WORK_LOCK_DIR/runtime"
  SHIM_DIR="$RUNTIME_DIR/shims"
  mkdir -p "$SHIM_DIR"
  NODE_MOCK="$RUNTIME_DIR/node-mock-missing.js"
  cat > "$NODE_MOCK" <<'JS'
const Module = require('module');
const path = require('path');
const fs = require('fs');

const original = Module._resolveFilename;
const SHIMS = new Map();
const SPECIAL_SHIMS = new Map([
  [
    '@prisma/client',
    `
      class PrismaClient {
        async $connect() {}
        async $disconnect() {}
      }
      module.exports = { PrismaClient };
    `,
  ],
]);

function makeShim(request) {
  const dir = path.join(process.cwd(), '.gpt-creator', 'runtime', 'shims');
  fs.mkdirSync(dir, { recursive: true });
  const safeName = request.replace(/[\/:]/g, '_');
  const file = path.join(dir, `${safeName}.js`);
  if (!fs.existsSync(file)) {
    const special = SPECIAL_SHIMS.get(request);
    const body = special
      ? `
        // Auto-generated shim for ${request}
        ${special}
      `
      : `
        // Auto-generated stub for missing module: ${request}
        module.exports = new Proxy(function () {}, {
          get: () => new Proxy(function () {}, { apply: () => undefined }),
          apply: () => undefined,
        });
      `;
    fs.writeFileSync(file, body);
  }
  return file;
}

Module._resolveFilename = function (request, parent, isMain, options) {
  try {
    return original.call(this, request, parent, isMain, options);
  } catch (error) {
    if (error && error.code === 'MODULE_NOT_FOUND') {
      if (!SHIMS.has(request)) {
        SHIMS.set(request, makeShim(request));
      }
      return SHIMS.get(request);
    }
    throw error;
  }
};
JS
  export GC_NODE_MOCK="$NODE_MOCK"
  existing_opts="${NODE_OPTIONS:-}"
  case " $existing_opts " in
    *"$GC_NODE_MOCK"*)
      ;;
    *)
      if [ -n "$existing_opts" ]; then
        export NODE_OPTIONS="--require $GC_NODE_MOCK $existing_opts"
      else
        export NODE_OPTIONS="--require $GC_NODE_MOCK"
      fi
      ;;
  esac
fi
