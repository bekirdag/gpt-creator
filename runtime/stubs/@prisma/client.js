class PrismaClient {
  async $connect() {}
  async $disconnect() {}
  async $executeRaw() {
    return 0;
  }
}

module.exports = {
  PrismaClient,
};
