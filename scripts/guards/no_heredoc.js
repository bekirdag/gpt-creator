#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require('fs');
const { spawnSync } = require('child_process');

function sh(command) {
  const res = spawnSync(command, { shell: true, encoding: 'utf8' });
  if (res.status !== 0) {
    return '';
  }
  return res.stdout;
}

function listFiles(all) {
  const cmd = all
    ? 'git ls-files -z'
    : 'git diff --cached --name-only -z';
  const output = sh(cmd);
  if (!output) return [];
  return output
    .split('\0')
    .map((entry) => entry.trim())
    .filter(Boolean)
    .filter((entry) => !entry.startsWith('node_modules/'));
}

function fileText(pathname) {
  try {
    const buf = fs.readFileSync(pathname);
    if (buf.includes(0)) return '';
    return buf.toString('utf8');
  } catch {
    return '';
  }
}

const scanAll = process.argv.includes('--all');
const files = listFiles(scanAll);
if (!files.length) {
  process.exit(0);
}

const offenders = [];
const BASH_CAT = /bash\s+-lc\s+["'][^"']*cat\s*<<['"]?EOF['"]?/i;
const CURL_PIPE = /curl\b[^|]+?\|\s*(bash|sh)\b/i;
const ELLIPSES = /(^|\n)\s*[.\u2026]{3}\s*($|\n)/;

for (const file of files) {
  const text = fileText(file);
  if (!text) continue;
  if (BASH_CAT.test(text) || CURL_PIPE.test(text) || ELLIPSES.test(text)) {
    offenders.push(file);
  }
}

if (offenders.length) {
  console.error('Guard rails: replace heredocs/ellipses with gpt-creator apply-block or scripts/python/write_block.py.');
  offenders.forEach((file) => console.error(`  - ${file}`));
  process.exit(1);
}
