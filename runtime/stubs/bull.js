class Queue {
  constructor() {
    this.processors = [];
  }
  process(fn) {
    this.processors.push(fn);
  }
  add() {
    return Promise.resolve();
  }
  on() {}
  close() {
    return Promise.resolve();
  }
}

module.exports = { Queue };
