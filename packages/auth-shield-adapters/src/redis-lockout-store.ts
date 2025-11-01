import type { LockoutState, LockoutStore } from '@org/auth-shield';
import type { Redis } from 'ioredis';

export interface RedisLockoutStoreOptions {
  /**
   * Redis connection.
   */
  redis: Redis;
  /**
   * Optional prefix applied to every key (e.g., "prod:auth:").
   */
  prefix?: string;
  /**
   * Clock override (defaults to Date.now).
   */
  now?: () => number;
}

const DEFAULT_PREFIX = '';

export class RedisLockoutStore implements LockoutStore {
  private readonly redis: Redis;
  private readonly prefix: string;
  private readonly now: () => number;

  constructor(options: RedisLockoutStoreOptions) {
    this.redis = options.redis;
    this.prefix = options.prefix ?? DEFAULT_PREFIX;
    this.now = options.now ?? Date.now;
  }

  private key(id: string): string {
    return `${this.prefix}${id}`;
  }

  async getFailures(key: string): Promise<number> {
    const raw = await this.redis.get(this.key(key));
    if (!raw) {
      return 0;
    }
    const value = Number(raw);
    return Number.isFinite(value) ? value : 0;
  }

  async incrFailure(key: string, ttlSeconds: number): Promise<number> {
    const redisKey = this.key(key);
    const value = await this.redis.incr(redisKey);
    if (value === 1 && ttlSeconds > 0) {
      await this.redis.expire(redisKey, ttlSeconds);
    }
    return value;
  }

  async getLock(key: string): Promise<LockoutState> {
    const redisKey = this.key(key);
    const raw = await this.redis.get(redisKey);
    if (!raw) {
      return { active: false };
    }
    try {
      const parsed = JSON.parse(raw) as LockoutState;
      if (parsed.active && parsed.until && parsed.until <= this.now()) {
        await this.redis.del(redisKey);
        return { active: false };
      }
      return parsed;
    } catch {
      await this.redis.del(redisKey);
      return { active: false };
    }
  }

  async setLock(key: string, untilEpochMs: number, reason: LockoutState['reason']): Promise<void> {
    const redisKey = this.key(key);
    const ttlMs = Math.max(1, untilEpochMs - this.now());
    const payload: LockoutState = {
      active: true,
      until: untilEpochMs,
      reason
    };
    await this.redis.set(redisKey, JSON.stringify(payload), 'PX', ttlMs);
  }

  async clear(key: string): Promise<void> {
    await this.redis.del(this.key(key));
  }
}
