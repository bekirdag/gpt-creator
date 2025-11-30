import { describe, it, expect } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { spawnSync } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BIN = path.resolve(__dirname, '../bin/gpt-creator-apply-block.js');

function sh(cmd, options = {}) {
  const res = spawnSync(cmd, {
    shell: true,
    encoding: 'utf8',
    stdio: 'pipe',
    ...options,
  });
  if (res.status !== 0) {
    const msg = res.stderr || res.stdout || res.error?.message || `command failed: ${cmd}`;
    const err = new Error(msg.trim());
    err.stdout = res.stdout;
    err.stderr = res.stderr;
    throw err;
  }
  // Some sandboxes set res.error even when the command succeeds; ignore it if status is 0.
  return (res.stdout || '').trim();
}

function initRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'apply-block-'));
  sh('git init', { cwd: dir });
  sh('git config user.email tester@example.com', { cwd: dir });
  sh('git config user.name Tester', { cwd: dir });
  fs.writeFileSync(path.join(dir, 'README.md'), '# tmp\n', 'utf8');
  sh('git add README.md', { cwd: dir });
  sh('git commit -m "init"', { cwd: dir });
  return dir;
}

describe('gpt-creator apply-block CLI', () => {
  it('overwrites files idempotently', () => {
    const repo = initRepo();
    const blockPath = path.join(repo, 'block.json');
    const block = {
      id: 'hello-file',
      writer: 'gpt-creator',
      mode: 'overwrite',
      path: 'src/hello.txt',
      content: 'hi there\n',
    };
    fs.writeFileSync(blockPath, JSON.stringify(block), 'utf8');
    sh(`node "${BIN}" --file "${blockPath}" --allow-dirty --no-commit --json`, {
      cwd: repo,
    });
    expect(fs.readFileSync(path.join(repo, 'src/hello.txt'), 'utf8')).toBe('hi there\n');

    const second = sh(
      `node "${BIN}" --file "${blockPath}" --allow-dirty --no-commit --json`,
      { cwd: repo }
    );
    const parsed = JSON.parse(second);
    expect(parsed.skipped.length).toBe(1);
    expect(parsed.skipped[0].id).toBe('hello-file');
  });

  it('merges JSON content deeply', () => {
    const repo = initRepo();
    const target = path.join(repo, 'cfg/app.json');
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(
      target,
      JSON.stringify({ alpha: 1, nested: { beta: true } }, null, 2),
      'utf8'
    );

    const block = {
      id: 'json-merge',
      writer: 'gpt-creator',
      mode: 'json-merge',
      path: 'cfg/app.json',
      content: { gamma: 3, nested: { beta: false, delta: true } },
    };
    const blockPath = path.join(repo, 'merge.json');
    fs.writeFileSync(blockPath, JSON.stringify(block), 'utf8');
    sh(`node "${BIN}" --file "${blockPath}" --allow-dirty --no-commit --json`, {
      cwd: repo,
    });

    const merged = JSON.parse(fs.readFileSync(target, 'utf8'));
    expect(merged).toEqual({
      alpha: 1,
      gamma: 3,
      nested: { beta: false, delta: true },
    });
  });

  it('removes files via ensure-absent', () => {
    const repo = initRepo();
    const doomed = path.join(repo, 'tmp/remove.me');
    fs.mkdirSync(path.dirname(doomed), { recursive: true });
    fs.writeFileSync(doomed, 'bye', 'utf8');
    const block = {
      id: 'ensure-absent',
      writer: 'gpt-creator',
      mode: 'ensure-absent',
      path: 'tmp/remove.me',
    };
    const blockPath = path.join(repo, 'remove.json');
    fs.writeFileSync(blockPath, JSON.stringify(block), 'utf8');
    sh(`node "${BIN}" --file "${blockPath}" --allow-dirty --no-commit --json`, {
      cwd: repo,
    });
    expect(fs.existsSync(doomed)).toBe(false);
  });

  it('appends and prepends content', () => {
    const repo = initRepo();
    const target = path.join(repo, 'notes.txt');
    fs.writeFileSync(target, 'start\n', 'utf8');

    const appendBlock = {
      id: 'append-note',
      writer: 'gpt-creator',
      mode: 'append',
      path: 'notes.txt',
      content: 'second\n',
    };
    const prependBlock = {
      id: 'prepend-note',
      writer: 'gpt-creator',
      mode: 'prepend',
      path: 'notes.txt',
      content: 'first\n',
    };

    const appendPath = path.join(repo, 'append.json');
    fs.writeFileSync(appendPath, JSON.stringify(appendBlock), 'utf8');
    sh(`node "${BIN}" --file "${appendPath}" --allow-dirty --no-commit --json`, {
      cwd: repo,
    });

    const prependPath = path.join(repo, 'prepend.json');
    fs.writeFileSync(prependPath, JSON.stringify(prependBlock), 'utf8');
    sh(`node "${BIN}" --file "${prependPath}" --allow-dirty --no-commit --json`, {
      cwd: repo,
    });

    const final = fs.readFileSync(target, 'utf8');
    expect(final).toBe('first\nstart\nsecond\n');
  });

  it('applies only selected block IDs', () => {
    const repo = initRepo();
    const blocks = [
      {
        id: 'apply-me',
        writer: 'gpt-creator',
        mode: 'overwrite',
        path: 'only/me.txt',
        content: 'hello\n',
      },
      {
        id: 'skip-me',
        writer: 'gpt-creator',
        mode: 'overwrite',
        path: 'only/skip.txt',
        content: 'bye\n',
      },
    ];
    const blockPath = path.join(repo, 'blocks.json');
    fs.writeFileSync(blockPath, JSON.stringify(blocks), 'utf8');
    const output = sh(
      `node "${BIN}" --file "${blockPath}" --allow-dirty --no-commit --json --select apply-me`,
      { cwd: repo }
    );
    const parsed = JSON.parse(output);
    expect(parsed.applied).toEqual(['apply-me']);
    expect(parsed.skipped.length).toBe(0);
    expect(fs.existsSync(path.join(repo, 'only/me.txt'))).toBe(true);
    expect(fs.existsSync(path.join(repo, 'only/skip.txt'))).toBe(false);
  });

  it('reports actions without touching files in dry-run mode', () => {
    const repo = initRepo();
    const block = {
      id: 'dry-run-write',
      writer: 'gpt-creator',
      mode: 'overwrite',
      path: 'dry-run.txt',
      content: 'hello\n',
    };
    const blockPath = path.join(repo, 'dry.json');
    fs.writeFileSync(blockPath, JSON.stringify(block), 'utf8');
    const out = sh(
      `node "${BIN}" --file "${blockPath}" --allow-dirty --no-commit --json --dry-run`,
      { cwd: repo }
    );
    const parsed = JSON.parse(out);
    expect(parsed.actions[0]).toMatchObject({ id: 'dry-run-write', action: 'write' });
    expect(parsed.committed).toBe(false);
    expect(fs.existsSync(path.join(repo, 'dry-run.txt'))).toBe(false);
  });
});
