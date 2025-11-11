const Module = require('module');
const path = require('path');
const fs = require('fs');

const original = Module._resolveFilename;
const SHIMS = new Map();
const SPECIAL_SHIMS = new Map([
  [
    '@prisma/client',
    `
      class PrismaClient {
        async $connect() {}
        async $disconnect() {}
      }
      module.exports = { PrismaClient };
    `,
  ],
]);

function makeShim(request) {
  const dir = path.join(process.cwd(), '.gpt-creator', 'runtime', 'shims');
  fs.mkdirSync(dir, { recursive: true });
  const safeName = request.replace(/[\/:]/g, '_');
  const file = path.join(dir, `${safeName}.js`);
  if (!fs.existsSync(file)) {
    const special = SPECIAL_SHIMS.get(request);
    const body = special
      ? `
        // Auto-generated shim for ${request}
        ${special}
      `
      : `
        // Auto-generated stub for missing module: ${request}
        module.exports = new Proxy(function () {}, {
          get: () => new Proxy(function () {}, { apply: () => undefined }),
          apply: () => undefined,
        });
      `;
    fs.writeFileSync(file, body);
  }
  return file;
}

Module._resolveFilename = function (request, parent, isMain, options) {
  try {
    return original.call(this, request, parent, isMain, options);
  } catch (error) {
    if (error && error.code === 'MODULE_NOT_FOUND') {
      if (!SHIMS.has(request)) {
        SHIMS.set(request, makeShim(request));
      }
      return SHIMS.get(request);
    }
    throw error;
  }
};
