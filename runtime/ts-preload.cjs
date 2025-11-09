#!/usr/bin/env node
/**
 * Lightweight transpile-only hook for TypeScript sources.
 * Requires `typescript` to be installed in the workspace; otherwise it no-ops.
 */
try {
  const fs = require('fs');
  const path = require('path');
  const ts = require('typescript');

  const extensions = ['.ts', '.tsx'];
  const compilerOptions = {
    module: 'commonjs',
    target: 'ES2019',
    esModuleInterop: true,
    jsx: 'react-jsx',
    skipLibCheck: true,
    isolatedModules: true,
    noEmitOnError: false,
  };

  const register = (ext) => {
    require.extensions[ext] = function transpileHook(module, filename) {
      const source = fs.readFileSync(filename, 'utf8');
      const result = ts.transpileModule(source, {
        compilerOptions,
        fileName: filename,
      });
      module._compile(result.outputText ?? '', filename);
    };
  };

  for (const ext of extensions) {
    register(ext);
  }
} catch {
  // typescript not available in this workspace; keep default behavior.
}
