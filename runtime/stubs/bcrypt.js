async function hash(value) {
  return `stub-${value}`;
}

async function compare() {
  return true;
}

module.exports = {
  hash,
  hashSync: (value) => `stub-${value}`,
  compare,
  compareSync: () => true,
  genSalt: async () => 'stub-salt',
  genSaltSync: () => 'stub-salt',
};
