# @org/auth-shield

Reusable guardrail toolkit for enforcing admin authentication invariants across Node.js, Express, and NestJS applications. The package bundles lockout, session policy, RBAC, CSRF, and audit/telemetry helpers so every project shares the same defence-in-depth posture.

## Features

- Shared interfaces for sessions, lockout stores, audit sinks, metrics, and telemetry.
- Pre-flight lockout evaluation with configurable thresholds (IP, 15 minute cooldown, 24 hour hard lock).
- Session policy enforcing absolute and idle TTLs (defaults 12h absolute, 2h idle).
- Express middleware helpers (`requireSession`, `requireAdmin`, `requireCsrf`).
- NestJS guards (`SessionGuard`, `AdminRbacGuard`, `CsrfGuard`) plus a coverage assertion to fail CI when an `/admin` route ships without RBAC.
- Login flow wrapper to centralise success/failure instrumentation.

## Installation

```bash
pnpm add @org/auth-shield
# or
npm install @org/auth-shield
```

Implement the store/sink interfaces for your environment (Redis, Prisma, etc.) and pass them to the helpers.

## Express example

```ts
import express from 'express';
import cookieParser from 'cookie-parser';
import { expressAuthShield } from '@org/auth-shield';
import { buildAuthShieldConfig } from './authShieldConfig';

const app = express();
app.use(cookieParser());
const shield = expressAuthShield(buildAuthShieldConfig());

app.get('/admin/programs', shield.requireSession, shield.requireAdmin, (req, res) => {
  res.json([]);
});

app.post('/api/v1/auth/logout', shield.requireSession, shield.requireCsrf, async (req, res) => {
  // revoke session, emit audit log, etc.
  res.sendStatus(204);
});
```

## NestJS example

```ts
import { Module, UseGuards, Controller, Get } from '@nestjs/common';
import { SessionGuard, AdminRbacGuard, CsrfGuard, assertAdminRoutesGuarded } from '@org/auth-shield';
import { buildAuthShieldConfig } from './authShieldConfig';

@Module({
  providers: [
    { provide: SessionGuard, useFactory: buildAuthShieldConfig },
    { provide: AdminRbacGuard, useFactory: buildAuthShieldConfig },
    CsrfGuard
  ]
})
export class AppModule {}

@Controller('admin/programs')
@UseGuards(SessionGuard, AdminRbacGuard)
export class AdminProgramsController {
  @Get()
  list() {
    return [];
  }
}
```

Add a guard coverage test to your CI pipeline:

```ts
import { Test } from '@nestjs/testing';
import { AppModule } from '../src/app.module';
import { assertAdminRoutesGuarded } from '@org/auth-shield';

describe('Admin guard coverage', () => {
  it('protects every /admin route', async () => {
    const mod = await Test.createTestingModule({ imports: [AppModule] }).compile();
    const app = mod.createNestApplication();
    await app.init();
    const modulesContainer = (app as any).container.getModules();
    await assertAdminRoutesGuarded(modulesContainer);
    await app.close();
  });
});
```

## Login flow helper

```ts
import { makeLoginFlow } from '@org/auth-shield';
import { cfg } from './authShieldConfig';

export async function login(email: string, password: string, ip: string) {
  const flow = makeLoginFlow(cfg);
  const { email: normEmail, ipHash } = await flow.precheck(email, ip);
  // Lookup user and verify password…
  const ok = false; // replace with hash compare
  if (!ok) {
    await flow.onFailure(normEmail, ipHash);
    return { status: 401, body: { code: 'INVALID_CREDENTIALS' } };
  }
  await flow.onSuccess();
  return { status: 204 };
}
```

All helpers are configurable through the `AuthShieldConfig` object. Override TTLs, lockout thresholds, or role lists to match project-specific policy without duplicating implementation.
