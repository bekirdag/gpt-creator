import { describe, it, expect } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BIN = path.resolve(__dirname, '../bin/gpt-creator-apply-block.js');

function sh(cmd, options = {}) {
  return execSync(cmd, {
    stdio: 'pipe',
    encoding: 'utf8',
    ...options,
  }).trim();
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
    expect(second).toContain('"skipped"');
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
});
