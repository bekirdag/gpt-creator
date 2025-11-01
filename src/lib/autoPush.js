#!/usr/bin/env node

const { promisify } = require('node:util');
const { execFile: _execFile } = require('node:child_process');
const { readFile } = require('node:fs/promises');

const execFile = promisify(_execFile);

async function git(args, cwd) {
  return execFile('git', args, { cwd, env: process.env });
}

function normalizeLabel(summary) {
  if (!summary.label) return undefined;
  const collapsed = summary.label.replace(/\s+/g, ' ').trim();
  return collapsed.length > 0 ? collapsed : undefined;
}

async function commitOnly(summary, cwd) {
  const normalizedLabel = normalizeLabel(summary);
  const title = normalizedLabel ? `auto: apply ${normalizedLabel}` : 'auto: apply_patch';
  const bodyLines = (summary.files || []).map((f) => `${f.op} ${f.path}`);
  const msg = [title, '', ...bodyLines].join('\n');
  await git(['add', '-A'], cwd);
  await git(['commit', '-m', msg], cwd).catch(() => void 0);
}

async function maybeAutoPush(summary) {
  if (process.env.GC_AUTO_PUSH !== '1') return;

  const cwd = summary.cwd || process.cwd();
  const normalizedLabel = normalizeLabel(summary);

  try {
    await git(['rev-parse', '--is-inside-work-tree'], cwd);
  } catch {
    return;
  }

  const status = await git(['status', '--porcelain'], cwd);
  if (!status.stdout.trim()) return;

  const branch = (await git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd)).stdout.trim();
  const title = normalizedLabel ? `auto: apply ${normalizedLabel}` : 'auto: apply_patch';
  const bodyLines = (summary.files || []).map((f) => `${f.op} ${f.path}`);
  const msg = [title, '', ...bodyLines].join('\n');

  await git(['add', '-A'], cwd);
  try {
    await git(['commit', '-m', msg], cwd);
  } catch (error) {
    const stderr = String((error && error.stderr) || error || '');
    if (!stderr.includes('nothing to commit')) {
      throw error;
    }
    return;
  }

  if (!branch || branch === 'HEAD') {
    await commitOnly(summary, cwd);
    return;
  }

  const remote = process.env.GC_AUTO_PUSH_REMOTE || 'origin';
  const pushTarget = process.env.GC_AUTO_PUSH_BRANCH || branch;

  try {
    await git(['remote', 'get-url', remote], cwd);
    await git(['push', remote, pushTarget], cwd);
  } catch {
    // ignore push failure so the caller can continue
  }
}

async function runFromCli() {
  const summaryPath = process.argv[2];
  if (!summaryPath) return;
  try {
    const raw = await readFile(summaryPath, 'utf8');
    const summary = JSON.parse(raw);
    await maybeAutoPush(summary);
  } catch {
    // no-op
  }
}

if (require.main === module) {
  runFromCli().catch(() => {});
}
