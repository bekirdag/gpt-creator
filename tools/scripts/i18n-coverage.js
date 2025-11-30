#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const {
  discoverLocaleContexts,
  flattenLocaleTree,
  loadLocaleFile,
} = require('./i18n-utils.js');

const KEY_REGEX = /(?:\$t|\bt)\(\s*(['"])([^'"`]+)\1\s*\)/g;
const SOURCE_EXTENSIONS = new Set(['.vue', '.ts', '.tsx', '.js', '.jsx']);

function walkFiles(root) {
  const files = [];
  const stack = [root];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const absPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(absPath);
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name).toLowerCase();
        if (SOURCE_EXTENSIONS.has(ext)) {
          files.push(absPath);
        }
      }
    }
  }
  return files;
}

function extractKeysFromFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const matches = new Set();
  let match;
  while ((match = KEY_REGEX.exec(content))) {
    const key = match[2];
    if (key && !key.includes('${')) {
      matches.add(key.trim());
    }
  }
  return Array.from(matches);
}

function loadLocaleMap(context, locale) {
  const map = new Map();
  for (const relativeFile of context.baseFiles) {
    const targetPath = path.join(context.localesRoot, locale, relativeFile);
    const info = loadLocaleFile(targetPath);
    if (!info.exists || info.error) {
      continue;
    }
    for (const [key] of flattenLocaleTree(info.data)) {
      map.set(key, true);
    }
  }
  return map;
}

function buildBaseMap(context) {
  const map = new Map();
  for (const relativeFile of context.baseFiles) {
    const basePath = path.join(context.baseDir, relativeFile);
    const info = loadLocaleFile(basePath);
    if (info.error) {
      throw new Error(`Invalid JSON in ${basePath}: ${info.error.message}`);
    }
    if (!info.data || typeof info.data !== 'object' || Array.isArray(info.data)) {
      throw new Error(`Locale ${basePath} must export an object.`);
    }
    for (const [key] of flattenLocaleTree(info.data)) {
      map.set(key, true);
    }
  }
  return map;
}

function main() {
  const projectRoot = process.cwd();
  const contexts = discoverLocaleContexts(projectRoot);
  if (contexts.length === 0) {
    return 0;
  }

  const issues = [];

  for (const context of contexts) {
    const srcRoot = path.dirname(context.localesRoot);
    const appSrc = path.join(srcRoot);
    if (!fs.existsSync(appSrc) || !fs.statSync(appSrc).isDirectory()) {
      continue;
    }

    const baseMap = buildBaseMap(context);
    const localeMaps = new Map();
    for (const locale of context.targetLocales) {
      localeMaps.set(locale, loadLocaleMap(context, locale));
    }

    const files = walkFiles(appSrc);
    const usedKeys = new Map();

    for (const file of files) {
      const keys = extractKeysFromFile(file);
      if (keys.length === 0) {
        continue;
      }
      const relPath = path.relative(projectRoot, file);
      usedKeys.set(relPath, keys);
    }

    for (const [file, keys] of usedKeys) {
      for (const key of keys) {
        if (!baseMap.has(key)) {
          issues.push({
            app: context.appName,
            file,
            key,
            type: 'missing-base-locale',
          });
          continue;
        }
        for (const [locale, map] of localeMaps.entries()) {
          if (!map.has(key)) {
            issues.push({
              app: context.appName,
              file,
              key,
              locale,
              type: 'missing-locale',
            });
          }
        }
      }
    }
  }

  if (issues.length > 0) {
    console.error(JSON.stringify({ issues }, null, 2));
    return 1;
  }

  return 0;
}

if (require.main === module) {
  const exitCode = main();
  process.exitCode = exitCode;
}

module.exports = { main };
