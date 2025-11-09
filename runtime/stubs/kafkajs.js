class Producer {
  async connect() {}
  async disconnect() {}
  async send() {}
}

class Consumer {
  async connect() {}
  async disconnect() {}
  async run() {}
  subscribe() {}
}

class Kafka {
  producer() {
    return new Producer();
  }
  consumer() {
    return new Consumer();
  }
}

module.exports = {
  Kafka,
};
