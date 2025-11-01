# @org/auth-shield-adapters

Redis + Prisma adapters for the `SessionStore` and `LockoutStore` interfaces defined by [`@org/auth-shield`](../auth-shield/README.md). Drop these into projects that already use Prisma for persistence and Redis for rate limiting / counters to get production-ready implementations with minimal wiring.

## Installation

```bash
pnpm add @org/auth-shield @org/auth-shield-adapters ioredis @prisma/client
# or npm/yarn equivalents
```

Ensure your Prisma schema exposes a `session` model with the following fields (names can be adjusted via the Prisma delegate you pass in):

```prisma
model Session {
  id                String   @id
  userId            Int?
  createdAt         DateTime @default(now())
  lastSeenAt        DateTime @default(now())
  absoluteExpiresAt DateTime
  idleExpiresAt     DateTime
  csrfToken         String
  user              User?    @relation(fields: [userId], references: [id])
}

model User {
  id        Int     @id @default(autoincrement())
  email     String  @unique
  role      String
  isActive  Boolean @default(true)
  // ...
  sessions  Session[]
}
```

## Redis lockout store

```ts
import Redis from 'ioredis';
import { RedisLockoutStore } from '@org/auth-shield-adapters';

const redis = new Redis(process.env.REDIS_URL);
const lockoutStore = new RedisLockoutStore({
  redis,
  prefix: 'adm01:lockout:' // optional, helps scope keys per environment
});
```

The adapter respects the `LockoutStore` contract used by `LockoutService`:

- Counter keys honour their TTL the first time a failure is seen.
- Locks are stored as JSON payloads with an expiry matching `untilEpochMs`.
- Optional `now` override allows deterministic unit testing.

## Prisma session store

```ts
import { PrismaClient } from '@prisma/client';
import { PrismaSessionStore } from '@org/auth-shield-adapters';

const prisma = new PrismaClient();
const sessions = new PrismaSessionStore({ prisma });
```

The adapter:

- Stores absolute / idle expiry as dedicated columns (derives TTLs back into `SessionInfo`).
- Includes linked `User` records to hydrate `UserIdentity` for RBAC checks.
- Supports rotation via `rotate(id)` using a url-safe `nanoid` identifier (override with `idFactory` if desired).
- Treats `is_active` (snake case) and `isActive` fields as synonyms for compatibility with legacy schemas.

You can supply a custom Prisma delegate (`sessionDelegate`) if your model name differs (`prisma.adminSession`, etc.).

## Wiring everything together

```ts
import { expressAuthShield } from '@org/auth-shield';
import {
  buildPrismaRedisAuthShieldConfig
} from '@org/auth-shield-adapters';

const cfg = buildPrismaRedisAuthShieldConfig({
  prisma,
  redis,
  audit: myAuditSink,
  metrics: myMetrics,
  telemetry: myTelemetry,
  idleTtlMs: 30 * 60 * 1000,
  absoluteTtlMs: 12 * 60 * 60 * 1000,
  lockoutStore: { prefix: 'adm01:' }
});

const shield = expressAuthShield(cfg);
```

Pair these adapters with the guards/middleware provided by `@org/auth-shield` to enforce idle timeouts, RBAC, CSRF and lockout policy across every project that adopts the package.
