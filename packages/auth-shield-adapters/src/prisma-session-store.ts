import type { PrismaClient } from '@prisma/client';
import { customAlphabet } from 'nanoid';
import type { Role, SessionInfo, SessionStore, UserIdentity } from '@org/auth-shield';

export interface PrismaSessionStoreOptions {
  prisma: PrismaClient;
  /**
    * Optional factory to generate session identifiers. Defaults to a url-friendly nanoid.
    */
  idFactory?: () => string;
  /**
    * Optional override for selecting session records. Defaults to `prisma.session`.
    */
  sessionDelegate?: {
    findUnique(args: unknown): Promise<any>;
    upsert(args: unknown): Promise<any>;
    delete(args: unknown): Promise<any>;
    create(args: unknown): Promise<any>;
  };
}

type PrismaSessionRecord = {
  id: string;
  userId: number | null;
  createdAt: Date;
  lastSeenAt: Date;
  absoluteExpiresAt: Date;
  idleExpiresAt: Date;
  csrfToken: string;
  user?: {
    id: number;
    email: string;
    role: string;
    isActive?: boolean | null;
    is_active?: boolean | null;
  } | null;
};

const DEFAULT_ID = customAlphabet('0123456789abcdefghijklmnopqrstuvwxyz', 32);

export class PrismaSessionStore implements SessionStore {
  private readonly prisma: PrismaClient;
  private readonly sessionDelegate: Required<PrismaSessionStoreOptions['sessionDelegate']>;
  private readonly idFactory: () => string;

  constructor(options: PrismaSessionStoreOptions) {
    this.prisma = options.prisma;
    this.idFactory = options.idFactory ?? DEFAULT_ID;
    const delegate =
      options.sessionDelegate ??
      ((this.prisma as unknown as { session?: PrismaSessionStoreOptions['sessionDelegate'] }).session);

    if (!delegate) {
      throw new Error('PrismaSessionStore requires a session delegate (prisma.session).');
    }

    this.sessionDelegate = delegate as Required<PrismaSessionStoreOptions['sessionDelegate']>;
  }

  async get(sessionId: string): Promise<SessionInfo | null> {
    const record = await this.sessionDelegate.findUnique({
      where: { id: sessionId },
      include: {
        user: true
      }
    });
    if (!record) {
      return null;
    }
    return this.toSessionInfo(record as PrismaSessionRecord);
  }

  async set(session: SessionInfo): Promise<void> {
    const data = this.toPersistence(session);
    await this.sessionDelegate.upsert({
      where: { id: session.id },
      create: data,
      update: data
    });
  }

  async revoke(sessionId: string): Promise<void> {
    try {
      await this.sessionDelegate.delete({
        where: { id: sessionId }
      });
    } catch (err: unknown) {
      /**
       * Ignore not-found errors so revoke remains idempotent across drivers.
       */
      if (typeof err !== 'object' || err === null) {
        throw err;
      }
      const message = (err as { message?: string }).message ?? '';
      if (!/not\s+found/i.test(message)) {
        throw err;
      }
    }
  }

  async rotate(sessionId: string): Promise<string> {
    const existing = await this.get(sessionId);
    if (!existing) {
      throw new Error(`Cannot rotate unknown session: ${sessionId}`);
    }
    const newId = this.idFactory();
    const data = this.toPersistence({ ...existing, id: newId });

    await this.prisma.$transaction(async (tx) => {
      const delegate = (tx as unknown as { session: Required<PrismaSessionStoreOptions['sessionDelegate']> })
        .session;
      await delegate.delete({ where: { id: sessionId } });
      await delegate.create({ data });
    });

    return newId;
  }

  private toSessionInfo(record: PrismaSessionRecord): SessionInfo {
    const createdAt = record.createdAt.getTime();
    const lastSeenAt = record.lastSeenAt.getTime();
    const absoluteExpiresAt = record.absoluteExpiresAt.getTime();
    const idleExpiresAt = record.idleExpiresAt.getTime();

    return {
      id: record.id,
      user: this.toUserIdentity(record.user),
      createdAt,
      lastSeenAt,
      absoluteTtlMs: Math.max(0, absoluteExpiresAt - createdAt),
      idleTtlMs: Math.max(0, idleExpiresAt - lastSeenAt),
      csrfToken: record.csrfToken
    };
  }

  private toPersistence(session: SessionInfo) {
    const createdAt = new Date(session.createdAt);
    const lastSeenAt = new Date(session.lastSeenAt);
    const absoluteExpiresAt = new Date(session.createdAt + session.absoluteTtlMs);
    const idleExpiresAt = new Date(session.lastSeenAt + session.idleTtlMs);

    return {
      id: session.id,
      userId: session.user?.id ?? null,
      createdAt,
      lastSeenAt,
      absoluteExpiresAt,
      idleExpiresAt,
      csrfToken: session.csrfToken
    };
  }

  private toUserIdentity(
    user: PrismaSessionRecord['user']
  ): UserIdentity | undefined {
    if (!user) {
      return undefined;
    }
    const isActive = user.isActive ?? user.is_active ?? false;
    const role = (user.role ?? 'user') as Role;
    return {
      id: user.id,
      email: user.email,
      role,
      isActive
    };
  }
}
