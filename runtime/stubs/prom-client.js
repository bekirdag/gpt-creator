class NoopMetric {
  labels() {
    return this;
  }
  inc() {}
  dec() {}
  set() {}
  observe() {}
}

const register = {
  metrics: async () => '',
  clear() {},
  getSingleMetric() {
    return null;
  },
};

module.exports = {
  Counter: NoopMetric,
  Gauge: NoopMetric,
  Histogram: NoopMetric,
  Summary: NoopMetric,
  register,
  collectDefaultMetrics: () => {},
};
