export const ADMIN_MODULES = new Set<string>([
  'users',
  'roles',
  'instructor-audit',
]);

export const isAdminModuleEnabled = (moduleName: string): boolean =>
  ADMIN_MODULES.has(moduleName);
