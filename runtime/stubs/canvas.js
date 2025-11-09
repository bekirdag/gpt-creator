function noop() {}

function createCanvas() {
  return {
    getContext: () => ({ fillRect: noop, drawImage: noop }),
    toBuffer: () => Buffer.from([]),
    toDataURL: () => '',
  };
}

module.exports = {
  createCanvas,
  loadImage: async () => ({ width: 0, height: 0 }),
  Image: function Image() {},
};
