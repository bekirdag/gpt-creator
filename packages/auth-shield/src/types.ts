export type Role = 'admin' | 'editor' | 'instructor' | 'user';

export interface UserIdentity {
  id: number;
  email: string;
  role: Role;
  isActive: boolean;
}

export interface SessionInfo {
  id: string;
  user?: UserIdentity;
  createdAt: number;
  lastSeenAt: number;
  absoluteTtlMs: number;
  idleTtlMs: number;
  csrfToken: string;
}

export interface LockoutState {
  active: boolean;
  until?: number;
  reason?: 'threshold' | 'hard';
}

export interface LockoutStore {
  getFailures(key: string): Promise<number>;
  incrFailure(key: string, ttlSeconds: number): Promise<number>;
  getLock(key: string): Promise<LockoutState>;
  setLock(key: string, untilEpochMs: number, reason: LockoutState['reason']): Promise<void>;
  clear(key: string): Promise<void>;
}

export interface AuditSink {
  record(event: string, payload: Record<string, unknown>): Promise<void>;
}

export interface Metrics {
  inc(name: string, labels?: Record<string, string>): void;
  observe(name: string, value: number, labels?: Record<string, string>): void;
}

export interface Telemetry {
  emit(event: string, props: Record<string, unknown>): void;
}

export interface SessionStore {
  get(sessionId: string): Promise<SessionInfo | null>;
  set(session: SessionInfo): Promise<void>;
  revoke(sessionId: string): Promise<void>;
  rotate(sessionId: string): Promise<string>;
}

export interface AuthShieldConfig {
  absoluteTtlMs?: number;
  idleTtlMs?: number;
  adminRoles?: Role[];
  sameSite?: 'Strict' | 'Lax';

  ipFailPerMinute?: number;
  acctCooldownFails15m?: number;
  acctHardFails24h?: number;

  sessions: SessionStore;
  lockout: LockoutStore;
  audit: AuditSink;
  metrics?: Metrics;
  telemetry?: Telemetry;
  now?: () => number;
  hashIp?: (ip: string) => string;
}
