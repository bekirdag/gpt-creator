#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === '[object Object]';
}

function readDirSafe(dirPath) {
  try {
    return fs.readdirSync(dirPath, { withFileTypes: true });
  } catch {
    return [];
  }
}

function normaliseNewlines(text) {
  return (text || '').replace(/\r\n/g, '\n');
}

function ensureDirSync(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

function listJsonFiles(baseDir) {
  const results = [];
  const stack = [{ dir: baseDir, prefix: '' }];

  while (stack.length > 0) {
    const { dir, prefix } = stack.pop();
    const entries = readDirSafe(dir);
    for (const entry of entries) {
      const relName = prefix ? path.join(prefix, entry.name) : entry.name;
      const absPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        stack.push({ dir: absPath, prefix: relName });
      } else if (entry.isFile() && entry.name.endsWith('.json')) {
        results.push(relName);
      }
    }
  }

  results.sort((a, b) => a.localeCompare(b));
  return results;
}

function loadLocaleFile(filePath) {
  const exists = fs.existsSync(filePath);
  if (!exists) {
    return { exists: false, data: {}, raw: '', error: null };
  }
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const data = JSON.parse(raw);
    return { exists: true, data, raw, error: null };
  } catch (error) {
    let raw = '';
    try {
      raw = fs.readFileSync(filePath, 'utf8');
    } catch {
      raw = '';
    }
    return { exists: true, data: {}, raw, error };
  }
}

function flattenLocaleTree(value, prefix = '') {
  const entries = [];
  if (isPlainObject(value)) {
    for (const key of Object.keys(value)) {
      const nextPrefix = prefix ? `${prefix}${key}.` : `${key}.`;
      entries.push(...flattenLocaleTree(value[key], nextPrefix));
    }
  } else {
    const key = prefix.endsWith('.') ? prefix.slice(0, -1) : prefix;
    entries.push([key, value == null ? '' : String(value)]);
  }
  return entries;
}

function placeholdersFor(text) {
  const matches = String(text || '').match(/\{[a-zA-Z0-9_]+\}/g);
  if (!matches) {
    return [];
  }
  const unique = Array.from(new Set(matches));
  unique.sort();
  return unique;
}

function sortObjectDeep(value) {
  if (Array.isArray(value)) {
    return value.map((item) => (isPlainObject(item) || Array.isArray(item) ? sortObjectDeep(item) : item));
  }
  if (!isPlainObject(value)) {
    return value;
  }
  const sortedKeys = Object.keys(value).sort((a, b) => a.localeCompare(b));
  const result = {};
  for (const key of sortedKeys) {
    const child = value[key];
    if (isPlainObject(child) || Array.isArray(child)) {
      result[key] = sortObjectDeep(child);
    } else {
      result[key] = child;
    }
  }
  return result;
}

function serialiseLocale(value) {
  const sorted = sortObjectDeep(value);
  return `${JSON.stringify(sorted, null, 2)}\n`;
}

function discoverLocaleContexts(projectRoot, baseLocale = 'en') {
  const contexts = [];
  const appsRoot = path.join(projectRoot, 'apps');
  const appEntries = readDirSafe(appsRoot).filter((entry) => entry.isDirectory());
  for (const appEntry of appEntries) {
    const localesRoot = path.join(appsRoot, appEntry.name, 'src', 'locales');
    if (!fs.existsSync(localesRoot)) {
      continue;
    }
    const baseDir = path.join(localesRoot, baseLocale);
    if (!fs.existsSync(baseDir) || !fs.statSync(baseDir).isDirectory()) {
      continue;
    }
    const targetLocales = new Set();
    for (const entry of readDirSafe(localesRoot)) {
      if (entry.isDirectory() && entry.name !== baseLocale) {
        targetLocales.add(entry.name);
      }
    }
    if (targetLocales.size === 0) {
      continue;
    }
    const baseFiles = listJsonFiles(baseDir);
    contexts.push({
      appName: appEntry.name,
      localesRoot,
      baseLocale,
      baseDir,
      targetLocales: Array.from(targetLocales).sort((a, b) => a.localeCompare(b)),
      baseFiles,
    });
  }
  return contexts;
}

