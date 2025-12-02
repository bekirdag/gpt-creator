#!/usr/bin/env node
/* eslint-disable no-console */
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function writeOut(message) {
  fs.writeSync(process.stdout.fd, `${message}\n`);
}

function writeErr(message) {
  fs.writeSync(process.stderr.fd, `${message}\n`);
}

function run(cmd, opts = {}) {
  const res = spawnSync(cmd, {
    shell: true,
    encoding: 'utf8',
    ...opts,
  });
  const failed = res.status !== 0 || res.signal;
  if (failed) {
    const err = new Error(
      `Command failed (${cmd}): ${(res.stderr || res.stdout || res.error?.message || '').trim()}`
    );
    err.code = res.status;
    throw err;
  }
  // Some sandboxes populate res.error even when the command succeeds; tolerate that.
  return res.stdout || '';
}

function parseArgs(argv) {
  const args = {
    files: [],
    commit: true,
    fmt: false,
    allowDirty: false,
    message: '',
    dryRun: false,
    json: false,
    select: null,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--file') {
      args.files.push(argv[++i]);
    } else if (token === '--no-commit') {
      args.commit = false;
    } else if (token === '--fmt') {
      args.fmt = true;
    } else if (token === '--allow-dirty') {
      args.allowDirty = true;
    } else if (token === '--message') {
      args.message = argv[++i] || '';
    } else if (token === '--dry-run') {
      args.dryRun = true;
    } else if (token === '--json') {
      args.json = true;
    } else if (token === '--select') {
      args.select = argv[++i] || '';
    } else if (token === '--help' || token === '-h') {
      printHelp();
      process.exit(0);
    }
  }
  return args;
}

function printHelp() {
  writeOut(`Usage:
  gpt-creator apply-block [options]

Options:
  --file <block.json>   Path to block definition (repeatable).
  --fmt                 Run workspace formatter after applying blocks.
  --no-commit           Skip automatic commit.
  --allow-dirty         Allow running with a non-clean working tree.
  --message <msg>       Custom commit message.
  --dry-run             Validate & report actions without touching files.
  --json                Emit JSON summary to stdout.
  --select id1,id2      Apply only matching block IDs from provided files/stdin.

Block JSON schema:
  {
    "id": "unique-id",
    "writer": "gpt-creator",
    "mode": "overwrite|append|prepend|ensure-absent|json-merge",
    "path": "relative/path.ext",
    "chmod": "644",
    "encoding": "utf8|base64",
    "content": "..."
  }`);
}

function repoRoot() {
  try {
    const inside = run('git rev-parse --is-inside-work-tree').trim();
    if (inside !== 'true') throw new Error('not inside git repo');
    return run('git rev-parse --show-toplevel').trim();
  } catch {
    return process.cwd();
  }
}

function loadConfig(root) {
  const cfgPath = path.join(root, 'gpt-creator.config.json');
  if (!fs.existsSync(cfgPath)) {
    return {
      allowedWriters: ['gpt-creator', 'scripts/python/write_block.py', 'tools/scripts/python/write_block.py'],
      commitPrefix: 'apply-block:',
      disallowEllipses: true,
      disallowHeredocs: true,
      binaryMaxBytes: 1024 * 1024,
    };
  }
  try {
    return JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  } catch (error) {
    throw new Error(`Invalid gpt-creator.config.json: ${error.message}`);
  }
}

function dirtyCheck(allowDirty) {
  if (allowDirty) return;
  const status = run('git status --porcelain').trim();
  if (status) {
    throw new Error('Working tree is dirty. Commit/stash or pass --allow-dirty.');
  }
}

function readStdinIfAny() {
  try {
    const fd = fs.fstatSync(0);
    if (fd.isFIFO() || fd.isFile()) {
      return fs.readFileSync(0, 'utf8');
    }
  } catch {
    // ignore
  }
  return '';
}

