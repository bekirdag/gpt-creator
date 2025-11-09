#!/usr/bin/env sh
# POSIX dependency preflight + mock-mode fallback

set -eu

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

GC_MOCK_DEPS=0
if ! do_node_install; then
  GC_MOCK_DEPS=1
fi
if ! do_python_install; then
  GC_MOCK_DEPS=1
fi
export GC_MOCK_DEPS

printf '%s\n' "$GC_MOCK_DEPS" > "$STATE_DIR/mock-deps.flag" 2>/dev/null || true

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
