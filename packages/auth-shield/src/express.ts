import type { Request, Response, NextFunction } from 'express';
import { AuthShieldConfig } from './types';
import { SessionPolicy } from './session';
import { isAdmin } from './rbac';
import { verifyCsrf } from './csrf';

type Middleware = (req: Request, res: Response, next: NextFunction) => void | Promise<void>;

export function expressAuthShield(cfg: AuthShieldConfig): {
  requireSession: Middleware;
  requireAdmin: Middleware;
  requireCsrf: Middleware;
} {
  const policy = new SessionPolicy(cfg);

  const requireSession: Middleware = async (req, res, next) => {
    const sid = (req.cookies && req.cookies.session) || undefined;
    if (!sid) {
      res.status(401).json({ code: 'SESSION_EXPIRED' });
      return;
    }

    const sess = await cfg.sessions.get(sid);
    if (!sess) {
      res.status(401).json({ code: 'SESSION_EXPIRED' });
      return;
    }

    const verdict = policy.validate(sess);
    if (!verdict.ok) {
      res.status(401).json({ code: verdict.code, reauthUrl: '/login' });
      return;
    }

    await cfg.sessions.set(policy.touch(sess));
    (req as unknown as { user?: typeof sess.user }).user = sess.user;
    (res.locals as { csrfToken?: string }).csrfToken = sess.csrfToken;
    return next();
  };

  const requireAdmin: Middleware = (req, res, next) => {
    const user = (req as unknown as { user?: Parameters<typeof isAdmin>[0] }).user;
    if (!isAdmin(user, cfg)) {
      void cfg.audit.record('AUTH_LOGIN_FAILURE', { reason: 'non_admin', scope: 'admin' });
      cfg.telemetry?.emit('admin_login_attempt', { outcome: 'denied', lockoutState: 'none', source: 'web' });
      res.status(403).json({ code: 'FORBIDDEN' });
      return;
    }
    return next();
  };

  const requireCsrf: Middleware = (req, res, next) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method.toUpperCase())) {
      const match = verifyCsrf(req.header('x-csrf-token') ?? undefined, res.locals.csrfToken);
      if (!match) {
        res.status(403).json({ code: 'CSRF' });
        return;
      }
    }
    return next();
  };

  return {
    requireSession,
    requireAdmin,
    requireCsrf
  };
}
