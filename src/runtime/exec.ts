import path from 'node:path';
import { rewriteForTsc } from './command-rewriter';

const JEST_PATTERN = /\bjest(\.js)?\b/;
const PNPM_JEST_PATTERN = /\bpnpm\s+test\b.*\bjest\b/;
const VITEST_PATTERN = /\bvitest\b/;
const THREADS_PATTERN = /\b--threads\b/;

const RUNTIME_DIR =
  process.env.GC_RUNTIME_DIR ||
  path.resolve(__dirname, '..', '..', 'runtime');

function hasFlag(cmd: string, flag: string): boolean {
  const rx = new RegExp(`\\b${flag}(?:\\b|=)`);
  return rx.test(cmd);
}

function applyJestOverlay(command: string): string {
  let next = command;
  if (!hasFlag(next, '--runInBand')) {
    next += ' --runInBand';
  }
  if (!hasFlag(next, '--testTimeout')) {
    next += ` --testTimeout ${process.env.GC_JEST_TIMEOUT || 60000}`;
  }
  if (!hasFlag(next, '--setupFilesAfterEnv')) {
    next += ` --setupFilesAfterEnv "${path.join(RUNTIME_DIR, 'jest-setup.js')}"`;
  }
  if (!hasFlag(next, '--resolver') && process.env.GC_JEST_RESOLVER !== '0') {
    next += ` --resolver "${path.join(RUNTIME_DIR, 'jest-resolver.cjs')}"`;
  }
  return next;
}

export function decorateCommand(cmd: string): string {
  let decorated = cmd.trim();
  const isJest = JEST_PATTERN.test(decorated) || PNPM_JEST_PATTERN.test(decorated);
  if (isJest) {
    decorated = applyJestOverlay(decorated);
  } else if (VITEST_PATTERN.test(decorated) && !THREADS_PATTERN.test(decorated)) {
    decorated += ' --threads 1';
  }
  return decorated;
}

export function prepareCommand(cmd: string): string {
  return decorateCommand(rewriteForTsc(cmd));
}
