import { AuthShieldConfig, UserIdentity } from './types';

export function isAdmin(user: UserIdentity | undefined, cfg?: AuthShieldConfig): boolean {
  if (!user) {
    return false;
  }
  if (!user.isActive) {
    return false;
  }
  const allowed = cfg?.adminRoles ?? ['admin', 'editor'];
  return allowed.includes(user.role);
}
