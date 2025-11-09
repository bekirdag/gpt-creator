const path = require('path');

let defaultResolver = (request, options) => {
  const resolver = options?.defaultResolver || require('jest-resolve/build/defaultResolver');
  return (resolver.default || resolver)(request, options);
};

const HEAVY = new Set([
  'sharp',
  'canvas',
  'multer',
  'prom-client',
  'bcrypt',
  'argon2',
  '@prisma/client',
  'bull',
  'ioredis',
  'amqplib',
  'kafkajs',
]);

const FALLBACK_DIRS = ['src', 'lib', 'build', 'out'];

function rewriteDist(request, basedir) {
  if (!/(^|\/)dist(\/|$)/.test(request)) {
    return [];
  }
  const candidates = new Set();
  for (const dir of FALLBACK_DIRS) {
    candidates.add(request.replace(/(^|\/)dist(\/|$)/, `$1${dir}$2`));
    try {
      const absolute = path.resolve(basedir, request);
      const swapped = absolute.replace(/(^|\/)dist(\/|$)/, `$1${dir}$2`);
      candidates.add(path.relative(basedir, swapped) || swapped);
    } catch {
      // ignore
    }
  }
  return Array.from(candidates);
}

function stubPath(request) {
  if (request === '@prisma/client') {
    return path.join(__dirname, 'stubs', '@prisma', 'client.js');
  }
  return path.join(__dirname, 'stubs', `${request}.js`);
}

module.exports = (request, options = {}) => {
  try {
    return defaultResolver(request, options);
  } catch (err) {
    const rewrites = rewriteDist(request, options.basedir || process.cwd());
    for (const candidate of rewrites) {
      try {
        return defaultResolver(candidate, options);
      } catch {
        // continue
      }
    }
    if (HEAVY.has(request)) {
      return require.resolve(stubPath(request));
    }
    throw err;
  }
};
