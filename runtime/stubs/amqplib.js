module.exports = {
  connect: async () => ({
    createChannel: async () => ({
      assertQueue: async () => {},
      consume: () => {},
      sendToQueue: () => {},
      ack: () => {},
      close: async () => {},
    }),
    close: async () => {},
  }),
};
