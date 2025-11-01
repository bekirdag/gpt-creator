import {
  BadRequestException,
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  UnauthorizedException
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { GUARDS_METADATA, PATH_METADATA } from '@nestjs/common/constants';
import { AuthShieldConfig } from './types';
import { SessionPolicy } from './session';
import { isAdmin } from './rbac';
import { verifyCsrf } from './csrf';

@Injectable()
export class SessionGuard implements CanActivate {
  private readonly policy: SessionPolicy;

  constructor(private readonly cfg: AuthShieldConfig) {
    this.policy = new SessionPolicy(cfg);
  }

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    const req = ctx.switchToHttp().getRequest();
    const sid = req.cookies?.session;

    if (!sid) {
      throw new UnauthorizedException({ code: 'SESSION_EXPIRED' });
    }

    const sess = await this.cfg.sessions.get(sid);
    if (!sess) {
      throw new UnauthorizedException({ code: 'SESSION_EXPIRED' });
    }

    const verdict = this.policy.validate(sess);
    if (!verdict.ok) {
      throw new UnauthorizedException({ code: verdict.code, reauthUrl: '/admin/login' });
    }

    await this.cfg.sessions.set(this.policy.touch(sess));
    req.user = sess.user;
    req.csrfToken = sess.csrfToken;
    return true;
  }
}

@Injectable()
export class AdminRbacGuard implements CanActivate {
  constructor(private readonly cfg: AuthShieldConfig) {}

  canActivate(ctx: ExecutionContext): boolean {
    const req = ctx.switchToHttp().getRequest();
    if (!isAdmin(req.user, this.cfg)) {
      void this.cfg.audit.record('AUTH_LOGIN_FAILURE', { reason: 'non_admin', scope: 'admin' });
      this.cfg.telemetry?.emit('admin_login_attempt', { outcome: 'denied', lockoutState: 'none', source: 'web' });
      throw new ForbiddenException({ code: 'FORBIDDEN' });
    }
    return true;
  }
}

@Injectable()
export class CsrfGuard implements CanActivate {
  canActivate(ctx: ExecutionContext): boolean {
    const req = ctx.switchToHttp().getRequest();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method)) {
      if (!verifyCsrf(req.header('x-csrf-token'), req.csrfToken)) {
        throw new BadRequestException({ code: 'CSRF' });
      }
    }
    return true;
  }
}

interface NestModulesContainer {
  entries(): IterableIterator<[unknown, { controllers: Map<unknown, { metatype: any }> }]>;
}

export async function assertAdminRoutesGuarded(modulesContainer: NestModulesContainer): Promise<void> {
  const reflector = new Reflector();
  const offenders: string[] = [];

  for (const [, moduleRef] of modulesContainer.entries()) {
    for (const ctrl of moduleRef.controllers.values()) {
      const target = ctrl.metatype;
      if (!target?.prototype) {
        continue;
      }

      const basePath = reflector.get<string | undefined>(PATH_METADATA, target);
      const classGuards = reflector.getAllAndMerge(GUARDS_METADATA, [target]) ?? [];
      const methods = Object.getOwnPropertyNames(target.prototype).filter(
        (name) => name !== 'constructor' && typeof target.prototype[name] === 'function'
      );

      for (const methodName of methods) {
        const handler = target.prototype[methodName];
        const methodPath = reflector.get<string | undefined>(PATH_METADATA, handler);
        const methodGuards = reflector.getAllAndMerge(GUARDS_METADATA, [handler]) ?? [];
        const fullPath = `/${[basePath, methodPath].filter(Boolean).join('/')}`.replace(/\/+/g, '/');

        if (!fullPath.startsWith('/admin')) {
          continue;
        }

        const guardStack = [...classGuards, ...methodGuards];
        const guarded = guardStack.some((g) => {
          const ctor = typeof g === 'function' ? g : g?.constructor;
          return ctor?.name === 'AdminRbacGuard';
        });

        if (!guarded) {
          offenders.push(`${target.name}.${methodName} → ${fullPath}`);
        }
      }
    }
  }

  if (offenders.length > 0) {
    throw new Error(`Unprotected admin routes detected:\n${offenders.join('\n')}`);
  }
}
