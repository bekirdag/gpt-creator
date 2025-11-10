/** @type {import('@pnpm/pnpmfile').Pnpmfile} */
const pnpmfile = {
  hooks: {
    readPackage(pkg) {
      return pkg;
    },
  },
};

export default pnpmfile;
