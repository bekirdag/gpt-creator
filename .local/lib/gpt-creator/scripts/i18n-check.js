#!/usr/bin/env node
'use strict';

const { collectLocaleIssues } = require('./i18n-utils.js');

function main() {
  const projectRoot = process.cwd();
  const { issues } = collectLocaleIssues(projectRoot);

  if (!issues.length) {
    return 0;
  }

  const payload = {
    issues,
  };
  console.error(JSON.stringify(payload, null, 2));
  return 2;
}

if (require.main === module) {
  const exitCode = main();
  process.exitCode = exitCode;
}

module.exports = { main };
