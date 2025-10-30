#!/usr/bin/env sh

if [ -n "$husky_skip_init" ]; then
  exit 0
fi

husky_skip_init=1
export husky_skip_init

if [ -f package.json ]; then
  if command -v node >/dev/null 2>&1; then
    export PATH="$PWD/node_modules/.bin:$PATH"
  fi
fi
