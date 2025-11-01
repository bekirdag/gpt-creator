import { AuthShieldConfig } from './types';
import { LockoutService } from './lockout';

type LockedError = Error & { status?: number; body?: Record<string, unknown> };

export function makeLoginFlow(cfg: AuthShieldConfig) {
  const lockout = new LockoutService(cfg);

  return {
    precheck: async (emailRaw: string, ip: string) => {
      const email = emailRaw.trim().toLowerCase();
      const ipHash = cfg.hashIp ? cfg.hashIp(ip) : ip;
      const state = await lockout.precheck(email, ipHash);

      if (state.active) {
        cfg.metrics?.inc('auth_login_failure_total', { scope: 'admin', reason: 'locked' });
        cfg.telemetry?.emit('admin_login_attempt', {
          outcome: 'locked',
          lockoutState: state.reason === 'hard' ? 'active' : 'cooldown',
          source: 'web'
        });
        const now = (cfg.now ?? Date.now)();
        const retryAfter = state.until ? Math.max(0, Math.floor((state.until - now) / 1000)) : 0;
        const err: LockedError = new Error('LOCKED');
        err.status = 423;
        err.body = {
          code: 'LOCKED',
          retryAfter,
          lockoutExpiresAt: state.until
        };
        throw err;
      }

      return { email, ipHash };
    },

    onFailure: async (emailLower: string, ipHash: string) => {
      await lockout.recordFailure(emailLower, ipHash);
      cfg.metrics?.inc('auth_login_failure_total', { scope: 'admin', reason: 'invalid_credentials' });
      cfg.telemetry?.emit('admin_login_attempt', {
        outcome: 'invalid_credentials',
        lockoutState: 'none',
        source: 'web'
      });
    },

    onSuccess: async () => {
      cfg.metrics?.inc('auth_login_success_total', { scope: 'admin' });
      cfg.telemetry?.emit('admin_login_attempt', { outcome: 'success', lockoutState: 'none', source: 'web' });
    },

    onClear: async (emailLower: string, ipHash: string) => {
      await lockout.clear(emailLower, ipHash);
    }
  };
}
