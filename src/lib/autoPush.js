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

function sanitizeSegment(value) {
  return value.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

async function ensureRepository(cwd) {
  await git(['rev-parse', '--is-inside-work-tree'], cwd);
}

function resolveTaskRef(summary) {
  const explicit = process.env.GC_AUTOPUSH_TASK_REF;
  if (explicit && explicit.trim()) {
    return sanitizeSegment(explicit.trim());
  }
  const label = normalizeLabel(summary);
  if (label) {
    return sanitizeSegment(label);
  }
  return 'task';
}

function resolveVerifySuffix() {
  const status = (process.env.GC_AUTOPUSH_VERIFY_STATUS || '').trim().toLowerCase();
  if (!status) return '';
  if (status === 'pass' || status === 'verified') {
    return ' [verified]';
  }
  return ` [verify:${status}]`;
}

async function resolveCurrentBranch(cwd) {
  const branch = (await git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd)).stdout.trim();
  return branch || 'HEAD';
}

async function performAutoPush(summary) {
  const cwd = summary.cwd || process.cwd();
  await ensureRepository(cwd);

  const allowEmpty = process.env.GC_ALLOW_EMPTY_COMMIT !== '0';
  const remote = process.env.GC_AUTO_PUSH_REMOTE || 'origin';
  let targetBranch = (process.env.GC_AUTO_PUSH_BRANCH || '').trim();
  const preferMain = process.env.GC_AUTO_PUSH_MAIN === '1';

  const taskRef = resolveTaskRef(summary) || 'task';
  const verifySuffix = resolveVerifySuffix();
  const commitMessage = `chore(gpt-creator): complete ${taskRef}${verifySuffix}`;

  await git(['add', '-A'], cwd);
  const commitArgs = ['commit', '-m', commitMessage];
  if (allowEmpty) {
    commitArgs.splice(1, 0, '--allow-empty');
  }

  let commitStatus = 'clean';
  let commitSha = '';

  try {
    await git(commitArgs, cwd);
    commitStatus = 'committed';
    commitSha = (await git(['rev-parse', 'HEAD'], cwd)).stdout.trim();
  } catch (error) {
    const stderr = String((error && error.stderr) || error || '');
    if (stderr.includes('nothing to commit')) {
      commitStatus = 'clean';
      commitSha = (await git(['rev-parse', 'HEAD'], cwd)).stdout.trim();
    } else {
      commitStatus = 'failed';
      throw new Error(stderr || 'commit failed');
    }
  }

  const branchAlias = `gc/${sanitizeSegment(taskRef) || taskRef}`;
  await git(['branch', '-f', branchAlias], cwd).catch(() => void 0);

  const currentBranch = await resolveCurrentBranch(cwd);
  if (!targetBranch || targetBranch === 'HEAD') {
    targetBranch = preferMain ? 'main' : currentBranch;
  }

  if (remote === '__skip__') {
    return {
      commitStatus,
      commitSha,
      pushStatus: 'skipped',
      remote,
      branch: targetBranch,
    };
  }

  await git(['remote', 'get-url', remote], cwd);

  if (targetBranch) {
    await git(['fetch', remote, targetBranch], cwd);
    try {
      await git(['rebase', `${remote}/${targetBranch}`], cwd);
    } catch (error) {
      await git(['rebase', '--abort'], cwd).catch(() => void 0);
      throw new Error(String((error && error.stderr) || error || 'rebase failed'));
    }
    await git(['branch', '-f', branchAlias], cwd).catch(() => void 0);
  }

  const pushArgs = ['push', '--atomic', remote];
  if (targetBranch) {
    pushArgs.push(`HEAD:${targetBranch}`);
  }
  pushArgs.push(`${branchAlias}:${branchAlias}`);

  try {
    await git(pushArgs, cwd);
    return {
      commitStatus,
      commitSha,
      pushStatus: 'pushed',
      remote,
      branch: targetBranch,
    };
  } catch (error) {
    const errText = String((error && error.stderr) || error || 'push failed');
    return {
      commitStatus,
      commitSha,
      pushStatus: 'failed',
      remote,
      branch: targetBranch,
      error: errText,
    };
  }
}

async function maybeAutoPush(summary) {
  if (process.env.GC_AUTO_PUSH !== '1') return undefined;
  return performAutoPush(summary);
}

async function runFromCli() {
  const summaryPath = process.argv[2];
  if (!summaryPath) return;
  try {
    const raw = await readFile(summaryPath, 'utf8');
    const summary = JSON.parse(raw);
    const result = await maybeAutoPush(summary);
    if (process.env.GC_AUTOPUSH_EXPECT_JSON === '1') {
      const payload =
        result || {
          commitStatus: 'skipped',
          commitSha: '',
          pushStatus: 'skipped',
          remote: '',
          branch: '',
        };
      console.log(JSON.stringify(payload));
    }
  } catch (error) {
    const errPayload = {
      commitStatus: 'failed',
      commitSha: '',
      pushStatus: 'failed',
      remote: process.env.GC_AUTO_PUSH_REMOTE || 'origin',
      branch: process.env.GC_AUTO_PUSH_BRANCH || '',
      error: String((error && error.stderr) || error || 'auto-push failure'),
    };
    if (process.env.GC_AUTOPUSH_EXPECT_JSON === '1') {
      console.log(JSON.stringify(errPayload));
    } else {
      process.exitCode = 1;
    }
  }
}

if (require.main === module) {
  runFromCli();
}

module.exports = { maybeAutoPush };
