import { AuthShieldConfig, SessionInfo } from './types';

const HOUR_MS = 60 * 60 * 1000;

export class SessionPolicy {
  constructor(private readonly cfg: AuthShieldConfig) {}

  private now(): number {
    return (this.cfg.now ?? Date.now)();
  }

  validate(session: SessionInfo): { ok: boolean; code?: 'SESSION_EXPIRED' | 'IDLE_TIMEOUT' } {
    const now = this.now();
    const absoluteTtl = this.cfg.absoluteTtlMs ?? 12 * HOUR_MS;
    const idleTtl = this.cfg.idleTtlMs ?? 2 * HOUR_MS;

    if (now - session.createdAt > absoluteTtl) {
      return { ok: false, code: 'SESSION_EXPIRED' };
    }
    if (now - session.lastSeenAt > idleTtl) {
      return { ok: false, code: 'IDLE_TIMEOUT' };
    }
    return { ok: true };
  }

  touch(session: SessionInfo): SessionInfo {
    const now = this.now();
    return {
      ...session,
      lastSeenAt: now
    };
  }
}
