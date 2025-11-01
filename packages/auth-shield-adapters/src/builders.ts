import type { PrismaClient } from '@prisma/client';
import type { Redis } from 'ioredis';
import type { AuditSink, AuthShieldConfig, Metrics, Telemetry } from '@org/auth-shield';
import { PrismaSessionStore, PrismaSessionStoreOptions } from './prisma-session-store';
import { RedisLockoutStore, RedisLockoutStoreOptions } from './redis-lockout-store';

export interface PrismaRedisConfigOptions {
  prisma: PrismaClient;
  redis: Redis;
  audit: AuditSink;
  metrics?: Metrics;
  telemetry?: Telemetry;
  idleTtlMs?: number;
  absoluteTtlMs?: number;
  adminRoles?: AuthShieldConfig['adminRoles'];
  sessionStore?: Omit<PrismaSessionStoreOptions, 'prisma'>;
  lockoutStore?: Omit<RedisLockoutStoreOptions, 'redis'>;
}

export function buildPrismaRedisAuthShieldConfig(options: PrismaRedisConfigOptions): AuthShieldConfig {
  const sessionStore = new PrismaSessionStore({
    prisma: options.prisma,
    ...(options.sessionStore ?? {})
  });

  const lockoutStore = new RedisLockoutStore({
    redis: options.redis,
    ...(options.lockoutStore ?? {})
  });

  return {
    sessions: sessionStore,
    lockout: lockoutStore,
    audit: options.audit,
    metrics: options.metrics,
    telemetry: options.telemetry,
    idleTtlMs: options.idleTtlMs,
    absoluteTtlMs: options.absoluteTtlMs,
    adminRoles: options.adminRoles
  };
}
