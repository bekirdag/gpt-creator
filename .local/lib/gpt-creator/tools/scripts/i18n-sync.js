#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const {
  collectLocaleIssues,
  discoverLocaleContexts,
  ensureDirSync,
  findLocaleRejects,
  loadLocaleFile,
  mergeLocaleTrees,
  normaliseNewlines,
  serialiseLocale,
} = require('./i18n-utils.js');

function main() {
  const projectRoot = process.cwd();
  const contexts = discoverLocaleContexts(projectRoot);

  if (contexts.length === 0) {
    return 0;
  }

  const rejectPaths = findLocaleRejects(projectRoot);
  if (rejectPaths.length > 0) {
    console.error(
      JSON.stringify(
        {
          error: 'locale-conflict',
          message: 'Resolve merge rejects under locales/ before running i18n-sync.',
          files: rejectPaths,
        },
        null,
        2,
      ),
    );
    return 3;
  }

  let hadError = false;
  const changedFiles = [];

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
        console.error(
          JSON.stringify(
            {
              error: 'invalid-base-locale',
              app: context.appName,
              file: relativeFile,
              message: baseInfo.error.message || String(baseInfo.error),
            },
            null,
            2,
          ),
        );
        hadError = true;
        continue;
      }

      if (baseInfo.data === null || typeof baseInfo.data !== 'object' || Array.isArray(baseInfo.data)) {
        console.error(
          JSON.stringify(
            {
              error: 'invalid-base-structure',
              app: context.appName,
              file: relativeFile,
              message: 'Base locale must be an object tree.',
            },
            null,
            2,
          ),
        );
        hadError = true;
        continue;
      }

      for (const locale of context.targetLocales) {
        const targetPath = path.join(context.localesRoot, locale, relativeFile);
        const targetInfo = loadLocaleFile(targetPath);

        if (targetInfo.error) {
          console.error(
            JSON.stringify(
              {
                error: 'invalid-locale-json',
                app: context.appName,
                locale,
                file: relativeFile,
                message: targetInfo.error.message || String(targetInfo.error),
              },
              null,
              2,
            ),
          );
          hadError = true;
          continue;
        }

        const reference = targetInfo.exists ? targetInfo.data : {};
        const merged = mergeLocaleTrees(baseInfo.data, reference).value;
        const output = serialiseLocale(merged);

        if (!targetInfo.exists || normaliseNewlines(targetInfo.raw) !== normaliseNewlines(output)) {
          ensureDirSync(path.dirname(targetPath));
          fs.writeFileSync(targetPath, output, 'utf8');
          const relativeOut = path.relative(projectRoot, targetPath);
          changedFiles.push(relativeOut);
        }
      }
    }
  }

  if (hadError) {
    return 1;
  }

  const checkResult = collectLocaleIssues(projectRoot);
  if (checkResult.issues.length > 0) {
    console.error(
      JSON.stringify(
        {
          error: 'post-sync-check-failed',
          issues: checkResult.issues,
        },
        null,
        2,
      ),
    );
    return 2;
  }

  if (changedFiles.length > 0) {
    console.log(
      JSON.stringify(
        {
          updated: changedFiles,
        },
        null,
        2,
      ),
    );
  }

  return 0;
}

if (require.main === module) {
  try {
    const exitCode = main();
    process.exitCode = exitCode;
  } catch (error) {
    console.error(
      JSON.stringify(
        {
          error: 'i18n-sync-unhandled',
          message: error.message || String(error),
        },
        null,
        2,
      ),
    );
    process.exitCode = 1;
  }
}

module.exports = { main };
