class Redis {
  constructor() {
    this.data = new Map();
  }
  async get(key) {
    return this.data.get(key) || null;
  }
  async set(key, value) {
    this.data.set(key, value);
  }
  duplicate() {
    return new Redis();
  }
  on() {}
  quit() {
    return Promise.resolve();
  }
}

module.exports = Redis;