function collectLocaleIssues(projectRoot) {
  const contexts = discoverLocaleContexts(projectRoot);
  const issues = [];

  for (const context of contexts) {
    const baseCache = new Map();

    for (const relativeFile of context.baseFiles) {
      const basePath = path.join(context.baseDir, relativeFile);
      let baseInfo = baseCache.get(relativeFile);
      if (!baseInfo) {
        baseInfo = loadLocaleFile(basePath);
        baseCache.set(relativeFile, baseInfo);
      }

      if (baseInfo.error) {
        issues.push({
          app: context.appName,
          locale: context.baseLocale,
          file: relativeFile,
          type: 'invalid-json',
          message: baseInfo.error.message || String(baseInfo.error),
        });
        continue;
      }

      if (!isPlainObject(baseInfo.data)) {
        issues.push({
          app: context.appName,
          locale: context.baseLocale,
          file: relativeFile,
          type: 'invalid-structure',
          message: 'Base locale root must be an object.',
        });
        continue;
      }

      const baseMap = Object.fromEntries(flattenLocaleTree(baseInfo.data));

      for (const locale of context.targetLocales) {
        const targetPath = path.join(context.localesRoot, locale, relativeFile);
        const targetInfo = loadLocaleFile(targetPath);

        if (targetInfo.error) {
          issues.push({
            app: context.appName,
            locale,
            file: relativeFile,
            type: 'invalid-json',
            message: targetInfo.error.message || String(targetInfo.error),
          });
          continue;
        }

        if (!targetInfo.exists) {
          issues.push({
            app: context.appName,
            locale,
            file: relativeFile,
            type: 'missing-file',
            missingKeys: Object.keys(baseMap),
          });
          continue;
        }

        if (!isPlainObject(targetInfo.data)) {
          issues.push({
            app: context.appName,
            locale,
            file: relativeFile,
            type: 'invalid-structure',
            message: 'Locale file must export an object.',
          });
          continue;
        }

        const targetMap = Object.fromEntries(flattenLocaleTree(targetInfo.data));

        const missingKeys = Object.keys(baseMap).filter((key) => !(key in targetMap));
        const extraKeys = Object.keys(targetMap).filter((key) => !(key in baseMap));
        const placeholderMismatch = [];
        for (const key of Object.keys(baseMap)) {
          if (!(key in targetMap)) {
            continue;
          }
          const baseVars = placeholdersFor(baseMap[key]);
          const targetVars = placeholdersFor(targetMap[key]);
          if (baseVars.length !== targetVars.length || baseVars.some((value, idx) => value !== targetVars[idx])) {
            placeholderMismatch.push({
              key,
              base: baseVars,
              locale: targetVars,
            });
          }
        }

        const expectedSerialised = serialiseLocale(targetInfo.data);
        const actualSerialised = `${normaliseNewlines(targetInfo.raw)}${targetInfo.raw.endsWith('\n') ? '' : '\n'}`.replace(/\r\n/g, '\n');
        const formatMismatch = expectedSerialised !== actualSerialised;

        if (missingKeys.length || extraKeys.length || placeholderMismatch.length || formatMismatch) {
          const issue = {
            app: context.appName,
            locale,
            file: relativeFile,
          };
          if (missingKeys.length) {
            issue.missingKeys = missingKeys;
          }
          if (extraKeys.length) {
            issue.extraKeys = extraKeys;
          }
          if (placeholderMismatch.length) {
            issue.placeholderMismatch = placeholderMismatch;
          }
          if (formatMismatch) {
            issue.formatMismatch = true;
          }
          issues.push(issue);
        }
      }
    }
  }

  return { contexts, issues };
}

function mergeLocaleTrees(baseNode, targetNode) {
  if (Array.isArray(baseNode)) {
    if (Array.isArray(targetNode)) {
      return { value: targetNode.slice(), changed: false };
    }
    return { value: baseNode.slice(), changed: true };
  }

  if (isPlainObject(baseNode)) {
    const result = {};
    const keys = new Set(Object.keys(baseNode));
    if (isPlainObject(targetNode)) {
      for (const key of Object.keys(targetNode)) {
        keys.add(key);
      }
    }
    let changed = false;
    for (const key of Array.from(keys).sort((a, b) => a.localeCompare(b))) {
      const baseHas = Object.prototype.hasOwnProperty.call(baseNode, key);
      const targetHas = isPlainObject(targetNode) && Object.prototype.hasOwnProperty.call(targetNode, key);
      const baseValue = baseHas ? baseNode[key] : undefined;
      const targetValue = targetHas ? targetNode[key] : undefined;

      if (baseHas && isPlainObject(baseValue)) {
        const childTarget = isPlainObject(targetValue) ? targetValue : {};
        const childResult = mergeLocaleTrees(baseValue, childTarget);
        result[key] = childResult.value;
        if (childResult.changed || (!targetHas || !isPlainObject(targetValue))) {
          changed = true;
        }
      } else if (baseHas) {
        if (!targetHas) {
          result[key] = `TODO_${baseValue == null ? '' : String(baseValue)}`;
          changed = true;
        } else if (isPlainObject(targetValue)) {
          result[key] = `TODO_${baseValue == null ? '' : String(baseValue)}`;
          changed = true;
        } else {
          result[key] = targetValue;
        }
      } else if (targetHas) {
        result[key] = targetValue;
      }
    }
    return { value: result, changed };
  }

  if (targetNode === undefined) {
    return { value: `TODO_${baseNode == null ? '' : String(baseNode)}`, changed: true };
  }
  if (isPlainObject(targetNode) || Array.isArray(targetNode)) {
    return { value: `TODO_${baseNode == null ? '' : String(baseNode)}`, changed: true };
  }
  return { value: targetNode, changed: false };
}

function findLocaleRejects(projectRoot) {
  const rejects = new Set();
  const appsRoot = path.join(projectRoot, 'apps');
  if (fs.existsSync(appsRoot)) {
    const rootStack = [appsRoot];
    while (rootStack.length > 0) {
      const current = rootStack.pop();
      for (const entry of readDirSafe(current)) {
        const absPath = path.join(current, entry.name);
        if (entry.isDirectory()) {
          rootStack.push(absPath);
        } else if (
          entry.isFile() &&
          entry.name.endsWith('.rej') &&
          absPath.split(path.sep).includes('locales')
        ) {
          rejects.add(absPath);
        }
      }
    }
  }

  const contexts = discoverLocaleContexts(projectRoot);
  for (const context of contexts) {
    const stack = [context.localesRoot];
    while (stack.length > 0) {
      const current = stack.pop();
      for (const entry of readDirSafe(current)) {
        const absPath = path.join(current, entry.name);
        if (entry.isDirectory()) {
          stack.push(absPath);
        } else if (entry.isFile() && entry.name.endsWith('.rej')) {
          rejects.add(absPath);
        }
      }
    }
  }

  return Array.from(rejects).sort((a, b) => a.localeCompare(b));
}

module.exports = {
  collectLocaleIssues,
  discoverLocaleContexts,
  ensureDirSync,
  findLocaleRejects,
  flattenLocaleTree,
  loadLocaleFile,
  mergeLocaleTrees,
  normaliseNewlines,
  serialiseLocale,
  sortObjectDeep,
};