function loadBlocks(files, selectCsv) {
  const chunks = [];
  if (files.length === 0) {
    const stdin = readStdinIfAny();
    if (stdin.trim()) {
      chunks.push(stdin);
    }
  } else {
    for (const file of files) {
      chunks.push(fs.readFileSync(file, 'utf8'));
    }
  }

  if (!chunks.length) return [];

  const parsedBlocks = [];
  for (const chunk of chunks) {
    const parsed = JSON.parse(chunk);
    if (Array.isArray(parsed)) parsedBlocks.push(...parsed);
    else parsedBlocks.push(parsed);
  }

  if (!selectCsv) return parsedBlocks;

  const allow = new Set(
    selectCsv
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  );
  return parsedBlocks.filter((block) => allow.has(block.id));
}

function validateBlock(block, root, cfg) {
  const id = String(block.id || '').trim();
  if (!id) throw new Error('Block missing "id".');

  const writer = String(block.writer || '').trim();
  if (!cfg.allowedWriters.includes(writer)) {
    throw new Error(`Block ${id} writer ${writer} is not allowed.`);
  }

  const mode = String(block.mode || 'overwrite');
  const allowedModes = new Set([
    'overwrite',
    'append',
    'prepend',
    'ensure-absent',
    'json-merge',
  ]);
  if (!allowedModes.has(mode)) {
    throw new Error(`Block ${id} has invalid mode ${mode}.`);
  }

  const rel = String(block.path || '').trim();
  if (!rel) throw new Error(`Block ${id} missing path.`);
  if (rel.includes('\0')) throw new Error(`Block ${id} path contains null byte.`);
  const abs = path.resolve(root, rel);
  const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (!abs.startsWith(rootWithSep)) {
    throw new Error(`Block ${id} escapes repository root.`);
  }

  const encoding = block.encoding || 'utf8';
  if (!['utf8', 'base64'].includes(encoding)) {
    throw new Error(`Block ${id} has unsupported encoding ${encoding}.`);
  }

  if (cfg.disallowEllipses && typeof block.content === 'string') {
    if (/\.\.\.|…/.test(block.content)) {
      throw new Error(`Block ${id} contains ellipses. Provide full content.`);
    }
  }

  if (cfg.disallowHeredocs && typeof block.content === 'string') {
    if (/<<\s*['"]?[A-Z0-9_]+['"]?/i.test(block.content)) {
      throw new Error(`Block ${id} appears to contain heredoc markers.`);
    }
  }

  return { id, abs, rel, mode, writer, encoding };
}

function ensureDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function atomicWriteFileSync(target, buffer) {
  const dir = path.dirname(target);
  const tmp = path.join(
    dir,
    `.${path.basename(target)}.${process.pid}.${Date.now()}.${crypto
      .randomBytes(4)
      .toString('hex')}`
  );

  fs.writeFileSync(tmp, buffer);
  try {
    const fd = fs.openSync(tmp, 'r');
    fs.fsyncSync(fd);
    fs.closeSync(fd);
  } catch {
    // ignore fsync failures (best-effort)
  }
  fs.renameSync(tmp, target);
  try {
    const dirFd = fs.openSync(dir, 'r');
    fs.fsyncSync(dirFd);
    fs.closeSync(dirFd);
  } catch {
    // ignore
  }
}

function normalizeText(str) {
  const normalized = str.replace(/\r\n/g, '\n');
  return normalized.endsWith('\n') ? normalized : `${normalized}\n`;
}

function deepMergeJson(base, patch) {
  if (Array.isArray(base) || Array.isArray(patch)) return patch;
  if (typeof base !== 'object' || base === null) return patch;
  if (typeof patch !== 'object' || patch === null) return patch;
  const out = { ...base };
  for (const key of Object.keys(patch)) {
    out[key] = deepMergeJson(base[key], patch[key]);
  }
  return out;
}

function textToBuffer(content, encoding) {
  if (encoding === 'base64') {
    return Buffer.from(String(content || ''), 'base64');
  }
  return Buffer.from(normalizeText(String(content ?? '')), 'utf8');
}

function fileBuffer(target) {
  try {
    return fs.readFileSync(target);
  } catch {
    return null;
  }
}

function buffersEqual(a, b) {
  if (!a || !b) return false;
  if (a.length !== b.length) return false;
  if (a.length === 0) return true;
  return crypto.timingSafeEqual(a, b);
}

function stage(rel) {
  run(`git add -- "${rel}"`);
}

function stageRemoval(rel) {
  try {
    run(`git rm -f -- "${rel}"`);
  } catch {
    run('git add -A');
  }
}

function maybeFmt() {
  try {
    run('pnpm -w run fmt', { stdio: 'inherit' });
  } catch {
    try {
      run('pnpm run fmt', { stdio: 'inherit' });
    } catch {
      // ignore
    }
  }
  try {
    run('git add -A');
  } catch {
    // ignore
  }
}

function hasStagedChanges() {
  try {
    run('git diff --cached --quiet');
    return false;
  } catch {
    return true;
  }
}

function enforceBinaryLimit(buffer, cfg, id) {
  if (!cfg.binaryMaxBytes) return;
  if (buffer.length > cfg.binaryMaxBytes) {
    throw new Error(
      `Block ${id} payload exceeds binaryMaxBytes (${cfg.binaryMaxBytes}).`
    );
  }
}

function main() {
  const args = parseArgs(process.argv);
  const root = repoRoot();
  const cfg = loadConfig(root);
  dirtyCheck(args.allowDirty);

  const blocks = loadBlocks(args.files, args.select);
  if (!blocks.length) {
    throw new Error('No blocks provided via --file or stdin.');
  }

  const applied = [];
  const skipped = [];
  const actions = [];

  for (const block of blocks) {
    const { id, abs, rel, mode, encoding } = validateBlock(block, root, cfg);
    ensureDir(abs);

    if (mode === 'ensure-absent') {
      if (fs.existsSync(abs)) {
        actions.push({ id, action: 'delete', path: rel });
        if (!args.dryRun) {
          fs.rmSync(abs, { force: true });
          stageRemoval(rel);
        }
        applied.push(id);
      } else {
        skipped.push({ id, reason: 'absent-already' });
      }
      continue;
    }

    let nextBuf;
    if (mode === 'json-merge') {
      const existing = fileBuffer(abs);
      let base = {};
      if (existing) {
        try {
          base = JSON.parse(existing.toString('utf8'));
        } catch {
          base = {};
        }
      }
      let patch = block.content;
      if (typeof block.content === 'string') {
        patch = JSON.parse(block.content);
      }
      const merged = deepMergeJson(base, patch);
      nextBuf = Buffer.from(`${JSON.stringify(merged, null, 2)}\n`, 'utf8');
    } else if (mode === 'append' || mode === 'prepend') {
      const existing = fileBuffer(abs) || Buffer.from('', 'utf8');
      const addition = textToBuffer(block.content || '', encoding);
      nextBuf =
        mode === 'append'
          ? Buffer.concat([existing, addition])
          : Buffer.concat([addition, existing]);
    } else {
      nextBuf = textToBuffer(block.content || '', encoding);
    }

    enforceBinaryLimit(nextBuf, cfg, id);

    const current = fileBuffer(abs);
    if (buffersEqual(current, nextBuf)) {
      skipped.push({ id, reason: 'no-op' });
      continue;
    }

    actions.push({ id, action: 'write', path: rel, bytes: nextBuf.length, mode });
    if (!args.dryRun) {
      atomicWriteFileSync(abs, nextBuf);
      if (block.chmod) {
        fs.chmodSync(abs, parseInt(String(block.chmod), 8));
      }
      stage(rel);
    }
    applied.push(id);
  }

  if (args.fmt && !args.dryRun) {
    maybeFmt();
  }

  let committed = false;
  let commitSha = '';
  if (args.commit && !args.dryRun && hasStagedChanges()) {
    const message =
      args.message ||
      `${cfg.commitPrefix} ${applied.length ? applied.join(', ') : 'update'}`;
    run(`git commit -m "${message.replace(/"/g, '\\"')}"`, {
      stdio: 'inherit',
    });
    commitSha = run('git rev-parse --short HEAD').trim();
    committed = true;
  }

  const report = { ok: true, applied, skipped, committed, commitSha, actions };
  if (args.json) {
    writeOut(JSON.stringify(report, null, 2));
  } else {
    writeOut(
      [
        `[apply-block] applied=${applied.length}`,
        `skipped=${skipped.length}`,
        committed ? `commit=${commitSha}` : 'commit=skipped',
      ].join(' ')
    );
  }
}

try {
  main();
} catch (error) {
  writeErr(`[apply-block] ${error.message || error}`);
  process.exit(1);
}
