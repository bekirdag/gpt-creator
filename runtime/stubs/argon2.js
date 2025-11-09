async function hash(value) {
  return `stub-${value}`;
}

async function verify() {
  return true;
}

module.exports = {
  hash,
  verify,
  needsRehash: () => false,
};
