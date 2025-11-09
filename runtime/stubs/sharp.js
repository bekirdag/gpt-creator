module.exports = new Proxy(function () {}, {
  get: () => new Proxy(function () {}, { apply: () => undefined }),
  apply: () => ({}),
});
