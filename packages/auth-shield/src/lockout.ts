import { AuthShieldConfig, LockoutState } from './types';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;

export class LockoutService {
  constructor(private readonly cfg: AuthShieldConfig) {}

  private now(): number {
    return (this.cfg.now ?? Date.now)();
  }

  async precheck(emailLower: string, ipHash: string): Promise<LockoutState> {
    const acctKey = `acct:${emailLower}`;
    const ipKey = `ip:${ipHash}`;

    const [acct, ip] = await Promise.all([
      this.cfg.lockout.getLock(acctKey),
      this.cfg.lockout.getLock(ipKey)
    ]);

    if (acct.active) {
      return acct;
    }
    if (ip.active) {
      return ip;
    }
    return { active: false };
  }

  async recordFailure(emailLower: string, ipHash: string): Promise<void> {
    const now = this.now();
    const minuteBucket = Math.floor(now / MINUTE_MS);
    const fifteenBucket = Math.floor(now / (15 * MINUTE_MS));
    const dayBucket = Math.floor(now / (24 * HOUR_MS));

    const minuteKey = `ipfail:${ipHash}:${minuteBucket}`;
    const fifteenKey = `acct15:${emailLower}:${fifteenBucket}`;
    const dayKey = `acct24:${emailLower}:${dayBucket}`;

    const ipFails = await this.cfg.lockout.incrFailure(minuteKey, 75);
    if (ipFails >= (this.cfg.ipFailPerMinute ?? 5)) {
      await this.cfg.lockout.setLock(`ip:${ipHash}`, now + 5 * MINUTE_MS, 'threshold');
    }

    const acctCooldownFails = await this.cfg.lockout.incrFailure(
      fifteenKey,
      16 * MINUTE_MS
    );
    if (acctCooldownFails >= (this.cfg.acctCooldownFails15m ?? 10)) {
      await this.cfg.lockout.setLock(
        `acct:${emailLower}`,
        now + 15 * MINUTE_MS,
        'threshold'
      );
      return;
    }

    const acctHardFails = await this.cfg.lockout.incrFailure(dayKey, 25 * HOUR_MS);
    if (acctHardFails >= (this.cfg.acctHardFails24h ?? 15)) {
      await this.cfg.lockout.setLock(
        `acct:${emailLower}`,
        now + 24 * HOUR_MS,
        'hard'
      );
    }
  }

  async clear(emailLower: string, ipHash: string): Promise<void> {
    await Promise.all([
      this.cfg.lockout.clear(`ip:${ipHash}`),
      this.cfg.lockout.clear(`acct:${emailLower}`)
    ]);
  }
}
