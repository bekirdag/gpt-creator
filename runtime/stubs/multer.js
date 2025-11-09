function multer() {
  return function middleware(_req, _res, next) {
    if (typeof next === 'function') {
      next();
    }
  };
}

class MulterError extends Error {}

module.exports = Object.assign(multer, {
  MulterError,
  diskStorage: () => ({}),
  memoryStorage: () => ({}),
});
