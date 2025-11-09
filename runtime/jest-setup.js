/* eslint-disable import/no-dynamic-require, global-require */
try {
  const timeout = Number(process.env.GC_JEST_TIMEOUT || 60000);
  if (typeof jest !== 'undefined' && typeof jest.setTimeout === 'function') {
    jest.setTimeout(timeout);
  }
} catch {
  // ignore
}

process.env.TZ = process.env.TZ || 'UTC';

const path = require('path');
const stubsDir = path.join(__dirname, 'stubs');

const STUBS = new Map(
  Object.entries({
    'sharp': path.join(stubsDir, 'sharp.js'),
    'canvas': path.join(stubsDir, 'canvas.js'),
    'multer': path.join(stubsDir, 'multer.js'),
    'prom-client': path.join(stubsDir, 'prom-client.js'),
    'bcrypt': path.join(stubsDir, 'bcrypt.js'),
    'argon2': path.join(stubsDir, 'argon2.js'),
    '@prisma/client': path.join(stubsDir, '@prisma', 'client.js'),
    'bull': path.join(stubsDir, 'bull.js'),
    'ioredis': path.join(stubsDir, 'ioredis.js'),
    'amqplib': path.join(stubsDir, 'amqplib.js'),
    'kafkajs': path.join(stubsDir, 'kafkajs.js'),
  }),
);

if (typeof jest !== 'undefined' && typeof jest.doMock === 'function') {
  for (const [moduleName, stubPath] of STUBS.entries()) {
    try {
      require.resolve(moduleName);
    } catch {
      try {
        jest.doMock(
          moduleName,
          () => require(stubPath),
          { virtual: true },
        );
      } catch {
        // ignore broken mocks
      }
    }
  }
}
