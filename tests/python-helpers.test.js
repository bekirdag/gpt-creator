import { describe, it, expect } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { spawnSync } from 'child_process';

function sh(cmd, options = {}) {
  const res = spawnSync('bash', ['-lc', cmd], {
    encoding: 'utf8',
    stdio: 'pipe',
    ...options,
  });
  if (res.status !== 0) {
    const msg = res.stderr || res.stdout || res.error?.message || `command failed: ${cmd}`;
    throw new Error(msg.trim());
  }
  return (res.stdout || '').trim();
}

describe('gc_clone_python_tool sidecar handling', () => {
  it('copies companion _lib.py files into shims', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gc-sidecar-'));
    const fsHelper = path.resolve('scripts/lib/fs.sh');
    const out = sh(
      `source "${fsHelper}" && CLI_ROOT="${process.cwd()}" gc_clone_python_tool estimate_remaining_work.py "${tmp}"`
    );
    const shimDir = path.dirname(out);
    const files = fs.readdirSync(shimDir);
    expect(files).toContain('estimate_remaining_work.py');
    expect(files).toContain('estimate_remaining_work_lib.py');
  });
});
